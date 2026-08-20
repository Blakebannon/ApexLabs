"""Deterministic synthetic mechanics verification (never racing research)."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
import zipfile

from apex_labs.errors import IntegrityError
from apex_labs.exports import generate_product_export
from apex_labs.findings import finding_hash, validate_finding_with_artifact
from apex_labs.ingestion import (
    ingest_apex_session_bundle,
    ingest_dataset,
    inspect_apex_session_bundle,
    inspect_dataset,
)
from apex_labs.io import canonical_json_bytes, read_json, write_json
from apex_labs.provenance import sha256_bytes, sha256_file


def _file_inventory(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _build_apex_session_fixture(source: Path, destination: Path) -> None:
    """Build the checked-in unzipped fixture without platform-dependent metadata."""
    order = [
        "README.md", "session-summary.md", "analysis-prompt.md", "data-dictionary.md",
        "findings.json", "laps.csv", "telemetry.csv", "manifest.json",
    ]
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_STORED) as archive:
        for name in order:
            info = zipfile.ZipInfo(name, (2000, 1, 1, 0, 0, 0))
            info.create_system = 0
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0
            archive.writestr(info, (source / name).read_bytes())


def verify_synthetic_demo(root: Path) -> dict[str, Any]:
    """Reproduce the checked-in synthetic software-path evidence twice."""
    root = root.resolve()
    dataset_path = root / "tests" / "fixtures" / "synthetic_demo" / "dataset.manifest.json"
    finding_path = root / "research" / "findings" / "inconclusive" / "synthetic-mechanics-demo.json"
    validation_path = root / "research" / "validations" / "synthetic-mechanics-demo-validation.json"
    definition_path = root / "product-exports" / "synthetic-demo-export-definition.json"
    with TemporaryDirectory(prefix="apex-labs-synthetic-verification-") as directory:
        temporary = Path(directory)
        first_normalized = temporary / "normalized-first"
        second_normalized = temporary / "normalized-second"
        first_manifest = ingest_dataset(dataset_path, first_normalized, project_root=root)
        second_manifest = ingest_dataset(dataset_path, second_normalized, project_root=root)
        if first_manifest["dataset_fingerprint"] != second_manifest["dataset_fingerprint"]:
            raise IntegrityError("Synthetic normalized fingerprints are not deterministic")
        if _file_inventory(first_normalized) != _file_inventory(second_normalized):
            raise IntegrityError("Synthetic normalized files are not byte deterministic")
        inspect_dataset(first_normalized / "manifest.json")

        template_finding, template_artifact = validate_finding_with_artifact(
            read_json(finding_path), read_json(validation_path)
        )
        expected_dataset_reference = {
            "dataset_id": first_manifest["dataset_id"],
            "fingerprint": first_manifest["dataset_fingerprint"],
            "normalized_manifest_sha256": sha256_file(first_normalized / "manifest.json"),
            "records_sha256": first_manifest["records_sha256"],
            "synthetic": True,
        }
        finding = dict(template_finding)
        finding["dataset_references"] = [expected_dataset_reference]
        finding["apex_labs_source_commit"] = first_manifest["code_identity"]["git_commit"]
        finding["analysis_code_identity"] = {
            key: first_manifest["code_identity"][key]
            for key in (
                "package_version",
                "git_commit",
                "git_state",
                "code_and_schema_sha256",
            )
        }
        preprocessing_configuration = {
            "normalized_dataset_fingerprint": first_manifest["dataset_fingerprint"],
            "normalized_manifest_sha256": expected_dataset_reference[
                "normalized_manifest_sha256"
            ],
        }
        finding["preprocessing"] = {
            "pipeline_id": first_manifest["preprocessing"]["pipeline_id"],
            "pipeline_version": first_manifest["preprocessing"]["pipeline_version"],
            "normalization_version": first_manifest["normalization_version"],
            "configuration": preprocessing_configuration,
            "configuration_sha256": sha256_bytes(
                canonical_json_bytes(preprocessing_configuration)
            ),
        }
        artifact = dict(template_artifact)
        artifact["datasets"] = finding["dataset_references"]
        artifact["preprocessing"] = finding["preprocessing"]
        artifact["analysis_code_identity"] = first_manifest["code_identity"]
        artifact["computed_evidence"] = dict(template_artifact["computed_evidence"])
        artifact["computed_evidence"]["sample_counts"] = dict(
            template_artifact["computed_evidence"]["sample_counts"]
        )
        artifact["computed_evidence"]["sample_counts"]["evidence_sha256"] = first_manifest[
            "records_sha256"
        ]
        artifact["finding_sha256"] = finding_hash(finding)
        validate_finding_with_artifact(finding, artifact)
        if finding["status"] != "inconclusive" or finding["recommended_product_action"] != "do_not_implement":
            raise IntegrityError("Synthetic mechanics finding has an impermissible scientific/product disposition")
        if artifact["gate_evaluations"]["scientific"] != "unresolved":
            raise IntegrityError("Synthetic mechanics validation must leave scientific truth unresolved")

        handoff_root = temporary / "handoff-root"
        dynamic_finding = handoff_root / "research" / "findings" / "inconclusive" / "synthetic-mechanics-demo.json"
        dynamic_validation = handoff_root / "research" / "validations" / "synthetic-mechanics-demo-validation.json"
        dynamic_metric = handoff_root / "research" / "metrics" / "demo-record-count.json"
        dynamic_definition = handoff_root / "product-exports" / "synthetic-demo-export-definition.json"
        write_json(dynamic_finding, finding)
        write_json(dynamic_validation, artifact)
        write_json(dynamic_metric, read_json(root / "research" / "metrics" / "demo-record-count.json"))
        definition = read_json(definition_path)
        definition["apex_labs_source_commit"] = first_manifest["code_identity"]["git_commit"]
        write_json(dynamic_definition, definition)

        first_export = temporary / "export-first"
        second_export = temporary / "export-second"
        generate_product_export(dynamic_definition, first_export, handoff_root)
        generate_product_export(dynamic_definition, second_export, handoff_root)
        if _file_inventory(first_export) != _file_inventory(second_export):
            raise IntegrityError("Synthetic product exports are not byte deterministic")

        apex_fixture = root / "tests" / "fixtures" / "apex_session_export_v1"
        first_bundle = temporary / "apex-first.zip"
        second_bundle = temporary / "apex-second.zip"
        _build_apex_session_fixture(apex_fixture / "bundle", first_bundle)
        _build_apex_session_fixture(apex_fixture / "bundle", second_bundle)
        if first_bundle.read_bytes() != second_bundle.read_bytes():
            raise IntegrityError("Synthetic Apex customer bundles are not byte deterministic")
        bundle_report = inspect_apex_session_bundle(first_bundle)
        first_apex_normalized = temporary / "apex-normalized-first"
        second_apex_normalized = temporary / "apex-normalized-second"
        first_apex_manifest = ingest_apex_session_bundle(
            first_bundle, first_apex_normalized, apex_fixture / "collection-record.json", project_root=root
        )
        second_apex_manifest = ingest_apex_session_bundle(
            second_bundle, second_apex_normalized, apex_fixture / "collection-record.json", project_root=root
        )
        if _file_inventory(first_apex_normalized) != _file_inventory(second_apex_normalized):
            raise IntegrityError("Synthetic Apex native normalization is not byte deterministic")
        inspect_dataset(first_apex_normalized / "manifest.json")
        if first_apex_manifest["research_eligibility"] != {
            "classification": "synthetic_demo",
            "scientific_promotion_eligible": False,
            "reason": "Synthetic mechanics cannot support scientific promotion.",
        }:
            raise IntegrityError("Synthetic Apex fixture acquired impermissible research eligibility")
    return {
        "ok": True,
        "classification": "synthetic_demo_only_not_racing_research",
        "dataset_id": first_manifest["dataset_id"],
        "dataset_fingerprint": first_manifest["dataset_fingerprint"],
        "record_counts": first_manifest["record_counts"],
        "finding_status": finding["status"],
        "scientific_gate": artifact["gate_evaluations"]["scientific"],
        "product_action": finding["recommended_product_action"],
        "deterministic_normalization": True,
        "deterministic_export": True,
        "native_apex_session_adapter": {
            "source_schema_version": bundle_report["source_schema_version"],
            "record_counts": first_apex_manifest["record_counts"],
            "distance_binned_not_raw_frames": True,
            "scientific_promotion_eligible": False,
            "deterministic_normalization": True,
        },
    }
