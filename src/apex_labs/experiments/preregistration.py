"""Immutable protocol snapshots and append-only amendments."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from apex_labs.atomic import atomic_output_directory
from apex_labs.errors import ContractValidationError
from apex_labs.io import canonical_json_bytes, read_json, write_json
from apex_labs.provenance import apex_labs_code_identity, require_research_code_identity, sha256_bytes
from apex_labs.schemas import validate_experiment
from apex_labs.schemas.research_validation import (
    validate_protocol_amendment,
    validate_protocol_freeze,
)
from apex_labs.schemas.versions import PROTOCOL_AMENDMENT, PROTOCOL_FREEZE


def _without_hash(value: dict[str, Any], field: str) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != field}


def protocol_hash(protocol: dict[str, Any]) -> str:
    return sha256_bytes(canonical_json_bytes(protocol))


def schedule_hash(schedule: list[Any]) -> str:
    return sha256_bytes(canonical_json_bytes(schedule))


def freeze_hash(snapshot: dict[str, Any]) -> str:
    return sha256_bytes(canonical_json_bytes(_without_hash(snapshot, "freeze_sha256")))


def verify_protocol_freeze(snapshot: dict[str, Any]) -> dict[str, Any]:
    snapshot = validate_protocol_freeze(snapshot)
    if snapshot["protocol_sha256"] != protocol_hash(snapshot["protocol"]):
        raise ContractValidationError("Frozen protocol canonical protocol hash does not match snapshot")
    if snapshot["randomization"]["schedule_sha256"] != schedule_hash(snapshot["randomization"]["schedule"]):
        raise ContractValidationError("Frozen protocol schedule hash does not match schedule")
    if snapshot["freeze_sha256"] != freeze_hash(snapshot):
        raise ContractValidationError("Frozen protocol artifact hash does not match content")
    return snapshot


def freeze_protocol(
    protocol_path: Path,
    registry_dir: Path,
    *,
    frozen_at: str,
    strategy: str,
    method: str,
    seed: int | None,
    schedule_id: str,
    schedule: list[Any],
    project_root: Path | None = None,
    code_identity: dict[str, Any] | None = None,
) -> Path:
    protocol = validate_experiment(read_json(protocol_path))
    if protocol["status"] != "preregistered":
        raise ContractValidationError("Only a preregistered protocol can be frozen")
    identity = code_identity or apex_labs_code_identity(project_root)
    require_research_code_identity(identity, synthetic=protocol["synthetic"])
    if not protocol["synthetic"] and protocol["apex_labs_source_commit"] != identity["git_commit"]:
        raise ContractValidationError("Protocol source commit must match the clean Apex Labs commit")
    target = registry_dir / f"{protocol['experiment_id']}-v{protocol['version']}"
    snapshot: dict[str, Any] = {
        "schema_version": PROTOCOL_FREEZE,
        "freeze_id": f"{protocol['experiment_id']}.freeze",
        "freeze_sha256": "0" * 64,
        "protocol_id": protocol["experiment_id"],
        "protocol_version": protocol["version"],
        "protocol_sha256": protocol_hash(protocol),
        "source_commit": protocol["apex_labs_source_commit"],
        "code_identity": identity,
        "frozen_at": frozen_at,
        "synthetic": protocol["synthetic"],
        "protocol": protocol,
        "randomization": {
            "strategy": strategy,
            "method": method,
            "seed": seed,
            "schedule_id": schedule_id,
            "schedule": schedule,
            "schedule_sha256": schedule_hash(schedule),
        },
        "amendment_history": [],
    }
    snapshot["freeze_sha256"] = freeze_hash(snapshot)
    verify_protocol_freeze(snapshot)
    with atomic_output_directory(target, operation="protocol-freeze", error_type=ContractValidationError) as staged:
        write_json(staged / "snapshot.json", snapshot)
    return target / "snapshot.json"


def amendment_hash(amendment: dict[str, Any]) -> str:
    return sha256_bytes(canonical_json_bytes(_without_hash(amendment, "amendment_sha256")))


def verify_protocol_amendment(amendment: dict[str, Any]) -> dict[str, Any]:
    amendment = validate_protocol_amendment(amendment)
    if amendment["amendment_sha256"] != amendment_hash(amendment):
        raise ContractValidationError("Protocol amendment hash does not match content")
    return amendment


def create_protocol_amendment(
    snapshot_path: Path,
    registry_dir: Path,
    *,
    amendment_id: str,
    version: str,
    created_at: str,
    source_commit: str,
    reason: str,
    changes: list[dict[str, Any]],
    impact_assessment: str,
    requires_new_protocol_version: bool,
    prior_amendments: list[dict[str, str]] | None = None,
) -> Path:
    snapshot = verify_protocol_freeze(read_json(snapshot_path))
    target = registry_dir / f"{amendment_id}-v{version}"
    amendment: dict[str, Any] = {
        "schema_version": PROTOCOL_AMENDMENT,
        "amendment_id": amendment_id,
        "version": version,
        "amendment_sha256": "0" * 64,
        "frozen_protocol": {
            "freeze_id": snapshot["freeze_id"],
            "freeze_sha256": snapshot["freeze_sha256"],
            "protocol_id": snapshot["protocol_id"],
            "protocol_version": snapshot["protocol_version"],
        },
        "created_at": created_at,
        "source_commit": source_commit,
        "reason": reason,
        "changes": changes,
        "impact_assessment": impact_assessment,
        "requires_new_protocol_version": requires_new_protocol_version,
        "prior_amendments": prior_amendments or [],
        "synthetic": snapshot["synthetic"],
    }
    amendment["amendment_sha256"] = amendment_hash(amendment)
    verify_protocol_amendment(amendment)
    with atomic_output_directory(target, operation="protocol-amendment", error_type=ContractValidationError) as staged:
        write_json(staged / "amendment.json", amendment)
    return target / "amendment.json"
