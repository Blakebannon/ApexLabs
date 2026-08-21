"""Explicit comparability keys and the guard against combining incompatible evidence.

A protocol may deliberately permit a field to vary, but the permission must be
declared in advance and the field must survive as a covariate or a stated
limitation. Nothing becomes comparable here by being convenient.
"""

from __future__ import annotations

from typing import Any

from apex_labs.errors import EvidenceError
from apex_labs.schemas.science_vocabulary import (
    GUARDED_COMPARABILITY_FIELDS,
    PROTECTED_IDENTITY_FIELDS,
)

# Human-readable reasons the guard exists, used in refusal messages.
_FIELD_SUBJECT = {
    "participant": "drivers",
    "simulator": "simulators",
    "car": "cars",
    "track": "tracks",
    "layout": "track layouts",
    "protocol_version": "protocol versions",
    "condition_semantics": "experimental conditions",
    "coaching_state": "coaching states",
    "configuration_identity": "configuration/setup states",
    "segment_definition": "segment definitions",
    "metric_definition": "metric definitions",
    "normalization_contract": "sampling/normalization contracts",
    "product_build": "product builds",
}

_IDENTITY_SOURCE_FILES = {
    "configuration_identity": "configuration-setup.json",
    "product_build": "product-build.json",
}


def source_identity(manifest: dict[str, Any], field: str) -> str | None:
    """Return a fingerprint-bound comparison identity when the source supplies one.

    Normalized v1 does not invent setup or product-build concepts.  It does,
    however, preserve each source file's path, role, and SHA-256.  An exact
    identity declaration file is therefore verifiable without interpreting its
    contents or expanding the normalized record vocabulary.  Absence remains
    unavailable, never a match.
    """
    filename = _IDENTITY_SOURCE_FILES[field]
    matches = [item for item in manifest["source_files"] if item["path"] == filename]
    if len(matches) > 1:
        raise EvidenceError(
            f"Dataset {manifest['dataset_id']} carries duplicate {filename} identity sources"
        )
    return None if not matches else f"sha256:{matches[0]['sha256']}"


def identity_variation_limits(
    definition: dict[str, Any], protocol: dict[str, Any]
) -> list[str]:
    """Bind every protected variation exception to a structured protocol plan."""
    plans = {item["plan_id"]: item for item in protocol.get("identity_variation_plans", [])}
    limits: list[str] = []
    for entry in definition["comparability"]["permitted_variation"]:
        field = entry["field"]
        if field not in PROTECTED_IDENTITY_FIELDS:
            continue
        plan_id = entry.get("protocol_variation_plan_id")
        plan = plans.get(plan_id)
        if plan is None:
            raise EvidenceError(
                f"Protected identity variation for {field} is not bound to a plan in the frozen protocol"
            )
        if plan["field"] != field:
            raise EvidenceError(
                f"Protocol variation plan {plan_id!r} applies to {plan['field']}, not {field}"
            )
        limits.append(plan["interpretation_ceiling"])
    return limits


def comparability_key(
    *,
    session: dict[str, Any],
    manifest: dict[str, Any],
    condition_id: str,
    coaching_state: str,
    segment: dict[str, Any],
    unit_metric: dict[str, Any],
) -> dict[str, str | None]:
    """The complete comparability key for one contributing dataset.

    Configuration/setup identity and product build are read only from exact,
    fingerprint-bound source identity declarations. They are otherwise reported
    as unavailable rather than silently treated as matching.
    """
    adapter = manifest["adapter"]
    snapshot = manifest["collection_context"]["protocol_snapshot"]
    return {
        "participant": session["driver_id"],
        "simulator": session["simulator"],
        "car": session["car"],
        "track": session["track"],
        "layout": session["layout"],
        "protocol_version": None if snapshot is None else snapshot["experiment_version"],
        "condition_semantics": condition_id,
        "coaching_state": coaching_state,
        "configuration_identity": source_identity(manifest, "configuration_identity"),
        "segment_definition": f"{segment['segment_definition_id']}@{segment['version']}",
        "metric_definition": f"{unit_metric['metric_id']}@{unit_metric['version']}",
        "normalization_contract": (
            f"{manifest['normalization_version']}/{adapter['id']}@{adapter['version']}"
        ),
        "product_build": source_identity(manifest, "product_build"),
    }


def assess(
    definition: dict[str, Any],
    keys: list[dict[str, str | None]],
    arms_present: set[str],
) -> dict[str, Any]:
    """Evaluate declared comparability across the contributing datasets.

    Variation in a must-match field is refused outright: that evidence may not
    be combined at all. Variation that the protocol permitted, and fields the
    corpus cannot verify, are preserved as covariates, limitations, and
    violations instead of being quietly dropped.
    """
    if not keys:
        raise EvidenceError("An evidence set requires at least one contributing dataset")
    must_match = list(definition["comparability"]["must_match"])
    permitted = {item["field"]: item for item in definition["comparability"]["permitted_variation"]}
    declared = set(must_match) | set(permitted)
    undeclared = GUARDED_COMPARABILITY_FIELDS - declared
    if undeclared:
        raise EvidenceError(
            f"Comparability fields {sorted(undeclared)} are neither required to match nor explicitly permitted to vary"
        )

    observed: dict[str, list[str]] = {}
    for field in sorted(declared):
        values = sorted({"<unavailable>" if key[field] is None else str(key[field]) for key in keys})
        observed[field] = values

    violations: list[str] = []
    limitations: list[str] = []
    identity_limitations: list[str] = []
    covariate_fields: list[str] = []
    for field in sorted(must_match):
        values = observed[field]
        real = [value for value in values if value != "<unavailable>"]
        if len(real) > 1:
            raise EvidenceError(
                f"Evidence may not be combined across incompatible {_FIELD_SUBJECT[field]}: "
                f"{field} takes values {real} but the protocol requires it to match"
            )
        if not real:
            detail = (
                f"{field} is unavailable in every contributing dataset and could not be verified as matching"
            )
            violations.append(detail)
            limitations.append(detail)
            if field in PROTECTED_IDENTITY_FIELDS:
                identity_limitations.append(detail)
        elif "<unavailable>" in values:
            detail = (
                f"{field} is unavailable in some contributing datasets and could not be verified as matching"
            )
            violations.append(detail)
            limitations.append(detail)
            if field in PROTECTED_IDENTITY_FIELDS:
                identity_limitations.append(detail)

    expected_factor_variation = {"condition_semantics"}
    coaching_states = {arm["coaching_state"] for arm in definition["factor"]["arms"]}
    if len(coaching_states) > 1:
        expected_factor_variation.add("coaching_state")
    for field in sorted(permitted):
        entry = permitted[field]
        values = observed[field]
        varied = len([value for value in values if value != "<unavailable>"]) > 1
        if entry["retained_as"] == "covariate":
            covariate_fields.append(field)
        if field in PROTECTED_IDENTITY_FIELDS:
            limitations.append(
                f"{field} follows frozen protocol variation plan {entry['protocol_variation_plan_id']}; "
                f"observed values {values} are retained as a {entry['retained_as']}"
            )
            identity_limitations.append(limitations[-1])
        elif varied and field not in expected_factor_variation:
            limitations.append(
                f"{field} was permitted to vary ({entry['justification']}); observed values {values} are retained as a {entry['retained_as']}"
            )
        elif "<unavailable>" in values:
            limitations.append(
                f"{field} is unavailable in this corpus; it was declared permitted variation retained as a {entry['retained_as']}"
            )

    if len(arms_present) < 2:
        violations.append(
            f"only the {sorted(arms_present)} arm is represented; the declared contrast is not present in this evidence"
        )
        status = "inadequate"
    elif violations or limitations:
        status = "limited"
    else:
        status = "adequate"

    return {
        "status": status,
        "must_match_fields": sorted(must_match),
        "observed_values": observed,
        "permitted_variation": [permitted[field] for field in sorted(permitted)],
        "violations": violations,
        "limitations": limitations,
        "identity_limitations": identity_limitations,
        "covariate_fields": sorted(covariate_fields),
    }
