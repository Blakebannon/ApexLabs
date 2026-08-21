"""Runtime validation for the hypothesis lifecycle and finding review packages."""

from __future__ import annotations

from typing import Any

from apex_labs.schemas import versions
from apex_labs.schemas.research_validation import _code_identity
from apex_labs.schemas.science_vocabulary import (
    CEILING_SET,
    EVIDENCE_BEARING_STATES,
    HYPOTHESIS_STATE_SET,
    HYPOTHESIS_TRANSITIONS,
    PRODUCT_RECOMMENDATION_STATES,
    SYNTHETIC_PRODUCT_RECOMMENDATIONS,
)
from apex_labs.schemas.validation import (
    _SCOPES,
    _STATUSES,
    _boolean,
    _canonical_hash,
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
)

GENERATION_SOURCES = {"deterministic_algorithm", "human", "llm"}
REVIEW_STATES = {"unreviewed", "pending", "approved", "rejected"}
PRODUCT_REVIEW_STATES = {"not_requested", "pending", "approved", "rejected"}
CORRECTIONS = {"holm_bonferroni", "benjamini_hochberg", "none"}
REPLICATION_STATES = {"not_required", "required_before_validation", "this_run_is_the_replication"}


def hypothesis_hash(hypothesis: dict[str, Any]) -> str:
    """Canonical hash over everything except the stored self-hash."""
    return _canonical_hash({key: value for key, value in hypothesis.items() if key != "hypothesis_sha256"})


def transition_hash(transition: dict[str, Any]) -> str:
    return _canonical_hash(
        {key: value for key, value in transition.items() if key != "transition_sha256"}
    )


def validate_hypothesis(value: Any) -> dict[str, Any]:
    obj = _object(value, "$")
    _version(obj, versions.HYPOTHESIS)
    _keys(
        obj,
        "$",
        required={
            "schema_version", "hypothesis_id", "version", "created_at", "synthetic", "title",
            "statement", "null_statement", "scientific_question", "scope", "generation",
            "hypothesis_sha256",
        },
    )
    _id(obj["hypothesis_id"], "$.hypothesis_id")
    _string(obj["version"], "$.version")
    _timestamp(obj["created_at"], "$.created_at")
    _boolean(obj["synthetic"], "$.synthetic")
    for name in ("title", "statement", "null_statement", "scientific_question"):
        _string(obj[name], f"$.{name}")
    _enum(obj["scope"], _SCOPES, "$.scope")
    generation = _object(obj["generation"], "$.generation")
    _keys(generation, "$.generation", required={"source", "actor", "detail", "is_evidence"})
    _enum(generation["source"], GENERATION_SOURCES, "$.generation.source")
    _string(generation["actor"], "$.generation.actor")
    _string(generation["detail"], "$.generation.detail")
    if generation["is_evidence"] is not False:
        _fail(
            "$.generation.is_evidence",
            "a generated hypothesis is a proposal; an algorithm or a language model producing it is never evidence",
        )
    _sha(obj["hypothesis_sha256"], "$.hypothesis_sha256")
    if obj["hypothesis_sha256"] != hypothesis_hash(obj):
        _fail("$.hypothesis_sha256", "does not match the canonical hypothesis content")
    return obj


def _optional_object(value: Any, path: str, required: set[str]) -> dict[str, Any] | None:
    if value is None:
        return None
    obj = _object(value, path)
    _keys(obj, path, required=required)
    return obj


def validate_hypothesis_transition(value: Any) -> dict[str, Any]:
    obj = _object(value, "$")
    _version(obj, versions.HYPOTHESIS_TRANSITION)
    _keys(
        obj,
        "$",
        required={
            "schema_version", "transition_id", "sequence_index", "hypothesis_id",
            "hypothesis_version", "hypothesis_sha256", "recorded_at", "synthetic", "from_state",
            "to_state", "previous_transition_sha256", "transition_sha256", "rationale",
            "bindings", "reviewer", "code_identity",
        },
    )
    _id(obj["transition_id"], "$.transition_id")
    sequence_index = _integer(obj["sequence_index"], "$.sequence_index", minimum=0)
    _id(obj["hypothesis_id"], "$.hypothesis_id")
    _string(obj["hypothesis_version"], "$.hypothesis_version")
    _sha(obj["hypothesis_sha256"], "$.hypothesis_sha256")
    _timestamp(obj["recorded_at"], "$.recorded_at")
    synthetic = _boolean(obj["synthetic"], "$.synthetic")
    from_state = obj["from_state"]
    if from_state is not None:
        _enum(from_state, HYPOTHESIS_STATE_SET, "$.from_state")
    to_state = _enum(obj["to_state"], HYPOTHESIS_STATE_SET, "$.to_state")
    if from_state is None:
        if sequence_index != 0:
            _fail("$.from_state", "only the first transition may originate from no prior state")
        if to_state != "generated":
            _fail("$.to_state", "a hypothesis lifecycle begins at generated")
    else:
        if sequence_index == 0:
            _fail("$.sequence_index", "the first transition has no prior state")
        if to_state not in HYPOTHESIS_TRANSITIONS[from_state]:
            _fail(
                "$.to_state",
                f"{from_state!r} does not permit a direct transition to {to_state!r}; states are never skipped",
            )
    previous = obj["previous_transition_sha256"]
    if previous is None:
        if sequence_index != 0:
            _fail("$.previous_transition_sha256", "only the first transition has no predecessor")
    else:
        _sha(previous, "$.previous_transition_sha256")
        if sequence_index == 0:
            _fail("$.previous_transition_sha256", "the first transition has no predecessor")
    _sha(obj["transition_sha256"], "$.transition_sha256")
    if obj["transition_sha256"] != transition_hash(obj):
        _fail("$.transition_sha256", "does not match the canonical transition content")
    _string(obj["rationale"], "$.rationale")

    bindings = _object(obj["bindings"], "$.bindings")
    _keys(
        bindings,
        "$.bindings",
        required={
            "protocol", "evidence_set", "analysis_definition", "analysis_run",
            "interpretation_ceiling", "multiple_comparison", "falsification", "replication",
        },
    )
    protocol = _optional_object(bindings["protocol"], "$.bindings.protocol", {"freeze_id", "freeze_sha256"})
    if protocol is not None:
        _id(protocol["freeze_id"], "$.bindings.protocol.freeze_id")
        _sha(protocol["freeze_sha256"], "$.bindings.protocol.freeze_sha256")
    evidence = _optional_object(
        bindings["evidence_set"],
        "$.bindings.evidence_set",
        {"evidence_set_id", "version", "evidence_set_sha256", "synthetic"},
    )
    if evidence is not None:
        _id(evidence["evidence_set_id"], "$.bindings.evidence_set.evidence_set_id")
        _string(evidence["version"], "$.bindings.evidence_set.version")
        _sha(evidence["evidence_set_sha256"], "$.bindings.evidence_set.evidence_set_sha256")
        if _boolean(evidence["synthetic"], "$.bindings.evidence_set.synthetic") != synthetic:
            _fail("$.bindings.evidence_set.synthetic", "must agree with the transition synthetic classification")
    analysis_definition = _optional_object(
        bindings["analysis_definition"],
        "$.bindings.analysis_definition",
        {"analysis_id", "version", "definition_sha256", "classification"},
    )
    if analysis_definition is not None:
        _id(analysis_definition["analysis_id"], "$.bindings.analysis_definition.analysis_id")
        _string(analysis_definition["version"], "$.bindings.analysis_definition.version")
        _sha(analysis_definition["definition_sha256"], "$.bindings.analysis_definition.definition_sha256")
        _enum(
            analysis_definition["classification"],
            {"confirmatory", "exploratory"},
            "$.bindings.analysis_definition.classification",
        )
    analysis_run = _optional_object(
        bindings["analysis_run"],
        "$.bindings.analysis_run",
        {"run_id", "run_sha256", "analysis_state", "verified", "synthetic"},
    )
    if analysis_run is not None:
        _id(analysis_run["run_id"], "$.bindings.analysis_run.run_id")
        _sha(analysis_run["run_sha256"], "$.bindings.analysis_run.run_sha256")
        _enum(analysis_run["analysis_state"], {"computed", "inconclusive"}, "$.bindings.analysis_run.analysis_state")
        _boolean(analysis_run["verified"], "$.bindings.analysis_run.verified")
        if _boolean(analysis_run["synthetic"], "$.bindings.analysis_run.synthetic") != synthetic:
            _fail("$.bindings.analysis_run.synthetic", "must agree with the transition synthetic classification")
    ceiling = bindings["interpretation_ceiling"]
    if ceiling is not None:
        _enum(ceiling, CEILING_SET, "$.bindings.interpretation_ceiling")
    multiple = _optional_object(
        bindings["multiple_comparison"], "$.bindings.multiple_comparison", {"family_id", "correction", "member_count"}
    )
    if multiple is not None:
        _id(multiple["family_id"], "$.bindings.multiple_comparison.family_id")
        _enum(multiple["correction"], CORRECTIONS, "$.bindings.multiple_comparison.correction")
        _integer(multiple["member_count"], "$.bindings.multiple_comparison.member_count", minimum=1)
    falsification = _optional_object(
        bindings["falsification"], "$.bindings.falsification", {"tests_run", "fragile_count"}
    )
    if falsification is not None:
        tests_run = _integer(falsification["tests_run"], "$.bindings.falsification.tests_run", minimum=0)
        fragile = _integer(falsification["fragile_count"], "$.bindings.falsification.fragile_count", minimum=0)
        if fragile > tests_run:
            _fail("$.bindings.falsification.fragile_count", "cannot exceed the number of tests run")
    replication = _optional_object(bindings["replication"], "$.bindings.replication", {"state", "scope"})
    if replication is not None:
        _enum(replication["state"], REPLICATION_STATES, "$.bindings.replication.state")
        _string(replication["scope"], "$.bindings.replication.scope")

    reviewer = _object(obj["reviewer"], "$.reviewer")
    _keys(reviewer, "$.reviewer", required={"state", "reviewer_id", "reviewed_at", "notes"})
    review_state = _enum(reviewer["state"], REVIEW_STATES, "$.reviewer.state")
    if reviewer["reviewer_id"] is not None:
        _id(reviewer["reviewer_id"], "$.reviewer.reviewer_id")
    if reviewer["reviewed_at"] is not None:
        _timestamp(reviewer["reviewed_at"], "$.reviewer.reviewed_at")
    _strings(reviewer["notes"], "$.reviewer.notes")
    if review_state in {"approved", "rejected"} and (reviewer["reviewer_id"] is None or reviewer["reviewed_at"] is None):
        _fail("$.reviewer", "a resolved review must name its reviewer and time")
    _code_identity(obj["code_identity"], "$.code_identity")

    if to_state == "analysis_ready":
        if protocol is None or evidence is None or analysis_definition is None:
            _fail(
                "$.bindings",
                "analysis_ready requires an exact frozen protocol, evidence-set, and frozen analysis-definition binding",
            )
        if analysis_run is not None:
            _fail("$.bindings.analysis_run", "a hypothesis becomes analysis_ready before any run exists")
    if to_state in EVIDENCE_BEARING_STATES:
        missing = [
            name
            for name, bound in (
                ("protocol", protocol),
                ("evidence_set", evidence),
                ("analysis_definition", analysis_definition),
                ("analysis_run", analysis_run),
                ("multiple_comparison", multiple),
                ("falsification", falsification),
                ("replication", replication),
            )
            if bound is None
        ]
        if ceiling is None:
            missing.append("interpretation_ceiling")
        if missing:
            _fail(
                "$.bindings",
                f"an evidence-bearing state requires complete bindings; missing={sorted(missing)}",
            )
        if analysis_run is not None and not analysis_run["verified"]:
            _fail("$.bindings.analysis_run.verified", "an evidence-bearing state requires an independently verified run")
        if review_state == "unreviewed":
            _fail("$.reviewer.state", "an evidence-bearing state requires a recorded reviewer disposition")
    if to_state == "supported_provisionally":
        if review_state != "approved":
            _fail("$.reviewer.state", "provisional support requires an approved scientific review")
        if analysis_run is not None and analysis_run["analysis_state"] != "computed":
            _fail("$.bindings.analysis_run.analysis_state", "provisional support requires a computed result")
    if to_state == "inconclusive" and analysis_run is not None and analysis_run["analysis_state"] == "computed":
        if review_state not in {"approved", "pending"}:
            _fail("$.reviewer.state", "an inconclusive disposition over a computed result requires review")
    return obj


def validate_finding_review_package(value: Any) -> dict[str, Any]:
    obj = _object(value, "$")
    _version(obj, versions.FINDING_REVIEW_PACKAGE)
    _keys(
        obj,
        "$",
        required={
            "schema_version", "package_id", "version", "created_at", "synthetic", "classification",
            "method_id", "package_sha256", "finding", "hypothesis", "protocol", "evidence",
            "analysis_definition", "analysis_run", "metric_definitions", "effect", "uncertainty",
            "practical_threshold", "statistical_evidence", "sufficiency", "attrition", "confounds",
            "sensitivity", "replication", "interpretation_ceiling", "limitations",
            "scientific_review", "product_review", "product_recommendation", "code_identity",
            "report_sha256",
        },
    )
    _id(obj["package_id"], "$.package_id")
    _string(obj["version"], "$.version")
    _timestamp(obj["created_at"], "$.created_at")
    synthetic = _boolean(obj["synthetic"], "$.synthetic")
    if obj["classification"] != "evidence_for_human_review_not_a_production_change":
        _fail("$.classification", "a review package is evidence for humans, never a production change")
    if obj["method_id"] != versions.REVIEW_PACKAGE_METHOD_ID:
        _fail("$.method_id", f"must be {versions.REVIEW_PACKAGE_METHOD_ID!r}")
    _sha(obj["package_sha256"], "$.package_sha256")

    finding = _object(obj["finding"], "$.finding")
    _keys(
        finding,
        "$.finding",
        required={
            "finding_id", "version", "finding_sha256", "status", "title", "research_question",
            "scope", "evidence_classification", "validation_id", "validation_version",
        },
    )
    _id(finding["finding_id"], "$.finding.finding_id")
    _string(finding["version"], "$.finding.version")
    _sha(finding["finding_sha256"], "$.finding.finding_sha256")
    status = _enum(finding["status"], _STATUSES, "$.finding.status")
    if synthetic and status not in {"inconclusive", "rejected"}:
        _fail(
            "$.finding.status",
            "a synthetic review package may only preserve an inconclusive or rejected demo finding",
        )
    _string(finding["title"], "$.finding.title")
    _string(finding["research_question"], "$.finding.research_question")
    _enum(finding["scope"], _SCOPES, "$.finding.scope")
    evidence_classification = _enum(
        finding["evidence_classification"],
        {"controlled", "observational", "synthetic_demo"},
        "$.finding.evidence_classification",
    )
    _id(finding["validation_id"], "$.finding.validation_id")
    _string(finding["validation_version"], "$.finding.validation_version")
    if synthetic and evidence_classification != "synthetic_demo":
        _fail("$.finding.evidence_classification", "synthetic evidence remains a synthetic demonstration")

    hypothesis = _object(obj["hypothesis"], "$.hypothesis")
    _keys(
        hypothesis,
        "$.hypothesis",
        required={
            "hypothesis_id", "version", "hypothesis_sha256", "state", "transition_count",
            "head_transition_sha256", "generation_source",
        },
    )
    _id(hypothesis["hypothesis_id"], "$.hypothesis.hypothesis_id")
    _string(hypothesis["version"], "$.hypothesis.version")
    _sha(hypothesis["hypothesis_sha256"], "$.hypothesis.hypothesis_sha256")
    hypothesis_state = _enum(hypothesis["state"], HYPOTHESIS_STATE_SET, "$.hypothesis.state")
    _integer(hypothesis["transition_count"], "$.hypothesis.transition_count", minimum=1)
    _sha(hypothesis["head_transition_sha256"], "$.hypothesis.head_transition_sha256")
    _enum(hypothesis["generation_source"], GENERATION_SOURCES, "$.hypothesis.generation_source")

    protocol = _object(obj["protocol"], "$.protocol")
    _keys(
        protocol,
        "$.protocol",
        required={
            "freeze_id", "freeze_sha256", "protocol_id", "protocol_version", "protocol_sha256",
            "scientific_question",
        },
    )
    _id(protocol["freeze_id"], "$.protocol.freeze_id")
    _id(protocol["protocol_id"], "$.protocol.protocol_id")
    for name in ("freeze_sha256", "protocol_sha256"):
        _sha(protocol[name], f"$.protocol.{name}")
    _string(protocol["protocol_version"], "$.protocol.protocol_version")
    _string(protocol["scientific_question"], "$.protocol.scientific_question")

    evidence = _object(obj["evidence"], "$.evidence")
    _keys(
        evidence,
        "$.evidence",
        required={
            "evidence_set_id", "version", "evidence_set_sha256", "definition_sha256",
            "segment_definition_id", "segment_definition_sha256", "datasets",
            "comparability_status", "comparability_violations", "counts", "experimental_unit",
            "resampling_unit",
        },
    )
    _id(evidence["evidence_set_id"], "$.evidence.evidence_set_id")
    _string(evidence["version"], "$.evidence.version")
    for name in ("evidence_set_sha256", "definition_sha256", "segment_definition_sha256"):
        _sha(evidence[name], f"$.evidence.{name}")
    _id(evidence["segment_definition_id"], "$.evidence.segment_definition_id")
    datasets = _list(evidence["datasets"], "$.evidence.datasets", nonempty=True)
    for index, item in enumerate(datasets):
        path = f"$.evidence.datasets[{index}]"
        dataset = _object(item, path)
        _keys(dataset, path, required={"dataset_id", "fingerprint", "synthetic"})
        _id(dataset["dataset_id"], f"{path}.dataset_id")
        _sha(dataset["fingerprint"], f"{path}.fingerprint")
        if _boolean(dataset["synthetic"], f"{path}.synthetic") != synthetic:
            _fail(f"{path}.synthetic", "package and evidence synthetic classifications must agree")
    _enum(evidence["comparability_status"], {"adequate", "limited", "inadequate"}, "$.evidence.comparability_status")
    _strings(evidence["comparability_violations"], "$.evidence.comparability_violations")
    _object(evidence["counts"], "$.evidence.counts")
    _string(evidence["experimental_unit"], "$.evidence.experimental_unit")
    _string(evidence["resampling_unit"], "$.evidence.resampling_unit")

    analysis_definition = _object(obj["analysis_definition"], "$.analysis_definition")
    _keys(
        analysis_definition,
        "$.analysis_definition",
        required={"analysis_id", "version", "definition_sha256", "classification"},
    )
    _id(analysis_definition["analysis_id"], "$.analysis_definition.analysis_id")
    _string(analysis_definition["version"], "$.analysis_definition.version")
    _sha(analysis_definition["definition_sha256"], "$.analysis_definition.definition_sha256")
    _enum(
        analysis_definition["classification"],
        {"confirmatory", "exploratory"},
        "$.analysis_definition.classification",
    )

    analysis_run = _object(obj["analysis_run"], "$.analysis_run")
    _keys(
        analysis_run,
        "$.analysis_run",
        required={"run_id", "run_sha256", "analysis_state", "recomputed_and_verified", "scope"},
    )
    _id(analysis_run["run_id"], "$.analysis_run.run_id")
    _sha(analysis_run["run_sha256"], "$.analysis_run.run_sha256")
    analysis_state = _enum(
        analysis_run["analysis_state"], {"computed", "inconclusive"}, "$.analysis_run.analysis_state"
    )
    recomputed = _boolean(analysis_run["recomputed_and_verified"], "$.analysis_run.recomputed_and_verified")
    _enum(analysis_run["scope"], {"primary", "holdout"}, "$.analysis_run.scope")

    metrics = _list(obj["metric_definitions"], "$.metric_definitions", nonempty=True)
    seen_metrics: set[tuple[str, str]] = set()
    for index, item in enumerate(metrics):
        path = f"$.metric_definitions[{index}]"
        metric = _object(item, path)
        _keys(metric, path, required={"metric_id", "version", "sha256"})
        identity = (_id(metric["metric_id"], f"{path}.metric_id"), _string(metric["version"], f"{path}.version"))
        if identity in seen_metrics:
            _fail(path, "metric identity must be unique")
        seen_metrics.add(identity)
        _sha(metric["sha256"], f"{path}.sha256")

    if obj["effect"] is not None:
        _object(obj["effect"], "$.effect")
    _object(obj["uncertainty"], "$.uncertainty")
    _object(obj["practical_threshold"], "$.practical_threshold")

    statistical = _object(obj["statistical_evidence"], "$.statistical_evidence")
    _keys(
        statistical,
        "$.statistical_evidence",
        required={"raw", "adjusted", "correction", "family_id", "interpretation"},
    )
    for name in ("raw", "adjusted"):
        if statistical[name] is not None:
            probability = _number(statistical[name], f"$.statistical_evidence.{name}")
            if not 0 <= probability <= 1:
                _fail(f"$.statistical_evidence.{name}", "must lie within [0, 1]")
    _enum(statistical["correction"], CORRECTIONS, "$.statistical_evidence.correction")
    _id(statistical["family_id"], "$.statistical_evidence.family_id")
    _string(statistical["interpretation"], "$.statistical_evidence.interpretation")

    _object(obj["sufficiency"], "$.sufficiency")
    attrition = _list(obj["attrition"], "$.attrition")
    for index, item in enumerate(attrition):
        _object(item, f"$.attrition[{index}]")
    _object(obj["confounds"], "$.confounds")
    sensitivity = _list(obj["sensitivity"], "$.sensitivity")
    for index, item in enumerate(sensitivity):
        _object(item, f"$.sensitivity[{index}]")

    replication = _object(obj["replication"], "$.replication")
    _keys(
        replication,
        "$.replication",
        required={"state", "required_scope", "achieved_scope", "holdout_available", "holdout_tested"},
    )
    _enum(replication["state"], REPLICATION_STATES, "$.replication.state")
    _string(replication["required_scope"], "$.replication.required_scope")
    _string(replication["achieved_scope"], "$.replication.achieved_scope")
    holdout_available = _boolean(replication["holdout_available"], "$.replication.holdout_available")
    holdout_tested = _boolean(replication["holdout_tested"], "$.replication.holdout_tested")
    if holdout_tested and not holdout_available:
        _fail("$.replication.holdout_tested", "reserved evidence cannot be tested when none was reserved")

    _enum(obj["interpretation_ceiling"], CEILING_SET, "$.interpretation_ceiling")
    _strings(obj["limitations"], "$.limitations", nonempty=True)

    review = _object(obj["scientific_review"], "$.scientific_review")
    _keys(
        review,
        "$.scientific_review",
        required={"state", "gate_structural", "gate_reproducibility", "gate_scientific"},
    )
    review_state = _enum(review["state"], REVIEW_STATES, "$.scientific_review.state")
    gate_structural = _enum(review["gate_structural"], {"passed", "failed"}, "$.scientific_review.gate_structural")
    gate_reproducibility = _enum(
        review["gate_reproducibility"], {"passed", "failed", "unresolved"}, "$.scientific_review.gate_reproducibility"
    )
    gate_scientific = _enum(
        review["gate_scientific"], {"passed", "failed", "unresolved"}, "$.scientific_review.gate_scientific"
    )
    product_review = _enum(obj["product_review"], PRODUCT_REVIEW_STATES, "$.product_review")

    recommendation = _object(obj["product_recommendation"], "$.product_recommendation")
    _keys(recommendation, "$.product_recommendation", required={"state", "rationale", "automatic_production_change"})
    state = _enum(recommendation["state"], PRODUCT_RECOMMENDATION_STATES, "$.product_recommendation.state")
    _string(recommendation["rationale"], "$.product_recommendation.rationale")
    if recommendation["automatic_production_change"] is not False:
        _fail(
            "$.product_recommendation.automatic_production_change",
            "Apex Labs never automatically changes Apex Sim Coach",
        )
    if synthetic and state not in SYNTHETIC_PRODUCT_RECOMMENDATIONS:
        _fail(
            "$.product_recommendation.state",
            "synthetic mechanics may only recommend none or do_not_implement",
        )
    if synthetic and product_review != "not_requested":
        _fail(
            "$.product_review",
            "synthetic evidence cannot enter product review; state must remain not_requested",
        )
    if state == "engineering_review_candidate":
        if status != "validated":
            _fail("$.product_recommendation.state", "only a validated finding may be an engineering-review candidate")
        if gate_scientific != "passed" or gate_reproducibility != "passed" or review_state != "approved":
            _fail(
                "$.product_recommendation.state",
                "an engineering-review candidate requires passed reproducibility and scientific gates and an approved review",
            )
        if replication["state"] == "required_before_validation":
            _fail("$.product_recommendation.state", "replication is still required")
    if status == "validated":
        if gate_scientific != "passed" or gate_reproducibility != "passed" or review_state != "approved":
            _fail("$.finding.status", "a validated finding requires passed gates and an approved review")
        if analysis_state != "computed":
            _fail("$.analysis_run.analysis_state", "a validated finding requires a computed result")
        if not recomputed:
            _fail("$.analysis_run.recomputed_and_verified", "a validated finding requires an independently recomputed run")
        if hypothesis_state not in {"supported_provisionally", "tested"}:
            _fail("$.hypothesis.state", "a validated finding requires a tested hypothesis")
        if synthetic:
            _fail("$.finding.status", "synthetic mechanics may never reach validated")
    if gate_structural != "passed":
        _fail("$.scientific_review.gate_structural", "a review package is only assembled from structurally valid artifacts")
    if gate_scientific == "unresolved" and status not in {"inconclusive", "provisional"}:
        _fail("$.finding.status", "an unresolved scientific gate cannot carry a stronger status")
    _code_identity(obj["code_identity"], "$.code_identity")
    _sha(obj["report_sha256"], "$.report_sha256")
    return obj
