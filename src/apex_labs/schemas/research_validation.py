"""Runtime validation for immutable research and review artifacts."""

from __future__ import annotations

from typing import Any

from apex_labs.schemas import versions
from apex_labs.schemas.validation import (
    _boolean,
    _canonical_hash,
    _commit,
    _enum,
    _fail,
    _id,
    _integer,
    _keys,
    _list,
    _number,
    _object,
    _sha,
    _string,
    _strings,
    _timestamp,
    _version,
    validate_experiment,
    _SCOPES,
)


def _code_identity(value: Any, path: str) -> dict[str, Any]:
    obj = _object(value, path)
    _keys(
        obj,
        path,
        required={"package_version", "git_commit", "git_state", "code_and_schema_sha256", "schema_sha256"},
    )
    _string(obj["package_version"], f"{path}.package_version")
    _commit(obj["git_commit"], f"{path}.git_commit")
    _enum(obj["git_state"], {"clean", "dirty", "uncommitted"}, f"{path}.git_state")
    _sha(obj["code_and_schema_sha256"], f"{path}.code_and_schema_sha256")
    schemas = _object(obj["schema_sha256"], f"{path}.schema_sha256")
    if not schemas:
        _fail(f"{path}.schema_sha256", "must not be empty")
    for name, digest in schemas.items():
        _string(name, f"{path}.schema_sha256 key")
        _sha(digest, f"{path}.schema_sha256.{name}")
    return obj


def validate_protocol_freeze(value: Any) -> dict[str, Any]:
    obj = _object(value, "$")
    _version(obj, versions.PROTOCOL_FREEZE)
    _keys(
        obj,
        "$",
        required={
            "schema_version", "freeze_id", "freeze_sha256", "protocol_id", "protocol_version",
            "protocol_sha256", "source_commit", "code_identity", "frozen_at", "synthetic",
            "protocol", "randomization", "amendment_history",
        },
    )
    _id(obj["freeze_id"], "$.freeze_id")
    _sha(obj["freeze_sha256"], "$.freeze_sha256")
    protocol_id = _id(obj["protocol_id"], "$.protocol_id")
    protocol_version = _string(obj["protocol_version"], "$.protocol_version")
    _sha(obj["protocol_sha256"], "$.protocol_sha256")
    commit = _commit(obj["source_commit"], "$.source_commit")
    identity = _code_identity(obj["code_identity"], "$.code_identity")
    _timestamp(obj["frozen_at"], "$.frozen_at")
    synthetic = _boolean(obj["synthetic"], "$.synthetic")
    protocol = validate_experiment(obj["protocol"])
    if protocol["experiment_id"] != protocol_id or protocol["version"] != protocol_version:
        _fail("$.protocol", "identity/version must match frozen snapshot fields")
    if protocol["status"] != "preregistered":
        _fail("$.protocol.status", "frozen protocols must be preregistered")
    if protocol["synthetic"] != synthetic or protocol["apex_labs_source_commit"] != commit:
        _fail("$.protocol", "synthetic classification and source commit must match snapshot")
    if not synthetic and (identity["git_state"] != "clean" or identity["git_commit"] != commit):
        _fail("$.code_identity", "real frozen protocol requires matching clean commit")
    randomization = _object(obj["randomization"], "$.randomization")
    _keys(randomization, "$.randomization", required={"strategy", "method", "seed", "schedule_id", "schedule", "schedule_sha256"})
    strategy = _enum(randomization["strategy"], {"randomized", "counterbalanced", "fixed", "not_applicable"}, "$.randomization.strategy")
    _string(randomization["method"], "$.randomization.method")
    if randomization["seed"] is not None:
        _integer(randomization["seed"], "$.randomization.seed", minimum=0)
    _id(randomization["schedule_id"], "$.randomization.schedule_id")
    schedule = _list(randomization["schedule"], "$.randomization.schedule")
    _sha(randomization["schedule_sha256"], "$.randomization.schedule_sha256")
    if strategy in {"randomized", "counterbalanced"} and randomization["seed"] is None and not schedule:
        _fail("$.randomization", "randomized/counterbalanced freezes require a seed or frozen schedule")
    if strategy == "fixed" and not schedule:
        _fail("$.randomization.schedule", "fixed strategy requires a frozen schedule")
    history = _list(obj["amendment_history"], "$.amendment_history")
    for index, entry in enumerate(history):
        path = f"$.amendment_history[{index}]"
        item = _object(entry, path)
        _keys(item, path, required={"amendment_id", "version", "amendment_sha256"})
        _id(item["amendment_id"], f"{path}.amendment_id")
        _string(item["version"], f"{path}.version")
        _sha(item["amendment_sha256"], f"{path}.amendment_sha256")
    return obj


def validate_protocol_amendment(value: Any) -> dict[str, Any]:
    obj = _object(value, "$")
    _version(obj, versions.PROTOCOL_AMENDMENT)
    _keys(
        obj,
        "$",
        required={
            "schema_version", "amendment_id", "version", "amendment_sha256",
            "frozen_protocol", "created_at", "source_commit", "reason", "changes",
            "impact_assessment", "requires_new_protocol_version", "prior_amendments", "synthetic",
        },
    )
    _id(obj["amendment_id"], "$.amendment_id")
    _string(obj["version"], "$.version")
    _sha(obj["amendment_sha256"], "$.amendment_sha256")
    frozen = _object(obj["frozen_protocol"], "$.frozen_protocol")
    _keys(frozen, "$.frozen_protocol", required={"freeze_id", "freeze_sha256", "protocol_id", "protocol_version"})
    _id(frozen["freeze_id"], "$.frozen_protocol.freeze_id")
    _sha(frozen["freeze_sha256"], "$.frozen_protocol.freeze_sha256")
    _id(frozen["protocol_id"], "$.frozen_protocol.protocol_id")
    _string(frozen["protocol_version"], "$.frozen_protocol.protocol_version")
    _timestamp(obj["created_at"], "$.created_at")
    _commit(obj["source_commit"], "$.source_commit")
    _string(obj["reason"], "$.reason")
    changes = _list(obj["changes"], "$.changes", nonempty=True)
    for index, change in enumerate(changes):
        path = f"$.changes[{index}]"
        item = _object(change, path)
        _keys(item, path, required={"field_path", "before_sha256", "after_value", "rationale"})
        _string(item["field_path"], f"{path}.field_path")
        _sha(item["before_sha256"], f"{path}.before_sha256")
        _string(item["rationale"], f"{path}.rationale")
    _string(obj["impact_assessment"], "$.impact_assessment")
    _boolean(obj["requires_new_protocol_version"], "$.requires_new_protocol_version")
    prior = _list(obj["prior_amendments"], "$.prior_amendments")
    prior_identities: set[tuple[str, str]] = set()
    for index, entry in enumerate(prior):
        path = f"$.prior_amendments[{index}]"
        item = _object(entry, path)
        _keys(item, path, required={"amendment_id", "version", "amendment_sha256"})
        identity = (
            _id(item["amendment_id"], f"{path}.amendment_id"),
            _string(item["version"], f"{path}.version"),
        )
        if identity in prior_identities:
            _fail(path, "duplicate prior amendment identity")
        prior_identities.add(identity)
        _sha(item["amendment_sha256"], f"{path}.amendment_sha256")
    synthetic = _boolean(obj["synthetic"], "$.synthetic")
    if not synthetic and obj["source_commit"] == "UNCOMMITTED":
        _fail("$.source_commit", "real amendments require a source commit")
    return obj


def validate_finding_validation(value: Any) -> dict[str, Any]:
    obj = _object(value, "$")
    _version(obj, versions.FINDING_VALIDATION)
    _keys(
        obj,
        "$",
        required={
            "schema_version", "validation_id", "version", "finding_id", "finding_version",
            "finding_sha256", "synthetic", "datasets", "frozen_protocol", "preprocessing",
            "analysis", "analysis_code_identity", "computed_evidence", "scope_assessment",
            "population_validation_design", "gate_evaluations", "review", "product_review_state",
            "created_at",
        },
    )
    _id(obj["validation_id"], "$.validation_id")
    _string(obj["version"], "$.version")
    _id(obj["finding_id"], "$.finding_id")
    _string(obj["finding_version"], "$.finding_version")
    _sha(obj["finding_sha256"], "$.finding_sha256")
    synthetic = _boolean(obj["synthetic"], "$.synthetic")
    datasets = _list(obj["datasets"], "$.datasets", nonempty=True)
    seen_datasets: set[tuple[str, str]] = set()
    for index, dataset in enumerate(datasets):
        path = f"$.datasets[{index}]"
        item = _object(dataset, path)
        _keys(item, path, required={"dataset_id", "fingerprint", "normalized_manifest_sha256", "records_sha256", "synthetic"})
        identity = (_id(item["dataset_id"], f"{path}.dataset_id"), _sha(item["fingerprint"], f"{path}.fingerprint"))
        if identity in seen_datasets:
            _fail(path, "duplicate dataset identity/fingerprint")
        seen_datasets.add(identity)
        _sha(item["normalized_manifest_sha256"], f"{path}.normalized_manifest_sha256")
        _sha(item["records_sha256"], f"{path}.records_sha256")
        if _boolean(item["synthetic"], f"{path}.synthetic") != synthetic:
            _fail(path, "dataset synthetic classification must match validation artifact")
    frozen = _object(obj["frozen_protocol"], "$.frozen_protocol")
    _keys(frozen, "$.frozen_protocol", required={"freeze_id", "freeze_sha256", "protocol_id", "protocol_version"})
    _id(frozen["freeze_id"], "$.frozen_protocol.freeze_id")
    _sha(frozen["freeze_sha256"], "$.frozen_protocol.freeze_sha256")
    _id(frozen["protocol_id"], "$.frozen_protocol.protocol_id")
    _string(frozen["protocol_version"], "$.frozen_protocol.protocol_version")
    preprocessing = _object(obj["preprocessing"], "$.preprocessing")
    _keys(preprocessing, "$.preprocessing", required={"pipeline_id", "pipeline_version", "normalization_version", "configuration", "configuration_sha256"})
    _id(preprocessing["pipeline_id"], "$.preprocessing.pipeline_id")
    _string(preprocessing["pipeline_version"], "$.preprocessing.pipeline_version")
    _string(preprocessing["normalization_version"], "$.preprocessing.normalization_version")
    _object(preprocessing["configuration"], "$.preprocessing.configuration")
    _sha(preprocessing["configuration_sha256"], "$.preprocessing.configuration_sha256")
    if preprocessing["configuration_sha256"] != _canonical_hash(preprocessing["configuration"]):
        _fail("$.preprocessing.configuration_sha256", "does not match canonical configuration content")
    analysis = _object(obj["analysis"], "$.analysis")
    _keys(analysis, "$.analysis", required={"algorithm_id", "algorithm_version", "configuration", "random_seed"})
    _id(analysis["algorithm_id"], "$.analysis.algorithm_id")
    _string(analysis["algorithm_version"], "$.analysis.algorithm_version")
    _object(analysis["configuration"], "$.analysis.configuration")
    if analysis["random_seed"] is not None:
        _integer(analysis["random_seed"], "$.analysis.random_seed", minimum=0)
    _code_identity(obj["analysis_code_identity"], "$.analysis_code_identity")

    evidence = _object(obj["computed_evidence"], "$.computed_evidence")
    _keys(evidence, "$.computed_evidence", required={"sample_counts", "sample_sufficiency", "exclusions", "effect_estimate", "uncertainty", "comparability", "falsification_attempts"})
    sample_counts = _object(evidence["sample_counts"], "$.computed_evidence.sample_counts")
    _keys(sample_counts, "$.computed_evidence.sample_counts", required={"provenance", "values", "evidence_sha256"})
    sample_provenance = _enum(sample_counts["provenance"], {"computed", "analyst_claim", "unavailable"}, "$.computed_evidence.sample_counts.provenance")
    values = _object(sample_counts["values"], "$.computed_evidence.sample_counts.values")
    expected_counts = {"drivers", "cars", "tracks", "sessions", "laps", "corners_or_events", "observations"}
    _keys(values, "$.computed_evidence.sample_counts.values", required=expected_counts)
    for name in expected_counts:
        _integer(values[name], f"$.computed_evidence.sample_counts.values.{name}", minimum=0)
    if sample_counts["evidence_sha256"] is not None:
        _sha(sample_counts["evidence_sha256"], "$.computed_evidence.sample_counts.evidence_sha256")
    sufficiency = _object(evidence["sample_sufficiency"], "$.computed_evidence.sample_sufficiency")
    _keys(sufficiency, "$.computed_evidence.sample_sufficiency", required={"status", "provenance", "criteria_applied", "evidence_references"})
    _enum(sufficiency["status"], {"sufficient", "insufficient", "undetermined"}, "$.computed_evidence.sample_sufficiency.status")
    sufficiency_provenance = _enum(sufficiency["provenance"], {"computed", "analyst_claim", "unavailable"}, "$.computed_evidence.sample_sufficiency.provenance")
    _strings(sufficiency["criteria_applied"], "$.computed_evidence.sample_sufficiency.criteria_applied", nonempty=True)
    sufficiency_references = _strings(sufficiency["evidence_references"], "$.computed_evidence.sample_sufficiency.evidence_references")
    exclusions = _list(evidence["exclusions"], "$.computed_evidence.exclusions")
    for index, exclusion in enumerate(exclusions):
        path = f"$.computed_evidence.exclusions[{index}]"
        item = _object(exclusion, path)
        _keys(item, path, required={"reason", "count", "provenance", "evidence_sha256"})
        _string(item["reason"], f"{path}.reason")
        _integer(item["count"], f"{path}.count", minimum=0)
        _enum(item["provenance"], {"computed", "analyst_claim"}, f"{path}.provenance")
        if item["evidence_sha256"] is not None:
            _sha(item["evidence_sha256"], f"{path}.evidence_sha256")
    if evidence["effect_estimate"] is not None:
        _object(evidence["effect_estimate"], "$.computed_evidence.effect_estimate")
    _object(evidence["uncertainty"], "$.computed_evidence.uncertainty")
    comparability = _object(evidence["comparability"], "$.computed_evidence.comparability")
    _keys(comparability, "$.computed_evidence.comparability", required={"status", "provenance", "criteria_applied", "violations", "evidence_references"})
    _enum(comparability["status"], {"adequate", "limited", "inadequate", "undetermined"}, "$.computed_evidence.comparability.status")
    comparability_provenance = _enum(comparability["provenance"], {"computed", "analyst_claim", "unavailable"}, "$.computed_evidence.comparability.provenance")
    _strings(comparability["criteria_applied"], "$.computed_evidence.comparability.criteria_applied", nonempty=True)
    _strings(comparability["violations"], "$.computed_evidence.comparability.violations")
    references = _strings(comparability["evidence_references"], "$.computed_evidence.comparability.evidence_references")
    attempts = _list(evidence["falsification_attempts"], "$.computed_evidence.falsification_attempts")
    for index, attempt in enumerate(attempts):
        path = f"$.computed_evidence.falsification_attempts[{index}]"
        item = _object(attempt, path)
        _keys(item, path, required={"description", "outcome", "provenance", "evidence_sha256"})
        _string(item["description"], f"{path}.description")
        _enum(item["outcome"], {"supports_hypothesis", "contradicts_hypothesis", "inconclusive", "not_applicable"}, f"{path}.outcome")
        _enum(item["provenance"], {"computed", "analyst_claim", "unavailable"}, f"{path}.provenance")
        if item["evidence_sha256"] is not None:
            _sha(item["evidence_sha256"], f"{path}.evidence_sha256")

    scope = _object(obj["scope_assessment"], "$.scope_assessment")
    _keys(scope, "$.scope_assessment", required={"scope", "design_basis", "evidence_references"})
    scope_value = _enum(scope["scope"], _SCOPES, "$.scope_assessment.scope")
    _string(scope["design_basis"], "$.scope_assessment.design_basis")
    _strings(scope["evidence_references"], "$.scope_assessment.evidence_references")
    population = obj["population_validation_design"]
    if population is not None:
        population_obj = _object(population, "$.population_validation_design")
        _keys(population_obj, "$.population_validation_design", required={"state", "frozen_protocol", "evidence_sha256", "assessment"})
        population_state = _enum(population_obj["state"], {"passed", "failed", "unresolved"}, "$.population_validation_design.state")
        _object(population_obj["frozen_protocol"], "$.population_validation_design.frozen_protocol")
        if population_obj["evidence_sha256"] is not None:
            _sha(population_obj["evidence_sha256"], "$.population_validation_design.evidence_sha256")
        _string(population_obj["assessment"], "$.population_validation_design.assessment")
    else:
        population_state = "unresolved"
    gates = _object(obj["gate_evaluations"], "$.gate_evaluations")
    _keys(gates, "$.gate_evaluations", required={"structural", "reproducibility", "scientific"})
    structural_gate = _enum(gates["structural"], {"passed", "failed"}, "$.gate_evaluations.structural")
    reproducibility_gate = _enum(gates["reproducibility"], {"passed", "failed", "unresolved"}, "$.gate_evaluations.reproducibility")
    scientific_gate = _enum(gates["scientific"], {"passed", "failed", "unresolved"}, "$.gate_evaluations.scientific")
    review = _object(obj["review"], "$.review")
    _keys(review, "$.review", required={"state", "reviewers", "reviewed_at", "notes"})
    review_state = _enum(review["state"], {"unreviewed", "pending", "approved", "rejected"}, "$.review.state")
    reviewers = _list(review["reviewers"], "$.review.reviewers")
    for index, reviewer in enumerate(reviewers):
        path = f"$.review.reviewers[{index}]"
        item = _object(reviewer, path)
        _keys(item, path, required={"reviewer_id", "role"})
        _id(item["reviewer_id"], f"{path}.reviewer_id")
        _string(item["role"], f"{path}.role")
    if review["reviewed_at"] is not None:
        _timestamp(review["reviewed_at"], "$.review.reviewed_at")
    _strings(review["notes"], "$.review.notes")
    product_state = _enum(obj["product_review_state"], {"not_requested", "pending", "approved", "rejected"}, "$.product_review_state")
    _timestamp(obj["created_at"], "$.created_at")

    if scientific_gate == "passed":
        if structural_gate != "passed" or reproducibility_gate != "passed":
            _fail("$.gate_evaluations.scientific", "cannot pass before structural and reproducibility gates")
        if (
            sample_provenance != "computed"
            or sufficiency_provenance != "computed"
            or not sufficiency_references
            or comparability_provenance != "computed"
            or not references
        ):
            _fail("$.computed_evidence", "scientific pass requires computed counts, sufficiency, comparability, and evidence references")
        if review_state != "approved" or not reviewers or review["reviewed_at"] is None:
            _fail("$.review", "scientific pass requires an explicit approved review record")
    if synthetic and (
        scientific_gate == "passed"
        or review_state == "approved"
        or product_state != "not_requested"
    ):
        _fail(
            "$",
            "synthetic evidence cannot pass scientific review or enter product review",
        )
    if scope_value == "population_supported" and (
        population is None or population_state != "passed" or scientific_gate != "passed"
    ):
        _fail("$.scope_assessment.scope", "population_supported requires a passed preregistered population design and scientific gate")
    return obj
