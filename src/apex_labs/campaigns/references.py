"""Regenerate hash-bound synthetic inference references from a clean engine commit.

The authored protocols, freeze schedules, evidence definitions, and analysis
definitions remain the scientific inputs. This workflow changes only derived
protocol snapshots and the exact hashes downstream definitions must bind. It
writes a complete mirror into a new atomic directory for artifact-only review.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from apex_labs.atomic import atomic_output_directory
from apex_labs.errors import ContractValidationError
from apex_labs.experiments.preregistration import (
    freeze_hash,
    protocol_hash,
    schedule_hash,
    verify_protocol_freeze,
)
from apex_labs.io import canonical_json_bytes, read_json, resolve_relative_file, write_json
from apex_labs.provenance import apex_labs_code_identity, sha256_bytes
from apex_labs.schemas import (
    validate_evidence_set_definition,
    validate_experiment,
    validate_inferential_analysis_definition,
)
from apex_labs.schemas.versions import PROTOCOL_FREEZE

REFERENCE_CONFIG = Path("research/campaigns/reference-freezes.json")


def _canonical_sha(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def _reference_config(root: Path) -> list[dict[str, Any]]:
    value = read_json(root / REFERENCE_CONFIG)
    if set(value) != {"classification", "description", "references", "synthetic"}:
        raise ContractValidationError("Synthetic reference configuration has unexpected fields")
    if value["classification"] != "synthetic_demo_only_not_racing_research":
        raise ContractValidationError("Synthetic reference configuration must remain demo-only")
    if value["synthetic"] is not True or not isinstance(value["description"], str):
        raise ContractValidationError("Synthetic reference configuration is not explicitly synthetic")
    references = value["references"]
    if not isinstance(references, list) or not references:
        raise ContractValidationError("Synthetic reference configuration requires freeze entries")
    expected = {
        "protocol", "frozen_at", "strategy", "method", "seed", "schedule_id", "schedule"
    }
    seen: set[str] = set()
    for index, item in enumerate(references):
        if not isinstance(item, dict) or set(item) != expected:
            raise ContractValidationError(
                f"Synthetic reference entry {index} does not have the exact required fields"
            )
        if item["protocol"] in seen:
            raise ContractValidationError("Synthetic reference protocols must be unique")
        seen.add(item["protocol"])
        if item["strategy"] not in {"randomized", "counterbalanced", "fixed", "not_applicable"}:
            raise ContractValidationError(f"Synthetic reference entry {index} has invalid strategy")
        if not isinstance(item["schedule"], list):
            raise ContractValidationError(f"Synthetic reference entry {index} schedule must be a list")
    return references


def _snapshot(
    protocol: dict[str, Any], reference: dict[str, Any], identity: dict[str, Any]
) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "schema_version": PROTOCOL_FREEZE,
        "freeze_id": f"{protocol['experiment_id']}.freeze",
        "freeze_sha256": "0" * 64,
        "protocol_id": protocol["experiment_id"],
        "protocol_version": protocol["version"],
        "protocol_sha256": protocol_hash(protocol),
        "source_commit": protocol["apex_labs_source_commit"],
        "code_identity": identity,
        "frozen_at": reference["frozen_at"],
        "synthetic": True,
        "protocol": protocol,
        "randomization": {
            "strategy": reference["strategy"],
            "method": reference["method"],
            "seed": reference["seed"],
            "schedule_id": reference["schedule_id"],
            "schedule": reference["schedule"],
            "schedule_sha256": schedule_hash(reference["schedule"]),
        },
        "amendment_history": [],
    }
    snapshot["freeze_sha256"] = freeze_hash(snapshot)
    return verify_protocol_freeze(snapshot)


def regenerate_reference_artifacts(
    root: Path,
    output_dir: Path,
    *,
    code_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write the complete regenerated reference set into a new output tree."""
    root = root.resolve()
    identity = code_identity or apex_labs_code_identity(root)
    if identity["git_state"] != "clean" or identity["git_commit"] == "UNCOMMITTED":
        raise ContractValidationError(
            "Synthetic references may only be regenerated from a clean committed code identity"
        )

    snapshots: dict[str, dict[str, Any]] = {}
    for reference in _reference_config(root):
        protocol_path = resolve_relative_file(root, reference["protocol"])
        protocol = validate_experiment(read_json(protocol_path))
        if protocol["synthetic"] is not True:
            raise ContractValidationError("The reference workflow accepts synthetic protocols only")
        snapshots[protocol["experiment_id"]] = _snapshot(protocol, reference, identity)

    evidence_values: dict[str, dict[str, Any]] = {}
    for path in sorted((root / "research/evidence-sets").glob("*.json")):
        definition = read_json(path)
        experiment_id = definition.get("protocol", {}).get("experiment_id")
        if experiment_id not in snapshots:
            continue
        snapshot = snapshots[experiment_id]
        updated = {
            **definition,
            "protocol": {
                **definition["protocol"],
                "freeze_id": snapshot["freeze_id"],
                "freeze_sha256": snapshot["freeze_sha256"],
            },
        }
        evidence_values[updated["evidence_set_id"]] = validate_evidence_set_definition(updated)

    analysis_values: dict[Path, dict[str, Any]] = {}
    for path in sorted((root / "research/analyses").glob("*.json")):
        definition = read_json(path)
        evidence_id = definition.get("evidence_set", {}).get("evidence_set_id")
        experiment_id = definition.get("protocol", {}).get("experiment_id")
        if evidence_id not in evidence_values or experiment_id not in snapshots:
            continue
        snapshot = snapshots[experiment_id]
        updated = {
            **definition,
            "evidence_set": {
                **definition["evidence_set"],
                "definition_sha256": _canonical_sha(evidence_values[evidence_id]),
            },
            "protocol": {
                **definition["protocol"],
                "freeze_id": snapshot["freeze_id"],
                "freeze_sha256": snapshot["freeze_sha256"],
            },
        }
        analysis_values[path.relative_to(root)] = validate_inferential_analysis_definition(updated)

    artifacts: list[tuple[Path, dict[str, Any]]] = []
    for experiment_id, snapshot in sorted(snapshots.items()):
        artifacts.append(
            (Path("research/campaigns/frozen") / f"{experiment_id}.freeze.json", snapshot)
        )
    for evidence_id, definition in sorted(evidence_values.items()):
        artifacts.append((Path("research/evidence-sets") / f"{evidence_id}.json", definition))
    artifacts.extend(sorted(analysis_values.items(), key=lambda item: item[0].as_posix()))

    with atomic_output_directory(
        output_dir,
        operation="synthetic-reference-regeneration",
        error_type=ContractValidationError,
    ) as staged:
        for relative, value in artifacts:
            destination = staged / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            write_json(destination, value)

    return {
        "valid": True,
        "classification": "synthetic_demo_only_not_racing_research",
        "code_commit": identity["git_commit"],
        "artifacts": [relative.as_posix() for relative, _ in artifacts],
        "count": len(artifacts),
    }
