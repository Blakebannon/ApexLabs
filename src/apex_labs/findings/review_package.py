"""Deterministic evidence dossier assembled for human scientific review.

The package restates the result plainly, including the parts that weaken it. It
carries no authority: Apex Labs never edits Apex Sim Coach, never changes a
coaching policy or threshold, and never opens a production change. The product
recommendation state is deliberately conservative and is derived from the
evidence rather than written by hand.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from apex_labs.atomic import atomic_output_directory
from apex_labs.errors import ExportError, IntegrityError, LifecycleError
from apex_labs.findings.validation_artifact import validate_finding_with_artifact
from apex_labs.io import canonical_json_bytes, read_json, write_json
from apex_labs.provenance import apex_labs_code_identity, sha256_bytes
from apex_labs.schemas import (
    validate_evidence_set,
    validate_finding_review_package,
    validate_inferential_analysis_run,
    validate_metric_definition,
)
from apex_labs.schemas.versions import FINDING_REVIEW_PACKAGE, REVIEW_PACKAGE_METHOD_ID

PACKAGE_FILE = "review-package.json"
REPORT_FILE = "review-report.md"


def _canonical_sha(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def _package_hash(package: dict[str, Any]) -> str:
    return _canonical_sha({key: value for key, value in package.items() if key != "package_sha256"})


def _primary(run: dict[str, Any]) -> dict[str, Any]:
    return next((item for item in run["comparisons"] if item["role"] == "primary"), run["comparisons"][0])


def _unique(items: list[str]) -> list[str]:
    """Preserve first-seen order while dropping limitations repeated by two sources."""
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def product_recommendation(
    finding: dict[str, Any],
    artifact: dict[str, Any],
    run: dict[str, Any],
    hypothesis_state: str,
) -> dict[str, Any]:
    """Derive a conservative production-recommendation state from the evidence.

    Nothing here can produce a production change. The strongest state available
    is a candidate for engineering review, and it requires a validated finding,
    passed reproducibility and scientific gates, an approved review, and a
    replication requirement that has actually been discharged.
    """
    gates = artifact["gate_evaluations"]
    review_state = artifact["review"]["state"]
    replication = run["definition"]["replication_policy"]["state"]
    if finding["synthetic"]:
        return {
            "state": "do_not_implement",
            "rationale": (
                "Every value behind this package is fabricated. Synthetic evidence demonstrates mechanics only "
                "and is permanently ineligible for scientific or product promotion."
            ),
            "automatic_production_change": False,
        }
    if (
        finding["status"] == "validated"
        and gates["scientific"] == "passed"
        and gates["reproducibility"] == "passed"
        and review_state == "approved"
        and replication != "required_before_validation"
    ):
        return {
            "state": "engineering_review_candidate",
            "rationale": (
                "A validated finding with passed reproducibility and scientific gates, an approved scientific "
                "review, and no outstanding replication requirement. Production engineering decides whether "
                "anything follows; Apex Labs does not."
            ),
            "automatic_production_change": False,
        }
    if replication == "required_before_validation" and run["analysis_state"] == "computed":
        return {
            "state": "replication_required",
            "rationale": (
                "A result exists and the frozen protocol requires independent replication before validation. "
                "Nothing may be acted on until that replication is collected and analysed."
            ),
            "automatic_production_change": False,
        }
    if finding["status"] == "provisional" and hypothesis_state == "supported_provisionally":
        return {
            "state": "investigate",
            "rationale": (
                "Useful evidence exists but a declared requirement remains outstanding. The appropriate next step "
                "is further research, not a product change."
            ),
            "automatic_production_change": False,
        }
    return {
        "state": "none",
        "rationale": (
            "The evidence does not support any production consideration. Recording that plainly is the point of "
            "this package."
        ),
        "automatic_production_change": False,
    }


def _format_number(value: Any) -> str:
    if value is None:
        return "not available"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _format_interval(uncertainty: dict[str, Any]) -> str:
    if not uncertainty.get("usable"):
        return f"not available - {uncertainty.get('unusable_reason') or 'no interval was produced'}"
    lower, upper = uncertainty["interval"]
    coverage = uncertainty["coverage_level"]
    return (
        f"{coverage:.0%} deterministic cluster bootstrap over {uncertainty['clusters']} "
        f"{uncertainty['resampling_unit']}-level cluster(s): [{_format_number(lower)}, {_format_number(upper)}]"
    )


def render_report(package: dict[str, Any], run: dict[str, Any], evidence: dict[str, Any]) -> str:
    """Owner-facing report that states the result without hiding weak evidence."""
    primary = _primary(run)
    effect = primary["effect"]
    counts = evidence["counts"]
    confounds = evidence["confounds"]
    lines: list[str] = []
    lines.append(f"# {package['finding']['title']}")
    lines.append("")
    lines.append("**Finding**")
    lines.append("")
    if effect is None:
        lines.append(
            f"The primary comparison `{primary['comparison_id']}` could not be computed from the available evidence."
        )
    else:
        direction = "higher" if effect["estimate"] > 0 else "lower" if effect["estimate"] < 0 else "unchanged"
        lines.append(
            f"Across {effect['n']} comparable {evidence['units_declaration']['experimental_unit']}-level pair(s), "
            f"the intervention arm was {direction} by a {effect['effect_size'].replace('_', ' ')} of "
            f"{_format_number(effect['estimate'])} {primary['unit_of_measure']}."
        )
    lines.append("")
    lines.append(f"**Status**: {package['finding']['status'].upper()}")
    lines.append("")
    lines.append("**Scientific question**")
    lines.append("")
    lines.append(run["definition"]["scientific_question"])
    lines.append("")
    lines.append("**Evidence**")
    lines.append("")
    lines.append(
        f"- {counts['included_units']} included unit(s) from {counts['blocks']} block(s) across "
        f"{counts['sessions']} session(s) and {counts['participants']} participant(s)"
    )
    lines.append(f"- {counts['pairs']} pair(s), {counts['unpaired_units']} unpaired unit(s)")
    lines.append(
        f"- experimental unit: {evidence['units_declaration']['experimental_unit']}; "
        f"resampling unit: {evidence['units_declaration']['resampling_unit']}"
    )
    lines.append(f"- comparability: {evidence['comparability']['status']}")
    lines.append(f"- protocol: {package['protocol']['protocol_id']} v{package['protocol']['protocol_version']}")
    lines.append("")
    lines.append("**Attrition**")
    lines.append("")
    for entry in evidence["attrition"]:
        if entry["excluded"]:
            lines.append(
                f"- {entry['level']}/{entry['stage']}: {entry['excluded']} removed "
                f"({entry['disposition']}) - {entry['detail']}"
            )
    if not any(entry["excluded"] for entry in evidence["attrition"]):
        lines.append("- No evidence was removed at any declared stage.")
    lines.append("")
    lines.append("**Effect**")
    lines.append("")
    if effect is None:
        lines.append("- No effect estimate is available.")
    else:
        lines.append(
            f"- {_format_number(effect['estimate'])} {primary['unit_of_measure']} "
            f"({effect['effect_size'].replace('_', ' ')})"
        )
        lines.append(
            f"- practical threshold {_format_number(primary['practical']['threshold_magnitude'])} "
            f"{primary['practical']['threshold_unit']} "
            f"({primary['practical']['threshold_source']}); "
            f"exceeded: {primary['practical']['estimate_exceeds_threshold']}"
        )
    lines.append("")
    lines.append("**Uncertainty**")
    lines.append("")
    lines.append(f"- {_format_interval(primary['uncertainty'])}")
    lines.append(f"- {primary['uncertainty']['semantics']}")
    lines.append("")
    lines.append("**Statistical evidence**")
    lines.append("")
    lines.append(
        f"- raw: {_format_number(package['statistical_evidence']['raw'])}; "
        f"adjusted ({package['statistical_evidence']['correction']}): "
        f"{_format_number(package['statistical_evidence']['adjusted'])}"
    )
    lines.append(f"- {package['statistical_evidence']['interpretation']}")
    lines.append("")
    lines.append("**Sample sufficiency**")
    lines.append("")
    lines.append(f"- {run['sufficiency']['status']} (source: {run['sufficiency']['source']})")
    for item in run["sufficiency"]["unmet_requirements"]:
        lines.append(f"- unmet: {item}")
    lines.append("")
    lines.append("**Confounds**")
    lines.append("")
    for item in confounds["controlled"]:
        lines.append(f"- controlled: {item}")
    for item in confounds["measured_covariates"]:
        lines.append(f"- measured: {item}")
    for item in confounds["unavailable"]:
        lines.append(f"- unavailable: {item}")
    lines.append("")
    lines.append("**Sensitivity and falsification**")
    lines.append("")
    for item in run["sensitivity"]:
        if item["comparison_id"] == primary["comparison_id"]:
            lines.append(f"- {item['test_id']} ({item['kind']}): {item['outcome']}")
    lines.append("")
    lines.append("**Replication**")
    lines.append("")
    replication = package["replication"]
    lines.append(
        f"- {replication['state']}; required scope: {replication['required_scope']}; "
        f"achieved scope: {replication['achieved_scope']}"
    )
    lines.append(
        f"- reserved replication evidence available: {replication['holdout_available']}; "
        f"tested: {replication['holdout_tested']}"
    )
    lines.append("")
    lines.append("**Interpretation**")
    lines.append("")
    lines.append(f"- ceiling: {package['interpretation_ceiling']}")
    lines.append(f"- {run['interpretation']['rationale']}")
    lines.append("")
    lines.append("**Limitations**")
    lines.append("")
    for item in package["limitations"]:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("**Scientific review**")
    lines.append("")
    review = package["scientific_review"]
    lines.append(
        f"- state: {review['state']}; structural: {review['gate_structural']}; "
        f"reproducibility: {review['gate_reproducibility']}; scientific: {review['gate_scientific']}"
    )
    lines.append(f"- hypothesis state: {package['hypothesis']['state']}")
    lines.append("")
    lines.append("**Production recommendation**")
    lines.append("")
    lines.append(f"- {package['product_recommendation']['state']}")
    lines.append(f"- {package['product_recommendation']['rationale']}")
    lines.append("")
    lines.append(
        "Apex Labs never edits Apex Sim Coach, changes a coaching policy, threshold, or configuration, opens a "
        "production change, or deploys anything. This package is evidence for human consideration only."
    )
    lines.append("")
    return "\n".join(lines)


def build_review_package(
    finding_value: dict[str, Any],
    artifact_value: dict[str, Any],
    evidence_path: Path,
    run_path: Path,
    history: dict[str, Any],
    metric_paths: Iterable[Path],
    output_dir: Path,
    *,
    package_id: str,
    created_at: str,
    recomputed_and_verified: bool,
    replication_run: dict[str, Any] | None = None,
    project_root: Path | None = None,
    code_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    finding, artifact = validate_finding_with_artifact(finding_value, artifact_value)
    evidence = validate_evidence_set(
        read_json(evidence_path / "evidence-set.json" if evidence_path.is_dir() else evidence_path)
    )
    run = validate_inferential_analysis_run(
        read_json(
            run_path / "inferential-analysis-run.json" if run_path.is_dir() else run_path
        )
    )
    if run["evidence_set"]["evidence_set_sha256"] != evidence["evidence_set_sha256"]:
        raise IntegrityError("The analysis run and evidence set in this package do not refer to each other")
    if finding["synthetic"] != run["synthetic"] or finding["synthetic"] != evidence["synthetic"]:
        raise IntegrityError("Finding, evidence, and run disagree about synthetic classification")
    hypothesis = history["hypothesis"]
    if hypothesis["synthetic"] != finding["synthetic"]:
        raise IntegrityError("Hypothesis and finding disagree about synthetic classification")
    head = history["transitions"][-1]
    bound_run = head["bindings"]["analysis_run"]
    if bound_run is None or bound_run["run_sha256"] != run["run_sha256"]:
        raise LifecycleError(
            "The hypothesis head transition is not bound to this analysis run; a review package never invents that link"
        )

    metrics = []
    for path in metric_paths:
        metric = validate_metric_definition(read_json(path))
        metrics.append(
            {"metric_id": metric["metric_id"], "version": metric["version"], "sha256": _canonical_sha(metric)}
        )
    metrics.sort(key=lambda item: (item["metric_id"], item["version"]))
    if not metrics:
        raise IntegrityError("A review package must bind at least one metric definition")

    primary = _primary(run)
    entry = next(
        (item for item in run["multiplicity"]["entries"] if item["comparison_id"] == primary["comparison_id"]),
        {"raw_p_value": None, "adjusted_p_value": None},
    )
    replication_policy = run["definition"]["replication_policy"]
    holdout_available = evidence["counts"]["holdout_units"] > 0
    holdout_tested = replication_run is not None and replication_run["evidence_set"]["scope"] == "holdout"
    achieved = (
        replication_policy["required_scope"]
        if holdout_tested and replication_run["analysis_state"] == "computed"
        else "none"
    )
    identity = code_identity or apex_labs_code_identity(project_root)
    hypothesis_state = history["state"]

    package: dict[str, Any] = {
        "schema_version": FINDING_REVIEW_PACKAGE,
        "package_id": package_id,
        "version": finding["version"],
        "created_at": created_at,
        "synthetic": finding["synthetic"],
        "classification": "evidence_for_human_review_not_a_production_change",
        "method_id": REVIEW_PACKAGE_METHOD_ID,
        "package_sha256": "0" * 64,
        "finding": {
            "finding_id": finding["finding_id"],
            "version": finding["version"],
            "finding_sha256": artifact["finding_sha256"],
            "status": finding["status"],
            "title": finding["title"],
            "research_question": finding["research_question"],
            "scope": finding["scope"],
            "evidence_classification": finding["evidence_classification"],
            "validation_id": artifact["validation_id"],
            "validation_version": artifact["version"],
        },
        "hypothesis": {
            "hypothesis_id": hypothesis["hypothesis_id"],
            "version": hypothesis["version"],
            "hypothesis_sha256": hypothesis["hypothesis_sha256"],
            "state": hypothesis_state,
            "transition_count": len(history["transitions"]),
            "head_transition_sha256": history["head_transition_sha256"],
            "generation_source": hypothesis["generation"]["source"],
        },
        "protocol": {
            "freeze_id": evidence["protocol"]["freeze_id"],
            "freeze_sha256": evidence["protocol"]["freeze_sha256"],
            "protocol_id": evidence["protocol"]["protocol_id"],
            "protocol_version": evidence["protocol"]["protocol_version"],
            "protocol_sha256": evidence["protocol"]["protocol_sha256"],
            "scientific_question": run["definition"]["scientific_question"],
        },
        "evidence": {
            "evidence_set_id": evidence["evidence_set_id"],
            "version": evidence["version"],
            "evidence_set_sha256": evidence["evidence_set_sha256"],
            "definition_sha256": evidence["definition_sha256"],
            "segment_definition_id": evidence["segment_definition"]["segment_definition_id"],
            "segment_definition_sha256": evidence["segment_definition_sha256"],
            "datasets": [
                {
                    "dataset_id": dataset["dataset_id"],
                    "fingerprint": dataset["fingerprint"],
                    "synthetic": dataset["synthetic"],
                }
                for dataset in evidence["datasets"]
            ],
            "comparability_status": evidence["comparability"]["status"],
            "comparability_violations": evidence["comparability"]["violations"],
            "counts": evidence["counts"],
            "experimental_unit": evidence["units_declaration"]["experimental_unit"],
            "resampling_unit": evidence["units_declaration"]["resampling_unit"],
        },
        "analysis_definition": {
            "analysis_id": run["definition"]["analysis_id"],
            "version": run["definition"]["version"],
            "definition_sha256": run["definition_sha256"],
            "classification": run["definition"]["classification"],
        },
        "analysis_run": {
            "run_id": run["run_id"],
            "run_sha256": run["run_sha256"],
            "analysis_state": run["analysis_state"],
            "recomputed_and_verified": recomputed_and_verified,
            "scope": run["evidence_set"]["scope"],
        },
        "metric_definitions": metrics,
        "effect": primary["effect"],
        "uncertainty": primary["uncertainty"],
        "practical_threshold": primary["practical"],
        "statistical_evidence": {
            "raw": entry["raw_p_value"],
            "adjusted": entry["adjusted_p_value"],
            "correction": run["multiplicity"]["correction"],
            "family_id": run["multiplicity"]["family_id"],
            "interpretation": run["multiplicity"]["interpretation"],
        },
        "sufficiency": run["sufficiency"],
        "attrition": evidence["attrition"],
        "confounds": evidence["confounds"],
        "sensitivity": run["sensitivity"],
        "replication": {
            "state": replication_policy["state"],
            "required_scope": replication_policy["required_scope"],
            "achieved_scope": achieved,
            "holdout_available": holdout_available,
            "holdout_tested": holdout_tested,
        },
        "interpretation_ceiling": run["interpretation"]["effective_ceiling"],
        "limitations": _unique(run["limitations"] + finding["limitations"]),
        "scientific_review": {
            "state": artifact["review"]["state"],
            "gate_structural": artifact["gate_evaluations"]["structural"],
            "gate_reproducibility": artifact["gate_evaluations"]["reproducibility"],
            "gate_scientific": artifact["gate_evaluations"]["scientific"],
        },
        "product_review": artifact["product_review_state"],
        "product_recommendation": product_recommendation(finding, artifact, run, hypothesis_state),
        "code_identity": identity,
        "report_sha256": "0" * 64,
    }
    report = render_report(package, run, evidence)
    package["report_sha256"] = sha256_bytes(report.encode("utf-8"))
    package["package_sha256"] = _package_hash(package)
    validate_finding_review_package(package)
    with atomic_output_directory(output_dir, operation="review-package", error_type=ExportError) as staged:
        write_json(staged / PACKAGE_FILE, package)
        (staged / REPORT_FILE).write_bytes(report.encode("utf-8"))
    return package


def verify_review_package(
    package_dir: Path, run_path: Path, evidence_path: Path
) -> dict[str, Any]:
    """Re-verify the package hashes and re-render the report from its content."""
    package = validate_finding_review_package(read_json(package_dir / PACKAGE_FILE))
    if package["package_sha256"] != _package_hash(package):
        raise IntegrityError("Review package hash does not match its content")
    evidence = validate_evidence_set(
        read_json(evidence_path / "evidence-set.json" if evidence_path.is_dir() else evidence_path)
    )
    run = validate_inferential_analysis_run(
        read_json(run_path / "inferential-analysis-run.json" if run_path.is_dir() else run_path)
    )
    if package["evidence"]["evidence_set_sha256"] != evidence["evidence_set_sha256"]:
        raise IntegrityError("Review package is bound to a different evidence set")
    if package["analysis_run"]["run_sha256"] != run["run_sha256"]:
        raise IntegrityError("Review package is bound to a different analysis run")
    stored = (package_dir / REPORT_FILE).read_bytes()
    if sha256_bytes(stored) != package["report_sha256"]:
        raise IntegrityError("Review report content does not match its recorded hash")
    rendered = render_report(package, run, evidence).encode("utf-8")
    if rendered != stored:
        raise IntegrityError("Review report is not reproducible from the package, run, and evidence")
    return {
        "valid": True,
        "package_id": package["package_id"],
        "package_sha256": package["package_sha256"],
        "finding_status": package["finding"]["status"],
        "hypothesis_state": package["hypothesis"]["state"],
        "interpretation_ceiling": package["interpretation_ceiling"],
        "product_recommendation": package["product_recommendation"]["state"],
        "automatic_production_change": package["product_recommendation"]["automatic_production_change"],
    }
