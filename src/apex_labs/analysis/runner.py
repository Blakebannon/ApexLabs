"""Deterministic descriptive analysis runs over verified normalized datasets.

A run artifact binds the exact analysis definition, dataset fingerprint,
metric-definition content, and Labs code identity to its computed results.
It is a source of computed descriptive evidence, never a scientific claim:
status, scope, and review still belong to findings and validation artifacts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from apex_labs.analysis.descriptive import build_computation
from apex_labs.atomic import atomic_output_directory
from apex_labs.errors import AnalysisError, IntegrityError
from apex_labs.ingestion import inspect_dataset
from apex_labs.io import canonical_json_bytes, iter_json_lines, read_json, resolve_relative_file, write_json
from apex_labs.provenance import (
    apex_labs_code_identity,
    require_research_code_identity,
    sha256_bytes,
    sha256_file,
)
from apex_labs.schemas import (
    validate_analysis_definition,
    validate_analysis_run,
    validate_metric_definition,
    validate_normalized_manifest,
)
from apex_labs.schemas.versions import ANALYSIS_RUN, DESCRIPTIVE_METHOD_ID


def _canonical_sha(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def _run_hash(artifact: dict[str, Any]) -> str:
    return _canonical_sha({key: value for key, value in artifact.items() if key != "run_sha256"})


def _load_metric_bindings(metric_paths: Iterable[Path]) -> list[dict[str, Any]]:
    bindings: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for path in metric_paths:
        metric = validate_metric_definition(read_json(path))
        identity = (metric["metric_id"], metric["version"])
        if identity in seen:
            raise AnalysisError(f"Duplicate metric identity {identity[0]} version {identity[1]}")
        seen.add(identity)
        bindings.append(
            {
                "metric_id": metric["metric_id"],
                "version": metric["version"],
                "sha256": _canonical_sha(metric),
            }
        )
    return sorted(bindings, key=lambda item: (item["metric_id"], item["version"]))


def _dataset_reference(manifest: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    reference = {
        "dataset_id": manifest["dataset_id"],
        "fingerprint": manifest["dataset_fingerprint"],
        "normalized_manifest_sha256": sha256_file(manifest_path),
        "records_sha256": manifest["records_sha256"],
        "synthetic": manifest["synthetic"],
    }
    # The stratum travels into the run artifact, so a reader of the results never
    # has to go back to the dataset to discover that this was pilot evidence.
    if "scientific_eligibility" in manifest:
        reference["scientific_eligibility"] = manifest["scientific_eligibility"]
    return reference


def _verified_dataset(dataset_dir: Path) -> tuple[dict[str, Any], Path, Path]:
    dataset_dir = dataset_dir.resolve()
    manifest_path = dataset_dir / "manifest.json"
    manifest = validate_normalized_manifest(read_json(manifest_path))
    records_path = resolve_relative_file(dataset_dir, manifest["records_file"])
    return manifest, manifest_path, records_path


def _execute(definition: dict[str, Any], records_path: Path) -> tuple[list[dict[str, Any]], int]:
    computations = [build_computation(spec) for spec in definition["computations"]]
    records_validated = 0
    for record in iter_json_lines(records_path):
        records_validated += 1
        for computation in computations:
            computation.consume(record)
    return [computation.result() for computation in computations], records_validated


def run_analysis(
    definition_path: Path,
    dataset_dir: Path,
    output_dir: Path,
    *,
    run_id: str,
    created_at: str,
    metric_paths: Iterable[Path] = (),
    project_root: Path | None = None,
    code_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    definition = validate_analysis_definition(read_json(definition_path))
    metric_bindings = _load_metric_bindings(metric_paths)
    manifest, manifest_path, records_path = _verified_dataset(dataset_dir)
    identity = code_identity or apex_labs_code_identity(project_root)
    require_research_code_identity(identity, synthetic=manifest["synthetic"])
    inspect_dataset(manifest_path)
    results, records_validated = _execute(definition, records_path)
    if records_validated != sum(manifest["record_counts"].values()):
        raise IntegrityError("Normalized records changed between verification and analysis")
    artifact: dict[str, Any] = {
        "schema_version": ANALYSIS_RUN,
        "run_id": run_id,
        "created_at": created_at,
        "classification": "descriptive_summary_not_scientific_evidence",
        "synthetic": manifest["synthetic"],
        "method_id": DESCRIPTIVE_METHOD_ID,
        "run_sha256": "0" * 64,
        "definition": definition,
        "definition_sha256": _canonical_sha(definition),
        "dataset": _dataset_reference(manifest, manifest_path),
        "metric_definitions": metric_bindings,
        "code_identity": identity,
        "integrity": {
            "records_validated": records_validated,
            "record_counts_verified": True,
            "quality_flags_verified": True,
            "fingerprint_verified": True,
        },
        "results": results,
    }
    artifact["run_sha256"] = _run_hash(artifact)
    validate_analysis_run(artifact)
    with atomic_output_directory(output_dir, operation="analysis-run", error_type=AnalysisError) as staged:
        write_json(staged / "analysis-run.json", artifact)
    return artifact


def _resolve_run_path(run_path: Path) -> Path:
    return run_path / "analysis-run.json" if run_path.is_dir() else run_path


def verify_analysis_run(
    run_path: Path,
    dataset_dir: Path,
    *,
    project_root: Path | None = None,
) -> dict[str, Any]:
    artifact = validate_analysis_run(read_json(_resolve_run_path(run_path)))
    if artifact["run_sha256"] != _run_hash(artifact):
        raise IntegrityError("Analysis run artifact hash does not match its content")
    if artifact["definition_sha256"] != _canonical_sha(artifact["definition"]):
        raise IntegrityError("Analysis run definition hash does not match the embedded definition")
    manifest, manifest_path, records_path = _verified_dataset(dataset_dir)
    if _dataset_reference(manifest, manifest_path) != artifact["dataset"]:
        raise IntegrityError("Analysis run was produced from a different normalized dataset")
    inspect_dataset(manifest_path)
    results, records_validated = _execute(artifact["definition"], records_path)
    if records_validated != artifact["integrity"]["records_validated"]:
        raise IntegrityError("Analysis run record count is not reproducible from the bound dataset")
    if results != artifact["results"]:
        raise IntegrityError("Analysis run results are not reproducible from the bound dataset")
    current_identity = apex_labs_code_identity(project_root)
    return {
        "valid": True,
        "run_id": artifact["run_id"],
        "analysis_id": artifact["definition"]["analysis_id"],
        "dataset_id": artifact["dataset"]["dataset_id"],
        "results_reproduced": len(results),
        "records_validated": records_validated,
        "code_identity_match": (
            current_identity["code_and_schema_sha256"] == artifact["code_identity"]["code_and_schema_sha256"]
        ),
    }
