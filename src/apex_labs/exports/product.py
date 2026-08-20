"""Generate and verify a deterministic Apex Sim Coach handoff package."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from apex_labs import __version__
from apex_labs.atomic import atomic_output_directory
from apex_labs.errors import ExportError, IntegrityError
from apex_labs.findings import validate_finding_with_artifact
from apex_labs.io import canonical_json_bytes, read_json, resolve_relative_file, write_json
from apex_labs.provenance import sha256_bytes, sha256_file
from apex_labs.schemas import (
    validate_algorithm_recommendation,
    validate_export_definition,
    validate_finding,
    validate_finding_validation,
    validate_metric_definition,
    validate_product_export_manifest,
    validate_product_provenance_summary,
)
from apex_labs.schemas.versions import PRODUCT_EXPORT_MANIFEST, PRODUCT_PROVENANCE_SUMMARY


def _safe_name(identifier: str, version: str) -> str:
    return f"{identifier}-v{version.replace('.', '_')}.json"


def _load_payloads(
    root: Path,
    paths: list[str],
    validator: Callable[[Any], dict[str, Any]],
    id_field: str,
    folder: str,
) -> list[tuple[str, dict[str, Any], bytes]]:
    payloads: list[tuple[str, dict[str, Any], bytes]] = []
    seen: set[tuple[str, str]] = set()
    for declared_path in paths:
        source_path = resolve_relative_file(root, declared_path)
        value = validator(read_json(source_path))
        identity = (value[id_field], value["version"])
        if identity in seen:
            raise ExportError(f"Duplicate {folder} identity {identity[0]} version {identity[1]}")
        seen.add(identity)
        export_path = f"{folder}/{_safe_name(*identity)}"
        content = canonical_json_bytes(value)
        payloads.append((export_path, value, content))
    return sorted(payloads, key=lambda item: item[0])


def _readme(definition: dict[str, Any], findings: list[tuple[str, dict[str, Any], bytes]]) -> bytes:
    rows = [
        "# Apex Labs product findings export",
        "",
        f"Export: `{definition['export_id']}`",
        "",
        definition["summary"],
        "",
        "This is an evidence handoff, not executable production configuration. It must not automatically modify Apex Sim Coach. Human and production-engineering review is required before implementation.",
        "Package verification establishes file integrity and internal consistency only. It does not establish authorship, scientific correctness, or production approval.",
        "",
        "## Included findings",
        "",
        "| Finding | Status | Scope | Global consideration | Product action |",
        "|---|---|---|---|---|",
    ]
    for _, finding, _ in findings:
        global_text = "yes" if finding["safe_for_global_consideration"] else "no"
        rows.append(
            f"| `{finding['finding_id']}` v{finding['version']} | {finding['status']} | {finding['scope']} | {global_text} | {finding['recommended_product_action']} |"
        )
    rows.extend(
        [
            "",
            "## Review sequence",
            "",
            "1. Verify every file against `manifest.json`.",
            "2. Read scope, uncertainty, limitations, confounders, and falsification attempts.",
            "3. Reject global implementation unless the manifest explicitly marks the finding safe for global consideration.",
            "4. Treat personalized findings as personalized only.",
            "5. Translate accepted recommendations into production design and tests in the separate production repository.",
            "",
        ]
    )
    return "\n".join(rows).encode("utf-8")


def _provenance_summary(
    definition: dict[str, Any], findings: list[tuple[str, dict[str, Any], bytes]]
) -> dict[str, Any]:
    summary = {
        "schema_version": PRODUCT_PROVENANCE_SUMMARY,
        "export_id": definition["export_id"],
        "apex_labs_version": definition["apex_labs_version"],
        "apex_labs_source_commit": definition["apex_labs_source_commit"],
        "finding_provenance": [
            {
                "finding_id": finding["finding_id"],
                "finding_version": finding["version"],
                "dataset_references": finding["dataset_references"],
                "protocol_reference": finding["protocol_reference"],
                "preprocessing": finding["preprocessing"],
                "analysis": finding["analysis"],
                "validation_artifact_reference": finding["validation_artifact_reference"],
                "scientific_review_state": finding["scientific_review_state"],
                "product_review_state": finding["product_review_state"],
            }
            for _, finding, _ in findings
        ],
    }
    validate_product_provenance_summary(summary)
    return summary


def generate_product_export(definition_path: Path, output_dir: Path, root: Path) -> dict[str, Any]:
    definition = validate_export_definition(read_json(definition_path))
    if definition["apex_labs_version"] != __version__:
        raise ExportError(
            f"Export declares Apex Labs {definition['apex_labs_version']}, but running package is {__version__}"
        )
    root = root.resolve()
    findings = _load_payloads(root, definition["finding_paths"], validate_finding, "finding_id", "findings")
    metrics = _load_payloads(root, definition["metric_paths"], validate_metric_definition, "metric_id", "metrics")
    algorithms = _load_payloads(root, definition["algorithm_paths"], validate_algorithm_recommendation, "algorithm_id", "algorithms")
    validations = _load_payloads(
        root,
        definition["validation_paths"],
        validate_finding_validation,
        "validation_id",
        "validations",
    )

    validations_by_identity = {
        (value["validation_id"], value["version"]): (path, value, content)
        for path, value, content in validations
    }
    used_validations: set[tuple[str, str]] = set()
    finding_validations: dict[str, tuple[str, dict[str, Any], bytes]] = {}
    for _, finding, _ in findings:
        reference = finding["validation_artifact_reference"]
        if reference is None:
            raise ExportError(
                f"Finding {finding['finding_id']} has no independent validation artifact"
            )
        identity = (reference["validation_id"], reference["version"])
        validation_payload = validations_by_identity.get(identity)
        if validation_payload is None:
            raise ExportError(
                f"Finding {finding['finding_id']} references validation artifact absent from export: {identity}"
            )
        validate_finding_with_artifact(finding, validation_payload[1])
        used_validations.add(identity)
        finding_validations[finding["finding_id"]] = validation_payload
    if used_validations != set(validations_by_identity):
        raise ExportError("Export definition contains unreferenced validation artifacts")

    findings_by_id = {value["finding_id"]: value for _, value, _ in findings}
    finding_ids = set(findings_by_id)
    for _, algorithm, _ in algorithms:
        missing = set(algorithm["finding_references"]) - finding_ids
        if missing:
            raise ExportError(
                f"Algorithm {algorithm['algorithm_id']} references findings absent from export: {sorted(missing)}"
            )
        references = [findings_by_id[finding_id] for finding_id in algorithm["finding_references"]]
        if algorithm["recommendation_status"] == "recommended" and any(
            finding["status"] != "validated" for finding in references
        ):
            raise ExportError(
                f"Recommended algorithm {algorithm['algorithm_id']} requires validated supporting findings"
            )
        if algorithm["safe_for_global_consideration"] and any(
            not finding["safe_for_global_consideration"] for finding in references
        ):
            raise ExportError(
                f"Globally safe algorithm {algorithm['algorithm_id']} requires globally safe supporting findings"
            )
    for _, finding, _ in findings:
        if finding["apex_labs_source_commit"] != definition["apex_labs_source_commit"]:
            raise ExportError(f"Finding {finding['finding_id']} source commit differs from export definition")

    readme = _readme(definition, findings)
    provenance = canonical_json_bytes(_provenance_summary(definition, findings))
    payloads: list[tuple[str, bytes, str, str]] = []
    payloads.extend((path, content, "application/json", "finding") for path, _, content in findings)
    payloads.extend((path, content, "application/json", "metric") for path, _, content in metrics)
    payloads.extend((path, content, "application/json", "algorithm") for path, _, content in algorithms)
    payloads.extend((path, content, "application/json", "validation") for path, _, content in validations)
    payloads.append(("provenance/summary.json", provenance, "application/json", "provenance"))
    payloads.append(("README.md", readme, "text/markdown", "summary"))
    payloads.sort(key=lambda item: item[0])

    manifest = {
        "schema_version": PRODUCT_EXPORT_MANIFEST,
        "export_id": definition["export_id"],
        "created_at": definition["created_at"],
        "apex_labs_version": definition["apex_labs_version"],
        "apex_labs_source_commit": definition["apex_labs_source_commit"],
        "summary": definition["summary"],
        "review_gate": "human_and_production_engineering_review_required",
        "findings": [
            {
                "finding_id": finding["finding_id"],
                "version": finding["version"],
                "status": finding["status"],
                "scope": finding["scope"],
                "evidence_classification": finding["evidence_classification"],
                "synthetic": finding["synthetic"],
                "safe_for_global_consideration": finding["safe_for_global_consideration"],
                "recommended_product_action": finding["recommended_product_action"],
                "scientific_review_state": finding["scientific_review_state"],
                "product_review_state": finding["product_review_state"],
                "validation_path": finding_validations[finding["finding_id"]][0],
                "validation_sha256": sha256_bytes(
                    finding_validations[finding["finding_id"]][2]
                ),
                "implementation_caveats": sorted(
                    set(finding["limitations"] + finding["possible_confounders"] + finding["required_future_validation"])
                ),
                "path": path,
                "sha256": sha256_bytes(content),
            }
            for path, finding, content in findings
        ],
        "files": [
            {"path": path, "sha256": sha256_bytes(content), "media_type": media_type, "role": role}
            for path, content, media_type, role in payloads
        ],
    }
    validate_product_export_manifest(manifest)
    with atomic_output_directory(
        output_dir, operation="product-export", error_type=ExportError
    ) as staging_dir:
        for relative_path, content, _, _ in payloads:
            destination = staging_dir / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        write_json(staging_dir / "manifest.json", manifest)
        verify_product_export(staging_dir)
    return manifest


def verify_product_export(export_dir: Path) -> dict[str, Any]:
    manifest_path = export_dir / "manifest.json"
    manifest = validate_product_export_manifest(read_json(manifest_path))
    declared_paths = {item["path"] for item in manifest["files"]}
    if len(declared_paths) != len(manifest["files"]):
        raise IntegrityError("Product export manifest contains duplicate file paths")
    actual_paths = {
        path.relative_to(export_dir).as_posix()
        for path in export_dir.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    if actual_paths != declared_paths:
        raise IntegrityError(
            f"Product export files differ from manifest: missing={sorted(declared_paths - actual_paths)}, undeclared={sorted(actual_paths - declared_paths)}"
        )
    file_entries = {item["path"]: item for item in manifest["files"]}
    for relative_path in sorted(declared_paths):
        path = resolve_relative_file(export_dir, relative_path)
        actual_hash = sha256_file(path)
        if actual_hash != file_entries[relative_path]["sha256"]:
            raise IntegrityError(f"Product export hash mismatch for {relative_path}")
    finding_entries = {item["path"]: item for item in manifest["findings"]}
    if len(finding_entries) != len(manifest["findings"]):
        raise IntegrityError("Product export manifest contains duplicate finding paths")
    finding_payloads = {
        path for path, item in file_entries.items() if item["role"] == "finding"
    }
    if finding_payloads != set(finding_entries):
        raise IntegrityError("Finding summary inventory differs from finding payload inventory")
    validation_payloads = {
        path for path, item in file_entries.items() if item["role"] == "validation"
    }
    referenced_validations: set[str] = set()
    for relative_path, entry in finding_entries.items():
        if relative_path not in file_entries or file_entries[relative_path]["role"] != "finding":
            raise IntegrityError(f"Finding {relative_path} is absent from the files inventory")
        if entry["sha256"] != file_entries[relative_path]["sha256"]:
            raise IntegrityError(f"Finding hash inventories disagree for {relative_path}")
        finding = validate_finding(read_json(export_dir / relative_path))
        for field in ("finding_id", "version", "status", "scope", "evidence_classification", "synthetic", "safe_for_global_consideration", "recommended_product_action", "scientific_review_state", "product_review_state"):
            if finding[field] != entry[field]:
                raise IntegrityError(f"Finding manifest metadata mismatch for {relative_path}: {field}")
        validation_path = entry["validation_path"]
        if validation_path not in file_entries or file_entries[validation_path]["role"] != "validation":
            raise IntegrityError(f"Finding validation payload is absent for {relative_path}")
        if entry["validation_sha256"] != file_entries[validation_path]["sha256"]:
            raise IntegrityError(f"Finding validation hash inventories disagree for {relative_path}")
        validation = validate_finding_validation(read_json(export_dir / validation_path))
        validate_finding_with_artifact(finding, validation)
        referenced_validations.add(validation_path)
        expected_caveats = sorted(
            set(finding["limitations"] + finding["possible_confounders"] + finding["required_future_validation"])
        )
        if entry["implementation_caveats"] != expected_caveats:
            raise IntegrityError(f"Finding caveats mismatch for {relative_path}")
        if finding["apex_labs_source_commit"] != manifest["apex_labs_source_commit"]:
            raise IntegrityError(f"Finding source commit mismatch for {relative_path}")
    if validation_payloads != referenced_validations:
        raise IntegrityError("Validation artifact inventory differs from finding references")
    for relative_path, file_entry in file_entries.items():
        if file_entry["role"] == "metric":
            validate_metric_definition(read_json(export_dir / relative_path))
        elif file_entry["role"] == "algorithm":
            validate_algorithm_recommendation(read_json(export_dir / relative_path))
    provenance_paths = [path for path, item in file_entries.items() if item["role"] == "provenance"]
    if provenance_paths != ["provenance/summary.json"]:
        raise IntegrityError("Product export requires exactly provenance/summary.json")
    actual_provenance = validate_product_provenance_summary(
        read_json(export_dir / "provenance" / "summary.json")
    )
    finding_payload_values = [
        (path, validate_finding(read_json(export_dir / path)), b"")
        for path in sorted(finding_entries)
    ]
    expected_provenance = _provenance_summary(
        {
            "export_id": manifest["export_id"],
            "apex_labs_version": manifest["apex_labs_version"],
            "apex_labs_source_commit": manifest["apex_labs_source_commit"],
        },
        finding_payload_values,
    )
    if actual_provenance != expected_provenance:
        raise IntegrityError("Product provenance summary differs from finding payloads")
    return manifest
