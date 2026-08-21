"""End-to-end synthetic demonstration of the scientific path.

This runs every known-answer campaign, then walks one of them the whole way:
comparable evidence, preregistered inference, an append-only hypothesis
lifecycle, a finding bound to its independent validation artifact, and a
deterministic review package.

The finding and validation artifact are generated here rather than checked in,
because their dataset references bind fingerprints of bytes this demonstration
fabricates. Nothing produced here is scientific evidence: the finding stays
inconclusive, the scientific gate stays unresolved, and the production
recommendation stays `do_not_implement`.
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from apex_labs.analysis import run_inferential_analysis, verify_inferential_analysis_run
from apex_labs.campaigns import campaign_paths, materialize, run_all_campaigns
from apex_labs.campaigns.runner import BUILT_AT
from apex_labs.errors import IntegrityError
from apex_labs.evidence import build_evidence_set, verify_evidence_set
from apex_labs.findings import finding_hash
from apex_labs.findings.review_package import build_review_package, verify_review_package
from apex_labs.hypotheses import (
    bindings_from_run,
    plan_bindings,
    record_transition,
    register_hypothesis,
    replay,
)
from apex_labs.io import canonical_json_bytes, read_json
from apex_labs.provenance import sha256_bytes
from apex_labs.schemas.versions import FINDING, FINDING_VALIDATION, HYPOTHESIS

DEMO_CAMPAIGN = "clear-paired-improvement"
_PENDING_REVIEW = {
    "state": "pending",
    "reviewer_id": None,
    "reviewed_at": None,
    "notes": [
        "Fabricated evidence. No reviewer can approve a scientific claim from numbers that were invented.",
    ],
}


def _file_inventory(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _primary(run: dict[str, Any]) -> dict[str, Any]:
    return next((item for item in run["comparisons"] if item["role"] == "primary"), run["comparisons"][0])


def _hypothesis(created_at: str) -> dict[str, Any]:
    return {
        "schema_version": HYPOTHESIS,
        "hypothesis_id": "synthetic-corner-speed-demo",
        "version": "1.0.0",
        "created_at": created_at,
        "synthetic": True,
        "title": "Fabricated corner minimum speed under a fabricated intervention block",
        "statement": (
            "In this fabricated corpus, laps in the intervention block show a higher minimum speed through the "
            "declared segment than paired laps in the baseline block."
        ),
        "null_statement": (
            "In this fabricated corpus, intervention-block laps show no difference in segment minimum speed from "
            "paired baseline-block laps."
        ),
        "scientific_question": (
            "Can Apex Labs carry a hypothesis from proposal through preregistered analysis to a preserved "
            "lifecycle state without ever promoting fabricated evidence?"
        ),
        "scope": "session_specific",
        "generation": {
            "source": "deterministic_algorithm",
            "actor": "apex-labs.science-demo",
            "detail": (
                "Stated by the demonstration itself so the lifecycle has something to carry. It describes "
                "fabricated numbers and is not a proposal about driving."
            ),
            "is_evidence": False,
        },
        "hypothesis_sha256": "0" * 64,
    }


def _finding(
    evidence: dict[str, Any], run: dict[str, Any], identity: dict[str, Any], manifest: dict[str, Any]
) -> dict[str, Any]:
    primary = _primary(run)
    effect = primary["effect"]
    counts = evidence["counts"]
    configuration = {
        "evidence_set_sha256": evidence["evidence_set_sha256"],
        "segment_definition_sha256": evidence["segment_definition_sha256"],
    }
    return {
        "schema_version": FINDING,
        "finding_id": "synthetic-inference-demo",
        "version": "1.0.0",
        "title": "Synthetic inference-path demonstration",
        "research_question": run["definition"]["scientific_question"],
        "status": "inconclusive",
        "scope": "session_specific",
        "evidence_classification": "synthetic_demo",
        "hypothesis": run["definition"]["hypothesis"],
        "conclusion": (
            "The artifact records that the comparable-evidence and inference path ran deterministically over "
            "fabricated numbers. It contains no evidence about a driver, car, track, simulator, technique, "
            "causal effect, or population."
        ),
        "effect_estimate": {
            "metric_id": primary["metric_id"],
            "estimate": effect["estimate"],
            "unit": primary["unit_of_measure"],
            "method": effect["effect_size"],
        },
        "uncertainty": {
            "method": primary["uncertainty"]["method"],
            "interval": primary["uncertainty"]["interval"],
            "confidence_level": primary["uncertainty"]["coverage_level"],
            "interpretation": primary["uncertainty"]["semantics"],
        },
        "sample_counts": {
            "drivers": counts["participants"],
            "cars": 1,
            "tracks": 1,
            "sessions": counts["sessions"],
            "laps": counts["included_units"],
            "corners_or_events": counts["pairs"],
            "observations": counts["source_records"],
        },
        "sample_sufficiency": {
            "status": run["sufficiency"]["status"],
            "method": "preregistered_minimum_from_frozen_protocol",
            "rationale": (
                "The fabricated corpus satisfies the fabricated software requirement cited from the frozen "
                "protocol. Satisfying a software requirement is not scientific adequacy."
            ),
        },
        "comparability_assessment": {
            "status": evidence["comparability"]["status"],
            "criteria_applied": evidence["comparability"]["must_match_fields"],
            "violations": evidence["comparability"]["violations"],
        },
        "dataset_references": [
            {
                "dataset_id": dataset["dataset_id"],
                "fingerprint": dataset["fingerprint"],
                "normalized_manifest_sha256": dataset["normalized_manifest_sha256"],
                "records_sha256": dataset["records_sha256"],
                "synthetic": dataset["synthetic"],
            }
            for dataset in evidence["datasets"]
        ],
        "protocol_reference": {
            "experiment_id": evidence["protocol"]["protocol_id"],
            "version": evidence["protocol"]["protocol_version"],
            "freeze_id": evidence["protocol"]["freeze_id"],
            "freeze_sha256": evidence["protocol"]["freeze_sha256"],
        },
        "preprocessing": {
            "pipeline_id": manifest["preprocessing"]["pipeline_id"],
            "pipeline_version": manifest["preprocessing"]["pipeline_version"],
            "normalization_version": manifest["normalization_version"],
            "configuration": configuration,
            "configuration_sha256": sha256_bytes(canonical_json_bytes(configuration)),
        },
        "analysis": {
            "algorithm_id": run["definition"]["analysis_id"],
            "algorithm_version": run["definition"]["version"],
            "configuration": {"definition_sha256": run["definition_sha256"]},
            "random_seed": run["definition"]["uncertainty"]["random_seed"],
        },
        "analysis_code_identity": {
            key: identity[key]
            for key in ("package_version", "git_commit", "git_state", "code_and_schema_sha256")
        },
        "analyst_claim": {
            "proposed_status": "inconclusive",
            "rationale": (
                "The run is a software demonstration over fabricated numbers and cannot support a scientific "
                "disposition regardless of how clean its statistics look."
            ),
        },
        "validation_artifact_reference": {
            "validation_id": "synthetic-inference-demo-validation",
            "version": "1.0.0",
        },
        "scientific_review_state": "pending",
        "product_review_state": "not_requested",
        "limitations": run["limitations"],
        "possible_confounders": evidence["confounds"]["unavailable"],
        "generalizability_assessment": (
            "None. Every number was fabricated by a checked-in campaign specification and must not be "
            "generalized to any driver, vehicle, track, simulator, corner, algorithm, or population."
        ),
        "falsification_attempts": [
            f"{item['test_id']} ({item['kind']}): {item['outcome']}" for item in run["sensitivity"]
        ],
        "product_implication": (
            "None. The package can be inspected by a future production reviewer as a format example; it offers "
            "no coaching recommendation."
        ),
        "recommended_product_action": "do_not_implement",
        "safe_for_global_consideration": False,
        "required_future_validation": [
            "Collect real data under an approved, preregistered protocol before evaluating any performance claim.",
            "Replicate any real result in an independent session before considering validation.",
        ],
        "created_at": BUILT_AT,
        "apex_labs_source_commit": identity["git_commit"],
        "synthetic": True,
    }


def _validation(finding: dict[str, Any], evidence: dict[str, Any], run: dict[str, Any], identity: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": FINDING_VALIDATION,
        "validation_id": "synthetic-inference-demo-validation",
        "version": "1.0.0",
        "finding_id": finding["finding_id"],
        "finding_version": finding["version"],
        "finding_sha256": finding_hash(finding),
        "synthetic": True,
        "datasets": finding["dataset_references"],
        "frozen_protocol": {
            "freeze_id": finding["protocol_reference"]["freeze_id"],
            "freeze_sha256": finding["protocol_reference"]["freeze_sha256"],
            "protocol_id": finding["protocol_reference"]["experiment_id"],
            "protocol_version": finding["protocol_reference"]["version"],
        },
        "preprocessing": finding["preprocessing"],
        "analysis": finding["analysis"],
        "analysis_code_identity": identity,
        "computed_evidence": {
            "sample_counts": {
                "provenance": "computed",
                "values": finding["sample_counts"],
                "evidence_sha256": evidence["evidence_set_sha256"],
            },
            "sample_sufficiency": {
                "status": finding["sample_sufficiency"]["status"],
                "provenance": "computed",
                "criteria_applied": run["definition"]["sufficiency_rule"]["source_declarations"],
                "evidence_references": [run["run_sha256"]],
            },
            "exclusions": [
                {
                    "reason": f"{item['level']}/{item['stage']}: {item['detail']}",
                    "count": item["excluded"],
                    "provenance": "computed",
                    "evidence_sha256": evidence["evidence_set_sha256"],
                }
                for item in evidence["attrition"]
                if item["excluded"]
            ],
            "effect_estimate": finding["effect_estimate"],
            "uncertainty": finding["uncertainty"],
            "comparability": {
                "status": evidence["comparability"]["status"],
                "provenance": "computed",
                "criteria_applied": evidence["comparability"]["must_match_fields"],
                "violations": evidence["comparability"]["violations"],
                "evidence_references": [evidence["evidence_set_sha256"]],
            },
            "falsification_attempts": [
                {
                    "description": f"{item['test_id']} ({item['kind']}) on {item['comparison_id']}",
                    "outcome": (
                        "supports_hypothesis"
                        if item["outcome"] == "robust"
                        else "contradicts_hypothesis"
                        if item["outcome"] == "fragile"
                        else "not_applicable"
                    ),
                    "provenance": "computed",
                    "evidence_sha256": run["run_sha256"],
                }
                for item in run["sensitivity"]
            ],
        },
        "scope_assessment": {
            "scope": finding["scope"],
            "design_basis": (
                "One fabricated participant in one fabricated car on one fabricated layout. Nothing wider than "
                "the fabricated sessions themselves is supported."
            ),
            "evidence_references": [evidence["evidence_set_sha256"], run["run_sha256"]],
        },
        "population_validation_design": None,
        "gate_evaluations": {
            "structural": "passed",
            "reproducibility": "passed",
            "scientific": "unresolved",
        },
        "review": {
            "state": "pending",
            "reviewers": [],
            "reviewed_at": None,
            "notes": [
                "Scientific truth is unresolved by construction: the evidence is fabricated.",
                "Reproducibility passed because the evidence set and run were both independently recomputed.",
            ],
        },
        "product_review_state": "not_requested",
        "created_at": BUILT_AT,
    }


def verify_science_demo(root: Path, *, run_campaigns: bool = True) -> dict[str, Any]:
    """Reproduce the whole scientific path over fabricated evidence, twice."""
    root = root.resolve()
    campaigns = run_all_campaigns(root, project_root=root) if run_campaigns else {"ok": True, "campaigns": 0, "failed": []}
    if not campaigns["ok"]:
        raise IntegrityError(f"Synthetic campaigns did not match their known answers: {campaigns['failed']}")

    spec_path = root / "research" / "campaigns" / f"{DEMO_CAMPAIGN}.campaign.json"
    spec = read_json(spec_path)
    paths = campaign_paths(spec, root)
    with TemporaryDirectory(prefix="apex-labs-science-demo-") as directory:
        workspace = Path(directory)
        dataset_dirs = materialize(spec, workspace, root)

        first = workspace / "evidence-first"
        second = workspace / "evidence-second"
        evidence = build_evidence_set(
            paths["evidence_definition"], paths["segment"], paths["protocol_freeze"], paths["metric"],
            dataset_dirs, first, built_at=BUILT_AT, project_root=root,
        )
        build_evidence_set(
            paths["evidence_definition"], paths["segment"], paths["protocol_freeze"], paths["metric"],
            dataset_dirs, second, built_at=BUILT_AT, project_root=root,
        )
        if _file_inventory(first) != _file_inventory(second):
            raise IntegrityError("Synthetic evidence sets are not byte deterministic")
        verify_evidence_set(
            first, paths["evidence_definition"], paths["segment"], paths["protocol_freeze"],
            paths["metric"], dataset_dirs, project_root=root,
        )

        run_first = workspace / "run-first"
        run_second = workspace / "run-second"
        run = run_inferential_analysis(
            paths["analysis_definition"], first, paths["protocol_freeze"], run_first,
            run_id="science-demo-run", created_at=BUILT_AT, project_root=root,
        )
        run_inferential_analysis(
            paths["analysis_definition"], first, paths["protocol_freeze"], run_second,
            run_id="science-demo-run", created_at=BUILT_AT, project_root=root,
        )
        if _file_inventory(run_first) != _file_inventory(run_second):
            raise IntegrityError("Synthetic inferential runs are not byte deterministic")
        verification = verify_inferential_analysis_run(
            run_first, first, paths["protocol_freeze"], project_root=root
        )
        if run["scientific_eligibility"]["eligible"]:
            raise IntegrityError("Synthetic evidence acquired impermissible scientific eligibility")

        registry = workspace / "hypotheses"
        identity = evidence["code_identity"]
        register_hypothesis(_hypothesis(BUILT_AT), registry, recorded_at=BUILT_AT, code_identity=identity)
        hypothesis_id = "synthetic-corner-speed-demo"
        record_transition(
            registry, hypothesis_id, to_state="analysis_ready",
            rationale=(
                "The protocol, evidence-set definition, and analysis definition were all frozen before the run "
                "existed."
            ),
            recorded_at=BUILT_AT,
            bindings=plan_bindings(evidence, run["definition"], run["definition_sha256"]),
            code_identity=identity,
        )
        run_bindings = bindings_from_run(evidence, run, verified=verification["valid"])
        record_transition(
            registry, hypothesis_id, to_state="tested",
            rationale="The preregistered analysis ran once over the primary scope and was independently recomputed.",
            recorded_at=BUILT_AT, bindings=run_bindings, reviewer=dict(_PENDING_REVIEW),
            code_identity=identity,
        )
        record_transition(
            registry, hypothesis_id, to_state="replication_required",
            rationale=(
                "The frozen protocol requires replication in an independent session before validation, and the "
                "evidence is fabricated, so nothing may be promoted."
            ),
            recorded_at=BUILT_AT, bindings=run_bindings, reviewer=dict(_PENDING_REVIEW),
            code_identity=identity,
        )
        history = replay(registry, hypothesis_id)

        manifest = read_json(dataset_dirs[0] / "manifest.json")
        finding = _finding(evidence, run, identity, manifest)
        artifact = _validation(finding, evidence, run, identity)

        package_first = workspace / "package-first"
        package_second = workspace / "package-second"
        package = build_review_package(
            finding, artifact, first, run_first, history, [paths["metric"]], package_first,
            package_id="synthetic-inference-demo-package", created_at=BUILT_AT,
            recomputed_and_verified=verification["valid"], code_identity=identity,
        )
        build_review_package(
            finding, artifact, first, run_first, history, [paths["metric"]], package_second,
            package_id="synthetic-inference-demo-package", created_at=BUILT_AT,
            recomputed_and_verified=verification["valid"], code_identity=identity,
        )
        if _file_inventory(package_first) != _file_inventory(package_second):
            raise IntegrityError("Synthetic review packages are not byte deterministic")
        package_verification = verify_review_package(package_first, run_first, first)

    if package["finding"]["status"] != "inconclusive":
        raise IntegrityError("Synthetic demonstration finding acquired an impermissible status")
    if package["scientific_review"]["gate_scientific"] != "unresolved":
        raise IntegrityError("Synthetic demonstration must leave scientific truth unresolved")
    if package["product_recommendation"]["state"] != "do_not_implement":
        raise IntegrityError("Synthetic demonstration acquired an impermissible product recommendation")
    if package["product_recommendation"]["automatic_production_change"] is not False:
        raise IntegrityError("Apex Labs never automatically changes Apex Sim Coach")
    return {
        "ok": True,
        "classification": "synthetic_demo_only_not_racing_research",
        "campaigns": campaigns["campaigns"],
        "campaigns_ok": campaigns["ok"],
        "evidence_set_sha256": evidence["evidence_set_sha256"],
        "run_sha256": run["run_sha256"],
        "package_sha256": package["package_sha256"],
        "deterministic_evidence": True,
        "deterministic_inference": True,
        "deterministic_review_package": True,
        "analysis_state": run["analysis_state"],
        "effective_ceiling": run["interpretation"]["effective_ceiling"],
        "hypothesis_state": history["state"],
        "finding_status": package["finding"]["status"],
        "scientific_gate": package["scientific_review"]["gate_scientific"],
        "scientific_promotion_eligible": run["scientific_eligibility"]["eligible"],
        "product_recommendation": package["product_recommendation"]["state"],
        "automatic_production_change": package["product_recommendation"]["automatic_production_change"],
        "review_package_verified": package_verification["valid"],
    }
