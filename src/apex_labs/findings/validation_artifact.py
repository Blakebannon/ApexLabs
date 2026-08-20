"""Cross-file scientific evidence/review binding for findings."""

from __future__ import annotations

from typing import Any

from apex_labs.errors import ContractValidationError
from apex_labs.io import canonical_json_bytes
from apex_labs.provenance import sha256_bytes
from apex_labs.schemas import validate_finding
from apex_labs.schemas.research_validation import validate_finding_validation


def finding_hash(finding: dict[str, Any]) -> str:
    return sha256_bytes(canonical_json_bytes(finding))


def validate_finding_with_artifact(
    finding_value: Any, artifact_value: Any
) -> tuple[dict[str, Any], dict[str, Any]]:
    finding = validate_finding(finding_value)
    artifact = validate_finding_validation(artifact_value)
    expected_ref = {
        "validation_id": artifact["validation_id"],
        "version": artifact["version"],
    }
    if finding["validation_artifact_reference"] != expected_ref:
        raise ContractValidationError("Finding validation-artifact reference does not match artifact")
    if artifact["finding_id"] != finding["finding_id"] or artifact["finding_version"] != finding["version"]:
        raise ContractValidationError("Validation artifact targets a different finding identity/version")
    if artifact["finding_sha256"] != finding_hash(finding):
        raise ContractValidationError("Validation artifact finding hash does not match finding content")
    if artifact["synthetic"] != finding["synthetic"]:
        raise ContractValidationError("Finding and validation artifact synthetic classifications differ")
    if artifact["datasets"] != finding["dataset_references"]:
        raise ContractValidationError("Validation artifact dataset evidence differs from finding references")
    expected_protocol = {
        "freeze_id": finding["protocol_reference"]["freeze_id"],
        "freeze_sha256": finding["protocol_reference"]["freeze_sha256"],
        "protocol_id": finding["protocol_reference"]["experiment_id"],
        "protocol_version": finding["protocol_reference"]["version"],
    }
    if artifact["frozen_protocol"] != expected_protocol:
        raise ContractValidationError("Validation artifact frozen protocol differs from finding")
    if artifact["preprocessing"] != finding["preprocessing"]:
        raise ContractValidationError("Validation artifact preprocessing differs from finding")
    if artifact["analysis"] != finding["analysis"]:
        raise ContractValidationError("Validation artifact analysis configuration differs from finding")
    artifact_code = artifact["analysis_code_identity"]
    finding_code = finding["analysis_code_identity"]
    for field in ("package_version", "git_commit", "git_state", "code_and_schema_sha256"):
        if artifact_code[field] != finding_code[field]:
            raise ContractValidationError(f"Validation artifact analysis code differs for {field}")
    evidence = artifact["computed_evidence"]
    if evidence["sample_counts"]["values"] != finding["sample_counts"]:
        raise ContractValidationError("Computed sample counts differ from finding")
    if evidence["sample_sufficiency"]["status"] != finding["sample_sufficiency"]["status"]:
        raise ContractValidationError("Sample-sufficiency disposition differs from finding")
    if evidence["effect_estimate"] != finding["effect_estimate"]:
        raise ContractValidationError("Computed effect estimate differs from finding")
    if evidence["uncertainty"] != finding["uncertainty"]:
        raise ContractValidationError("Computed uncertainty differs from finding")
    if evidence["comparability"]["status"] != finding["comparability_assessment"]["status"]:
        raise ContractValidationError("Comparability disposition differs from finding")
    if artifact["scope_assessment"]["scope"] != finding["scope"]:
        raise ContractValidationError("Scope assessment differs from finding")

    gates = artifact["gate_evaluations"]
    review_state = artifact["review"]["state"]
    status = finding["status"]
    if finding["scientific_review_state"] != (
        "approved" if review_state == "approved" else "rejected" if review_state == "rejected" else "pending" if review_state == "pending" else "unresolved"
    ):
        raise ContractValidationError("Finding scientific review state differs from validation artifact")
    if finding["product_review_state"] != artifact["product_review_state"]:
        raise ContractValidationError("Finding product review state differs from validation artifact")
    if status == "validated" and not (
        gates["scientific"] == "passed" and gates["reproducibility"] == "passed" and review_state == "approved"
    ):
        raise ContractValidationError("Validated finding lacks passed evidence/reproducibility and approved review")
    if status == "provisional" and not (
        gates["structural"] == "passed" and review_state == "approved"
    ):
        raise ContractValidationError("Provisional finding lacks reviewed structural evidence")
    if status == "rejected" and not (
        gates["scientific"] == "failed" and review_state == "approved"
    ):
        raise ContractValidationError("Rejected finding lacks reviewed contradictory/falsifying evidence")
    if gates["scientific"] == "unresolved" and status != "inconclusive":
        raise ContractValidationError("Unresolved scientific gate must remain inconclusive")
    return finding, artifact
