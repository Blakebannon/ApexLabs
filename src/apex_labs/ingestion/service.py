"""Dataset ingestion orchestration and integrity-aware inspection."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from apex_labs.atomic import atomic_output_directory
from apex_labs.errors import IngestionError, IntegrityError
from apex_labs.experiments import verify_protocol_freeze
from apex_labs.ingestion.tabular_csv import ADAPTER_ID, ADAPTER_VERSION, normalize_csv
from apex_labs.io import canonical_json_bytes, iter_json_lines, parse_json_bytes, read_json, resolve_relative_file, write_json
from apex_labs.normalization.integrity import NormalizedIntegrityTracker
from apex_labs.provenance import (
    apex_labs_code_identity,
    build_dataset_fingerprint,
    canonical_manifest_sha256,
    dataset_fingerprint,
    normalized_dataset_fingerprint_basis,
    require_research_code_identity,
    sha256_bytes,
    sha256_file,
    snapshot_source_files,
    verify_source_files,
)
from apex_labs.schemas import (
    validate_collection_record,
    validate_adapter_conformance,
    validate_dataset_manifest,
    validate_normalized_manifest,
    validate_normalized_record,
    validate_product_annotations,
)
from apex_labs.schemas.versions import NORMALIZATION_VERSION, NORMALIZED_MANIFEST


def _load_source(manifest_path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        manifest_bytes = manifest_path.read_bytes()
    except FileNotFoundError as exc:
        raise IngestionError(f"Source manifest does not exist: {manifest_path}") from exc
    manifest = validate_dataset_manifest(parse_json_bytes(manifest_bytes, source=str(manifest_path)))
    return manifest, manifest_bytes


def _verify_collection_protocol(
    manifest: dict[str, Any], source_paths: dict[str, Path]
) -> None:
    reference = manifest["collection_context"]["protocol_snapshot"]
    if reference is None:
        return
    snapshot = verify_protocol_freeze(read_json(source_paths[reference["path"]]))
    comparisons = {
        "freeze_id": snapshot["freeze_id"],
        "freeze_sha256": snapshot["freeze_sha256"],
        "experiment_id": snapshot["protocol_id"],
        "experiment_version": snapshot["protocol_version"],
        "schedule_id": snapshot["randomization"]["schedule_id"],
        "schedule_sha256": snapshot["randomization"]["schedule_sha256"],
    }
    for field, actual in comparisons.items():
        if reference[field] != actual:
            raise IntegrityError(
                f"Dataset collection protocol reference mismatch for {field}: declared {reference[field]!r}, actual {actual!r}"
            )
    if snapshot["synthetic"] != manifest["synthetic"]:
        raise IntegrityError("Dataset and frozen protocol synthetic classifications differ")


def ingest_dataset(
    manifest_path: Path,
    output_dir: Path,
    *,
    project_root: Path | None = None,
) -> dict[str, Any]:
    manifest_path = manifest_path.resolve()
    manifest, manifest_bytes = _load_source(manifest_path)
    adapter = manifest["adapter"]
    if adapter["id"] != ADAPTER_ID or adapter["version"] != ADAPTER_VERSION:
        raise IngestionError(
            f"Unsupported adapter {adapter['id']} {adapter['version']}; supported: {ADAPTER_ID} {ADAPTER_VERSION}"
        )
    code_identity = apex_labs_code_identity(project_root)
    require_research_code_identity(code_identity, synthetic=manifest["synthetic"])
    temporal_policy = adapter["configuration"]["temporal_policy"]
    conventions = adapter["configuration"]["conventions"]

    with atomic_output_directory(output_dir, operation="ingest", error_type=IngestionError) as staged:
        with TemporaryDirectory(prefix=".apex-labs-source-snapshot-", dir=output_dir.resolve().parent) as temporary:
            source_paths = snapshot_source_files(manifest, manifest_path.parent, Path(temporary))
            _verify_collection_protocol(manifest, source_paths)
            records, capabilities, unknown_channels = normalize_csv(manifest, source_paths)
            records_path = staged / "records.jsonl"
            tracker = NormalizedIntegrityTracker(manifest["dataset_id"], temporal_policy)
            with records_path.open("wb") as handle:
                for sequence_index, record in enumerate(records):
                    record["sequence_index"] = sequence_index
                    validate_normalized_record(record)
                    tracker.add(record)
                    validate_normalized_record(record)
                    handle.write(canonical_json_bytes(record))
            integrity_summary = tracker.finalize()

        normalized_manifest: dict[str, Any] = {
            "schema_version": NORMALIZED_MANIFEST,
            "dataset_id": manifest["dataset_id"],
            "dataset_fingerprint": "0" * 64,
            "source_fingerprint": dataset_fingerprint(manifest),
            "synthetic": manifest["synthetic"],
            "created_at": manifest["created_at"],
            "source_manifest_sha256": sha256_bytes(manifest_bytes),
            "canonical_source_manifest_sha256": canonical_manifest_sha256(manifest),
            "normalization_version": NORMALIZATION_VERSION,
            "adapter": {
                "id": adapter["id"],
                "version": adapter["version"],
                "configuration": adapter["configuration"],
            },
            "code_identity": code_identity,
            "preprocessing": {
                "pipeline_id": "tabular-csv-normalization",
                "pipeline_version": ADAPTER_VERSION,
                "configuration": adapter["configuration"],
                "configuration_sha256": sha256_bytes(
                    canonical_json_bytes(adapter["configuration"])
                ),
            },
            "collection_context": manifest["collection_context"],
            "temporal_policy": temporal_policy,
            "conventions": conventions,
            "integrity_summary": integrity_summary,
            "records_file": "records.jsonl",
            "records_sha256": sha256_file(records_path),
            "record_counts": dict(tracker.counts),
            "source_files": [
                {
                    "path": item["path"],
                    "sha256": item["sha256"],
                    "role": item["role"],
                    "media_type": item["media_type"],
                }
                for item in sorted(manifest["source_files"], key=lambda item: item["path"].casefold())
            ],
            "capabilities": capabilities,
            "unknown_source_channels": unknown_channels,
        }
        normalized_manifest["dataset_fingerprint"] = build_dataset_fingerprint(
            normalized_dataset_fingerprint_basis(normalized_manifest)
        )
        validate_normalized_manifest(normalized_manifest)
        write_json(staged / "manifest.json", normalized_manifest)
    return normalized_manifest


def inspect_dataset(manifest_path: Path, *, validate_records: bool = True) -> dict[str, Any]:
    value = read_json(manifest_path)
    schema_version = value.get("schema_version") if isinstance(value, dict) else None
    if schema_version == NORMALIZED_MANIFEST:
        manifest = validate_normalized_manifest(value)
        records_path = resolve_relative_file(manifest_path.parent, manifest["records_file"])
        actual_hash = sha256_file(records_path)
        if actual_hash != manifest["records_sha256"]:
            raise IntegrityError(
                f"Normalized records hash mismatch: declared {manifest['records_sha256']}, actual {actual_hash}"
            )
        expected_fingerprint = build_dataset_fingerprint(
            normalized_dataset_fingerprint_basis(manifest)
        )
        if expected_fingerprint != manifest["dataset_fingerprint"]:
            raise IntegrityError("Normalized dataset fingerprint does not match its provenance/content basis")
        native_validators = {
            "collection_record": validate_collection_record,
            "product_annotations": validate_product_annotations,
            "adapter_conformance": validate_adapter_conformance,
        }
        for field, validator in native_validators.items():
            if field not in manifest:
                continue
            reference = manifest[field]
            artifact_path = resolve_relative_file(manifest_path.parent, reference["path"])
            if sha256_file(artifact_path) != reference["sha256"]:
                raise IntegrityError(f"Normalized {field} hash mismatch")
            if validator is not None:
                validator(read_json(artifact_path))
        tracker = NormalizedIntegrityTracker(manifest["dataset_id"], manifest["temporal_policy"])
        actual_counts: Counter[str] = Counter()
        for index, record in enumerate(iter_json_lines(records_path)):
            if validate_records:
                try:
                    validated = validate_normalized_record(record)
                    original_flags = list(validated.get("quality_flags", []))
                    tracker.add(validated)
                    if validated.get("quality_flags", []) != original_flags:
                        raise IntegrityError("stored quality flags omit a deterministically detectable defect")
                except Exception as exc:
                    raise IntegrityError(f"Invalid normalized record at zero-based index {index}: {exc}") from exc
                record_type = validated["record_type"]
            else:
                record_type = record.get("record_type") if isinstance(record, dict) else None
            actual_counts[record_type] += 1
        if dict(actual_counts) != manifest["record_counts"]:
            raise IntegrityError(
                f"Record counts mismatch: declared {manifest['record_counts']}, actual {dict(actual_counts)}"
            )
        if validate_records and tracker.finalize() != manifest["integrity_summary"]:
            raise IntegrityError("Normalized integrity summary does not match record content")
        return {
            "kind": "normalized_dataset",
            "dataset_id": manifest["dataset_id"],
            "fingerprint": manifest["dataset_fingerprint"],
            "source_fingerprint": manifest["source_fingerprint"],
            "synthetic": manifest["synthetic"],
            "integrity": "verified",
            "record_counts": manifest["record_counts"],
            "quality_flag_counts": manifest["integrity_summary"]["quality_flag_counts"],
            "available_capabilities": sorted(
                name for name, capability in manifest["capabilities"].items()
                if capability["provenance"] != "unavailable"
            ),
            "unavailable_capability_count": sum(
                capability["provenance"] == "unavailable"
                for capability in manifest["capabilities"].values()
            ),
            "unknown_source_channels": manifest["unknown_source_channels"],
        }
    manifest_path = manifest_path.resolve()
    manifest, _ = _load_source(manifest_path)
    verify_source_files(manifest, manifest_path.parent)
    return {
        "kind": "source_dataset",
        "dataset_id": manifest["dataset_id"],
        "source_fingerprint": dataset_fingerprint(manifest),
        "synthetic": manifest["synthetic"],
        "data_classification": manifest["data_classification"],
        "simulator": manifest["simulator"],
        "adapter": manifest["adapter"]["id"],
        "source_file_count": len(manifest["source_files"]),
        "integrity": "source_hashes_verified",
    }
