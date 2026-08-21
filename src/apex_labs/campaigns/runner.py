"""Drive a synthetic campaign end to end and check it against its known answer.

The expectations a campaign declares were worked out by hand from the fabricated
numbers before the pipeline was run. A campaign that merely reproduced whatever
the implementation happened to output would test nothing, so every mismatch is
reported rather than absorbed.
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from apex_labs.analysis import run_inferential_analysis, verify_inferential_analysis_run
from apex_labs.campaigns.synthetic import campaign_paths, materialize, validate_campaign_spec
from apex_labs.errors import ApexLabsError, ContractValidationError, EvidenceError, IntegrityError
from apex_labs.evidence import build_evidence_set, verify_evidence_set
from apex_labs.io import read_json, write_json

BUILT_AT = "2026-08-20T00:00:00Z"
_REFUSALS = (EvidenceError, IntegrityError, ContractValidationError)


def _primary(run: dict[str, Any]) -> dict[str, Any]:
    return next((item for item in run["comparisons"] if item["role"] == "primary"), run["comparisons"][0])


def _observed(evidence: dict[str, Any], run: dict[str, Any], replication: dict[str, Any] | None) -> dict[str, Any]:
    primary = _primary(run)
    entries = {item["comparison_id"]: item for item in run["multiplicity"]["entries"]}
    entry = entries.get(primary["comparison_id"], {})
    raw_values = [item["raw_p_value"] for item in run["multiplicity"]["entries"] if item["raw_p_value"] is not None]
    adjusted_values = [
        item["adjusted_p_value"] for item in run["multiplicity"]["entries"] if item["adjusted_p_value"] is not None
    ]
    observed: dict[str, Any] = {
        "product_recommendation": "none",
        "evidence": {
            "included_units": evidence["counts"]["included_units"],
            "baseline_units": evidence["counts"]["baseline_units"],
            "intervention_units": evidence["counts"]["intervention_units"],
            "pairs": evidence["counts"]["pairs"],
            "unpaired_units": evidence["counts"]["unpaired_units"],
            "holdout_units": evidence["counts"]["holdout_units"],
            "resampling_clusters": evidence["counts"]["resampling_clusters"],
            "comparability": evidence["comparability"]["status"],
            "structural_ceiling": evidence["structural_interpretation_ceiling"],
        },
        "analysis_state": run["analysis_state"],
        "sufficiency": run["sufficiency"]["status"],
        "effective_ceiling": run["interpretation"]["effective_ceiling"],
        "confirmatory_permitted": run["sufficiency"]["confirmatory_permitted"],
        "condition_balanced": run["sufficiency"]["condition_balance"]["balanced"],
        "primary_method": primary["method"],
        "scientific_eligibility": run["scientific_eligibility"]["eligible"],
        "unmet_requirement_count": len(run["sufficiency"]["unmet_requirements"]),
        "zero_valued_units": sum(1 for unit in evidence["units"] if unit["value"] == 0.0),
        "missing_required_channel_records": sum(
            item["excluded"] for item in evidence["attrition"] if item["stage"] == "missing_required_channel"
        ),
        "minimum_raw_p_value": min(raw_values) if raw_values else None,
        "minimum_adjusted_p_value": min(adjusted_values) if adjusted_values else None,
        "any_rejected_at_alpha": any(item["rejected_at_alpha"] for item in run["multiplicity"]["entries"]),
        "primary": {
            "estimate": None if primary["effect"] is None else primary["effect"]["estimate"],
            "secondary_estimate": None if primary["effect"] is None else primary["effect"]["secondary_estimate"],
            "raw_p_value": primary["statistical_evidence"]["raw_p_value"],
            "adjusted_p_value": entry.get("adjusted_p_value"),
            "rejected_at_alpha": entry.get("rejected_at_alpha"),
            "estimate_exceeds_threshold": primary["practical"]["estimate_exceeds_threshold"],
            "direction_matches_hypothesis": primary["practical"]["direction_matches_hypothesis"],
            "interval_excludes_no_effect": primary["practical"]["interval_excludes_no_effect"],
            "interval": primary["uncertainty"]["interval"],
        },
        "sensitivity": {
            item["test_id"]: item["outcome"]
            for item in run["sensitivity"]
            if item["comparison_id"] == primary["comparison_id"]
        },
    }
    if replication is not None:
        replication_primary = _primary(replication)
        replication_entry = next(
            (
                item
                for item in replication["multiplicity"]["entries"]
                if item["comparison_id"] == replication_primary["comparison_id"]
            ),
            {},
        )
        observed["replication"] = {
            "analysis_state": replication["analysis_state"],
            "estimate": None if replication_primary["effect"] is None else replication_primary["effect"]["estimate"],
            "estimate_exceeds_threshold": replication_primary["practical"]["estimate_exceeds_threshold"],
            "raw_p_value": replication_primary["statistical_evidence"]["raw_p_value"],
            "adjusted_p_value": replication_entry.get("adjusted_p_value"),
        }
    return observed


def _compare(expected: Any, observed: Any, path: str, mismatches: list[str]) -> None:
    if isinstance(expected, dict):
        for key, value in expected.items():
            if not isinstance(observed, dict) or key not in observed:
                mismatches.append(f"{path}.{key}: expected {value!r} but nothing was observed")
                continue
            _compare(value, observed[key], f"{path}.{key}", mismatches)
        return
    if expected != observed:
        mismatches.append(f"{path}: expected {expected!r}, observed {observed!r}")


def check_expectations(spec: dict[str, Any], observed: dict[str, Any]) -> list[str]:
    """Compare the hand-computed known answers with what the pipeline produced."""
    expectations = spec["expectations"]
    mismatches: list[str] = []
    for key, expected in expectations.items():
        if key in {"notes", "refuses_ceiling", "outcome_reason_contains"}:
            continue
        if key == "sensitivity_all_robust":
            fragile = sorted(name for name, outcome in observed["sensitivity"].items() if outcome != "robust")
            if expected and fragile:
                mismatches.append(f"sensitivity: expected every check robust, but {fragile} were not")
            continue
        if key == "fragile_tests":
            for test_id in expected:
                outcome = observed["sensitivity"].get(test_id)
                if outcome != "fragile":
                    mismatches.append(f"sensitivity.{test_id}: expected 'fragile', observed {outcome!r}")
            continue
        if key == "unmet_requirement_count_at_least":
            if observed["unmet_requirement_count"] < expected:
                mismatches.append(
                    f"unmet_requirement_count: expected at least {expected}, observed {observed['unmet_requirement_count']}"
                )
            continue
        if key not in observed:
            mismatches.append(f"{key}: expected {expected!r} but nothing was observed")
            continue
        _compare(expected, observed[key], key, mismatches)
    return mismatches


def _refused_ceiling_probe(
    analysis_path: Path,
    evidence_dir: Path,
    protocol_freeze: Path,
    workspace: Path,
    ceiling: str,
    project_root: Path,
) -> str:
    """Ask for a stronger interpretation than the design permits and record the refusal."""
    definition = read_json(analysis_path)
    definition["interpretation_ceiling"] = ceiling
    probe_path = workspace / "over-strong-definition.json"
    write_json(probe_path, definition)
    try:
        run_inferential_analysis(
            probe_path,
            evidence_dir,
            protocol_freeze,
            workspace / "over-strong-run",
            run_id="ceiling-probe",
            created_at=BUILT_AT,
            project_root=project_root,
        )
    except ApexLabsError as exc:
        return str(exc)
    raise AssertionError(
        f"A {ceiling!r} interpretation was accepted although the design does not permit it"
    )


def run_campaign(
    spec_path: Path,
    workspace: Path,
    root: Path,
    *,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Materialize, build, analyse, verify, and check one synthetic campaign."""
    project_root = project_root or root
    spec = validate_campaign_spec(read_json(spec_path))
    paths = campaign_paths(spec, root)
    dataset_dirs = materialize(spec, workspace, root)
    evidence_dir = workspace / "evidence"

    def build() -> dict[str, Any]:
        return build_evidence_set(
            paths["evidence_definition"],
            paths["segment"],
            paths["protocol_freeze"],
            paths["metric"],
            dataset_dirs,
            evidence_dir,
            built_at=BUILT_AT,
            project_root=project_root,
        )

    if spec["outcome"] == "evidence_refused":
        expected_reason = spec["expectations"].get("outcome_reason_contains", "")
        try:
            build()
        except _REFUSALS as exc:
            reason = str(exc)
            mismatches = (
                []
                if expected_reason in reason
                else [f"refusal reason: expected text {expected_reason!r} in {reason!r}"]
            )
            if spec["expectations"].get("product_recommendation") != "none":
                mismatches.append("product_recommendation: every synthetic campaign must expect 'none'")
            return {
                "campaign_id": spec["campaign_id"],
                "outcome": "evidence_refused",
                "reason": reason,
                "mismatches": mismatches,
                "ok": not mismatches,
                "classification": "synthetic_demo_only_not_racing_research",
                "scientific_promotion_eligible": False,
                "product_recommendation": "none",
            }
        raise AssertionError(
            f"Campaign {spec['campaign_id']} expected the evidence build to be refused but it succeeded"
        )

    evidence = build()
    verify_evidence_set(
        evidence_dir,
        paths["evidence_definition"],
        paths["segment"],
        paths["protocol_freeze"],
        paths["metric"],
        dataset_dirs,
        project_root=project_root,
    )
    run = run_inferential_analysis(
        paths["analysis_definition"],
        evidence_dir,
        paths["protocol_freeze"],
        workspace / "run",
        run_id=f"{spec['campaign_id']}-run",
        created_at=BUILT_AT,
        project_root=project_root,
    )
    verify_inferential_analysis_run(
        workspace / "run", evidence_dir, paths["protocol_freeze"], project_root=project_root
    )

    replication = None
    if "replication_analysis_definition" in spec:
        replication_path = root / "research" / "analyses" / f"{spec['replication_analysis_definition']}.json"
        replication = run_inferential_analysis(
            replication_path,
            evidence_dir,
            paths["protocol_freeze"],
            workspace / "replication-run",
            run_id=f"{spec['campaign_id']}-replication",
            created_at=BUILT_AT,
            project_root=project_root,
        )
        verify_inferential_analysis_run(
            workspace / "replication-run", evidence_dir, paths["protocol_freeze"], project_root=project_root
        )

    refusal = None
    if "refuses_ceiling" in spec["expectations"]:
        refusal = _refused_ceiling_probe(
            paths["analysis_definition"],
            evidence_dir,
            paths["protocol_freeze"],
            workspace,
            spec["expectations"]["refuses_ceiling"],
            project_root,
        )

    observed = _observed(evidence, run, replication)
    mismatches = check_expectations(spec, observed)
    return {
        "campaign_id": spec["campaign_id"],
        "outcome": "analysed",
        "evidence_set_sha256": evidence["evidence_set_sha256"],
        "run_sha256": run["run_sha256"],
        "replication_run_sha256": None if replication is None else replication["run_sha256"],
        "refused_ceiling_reason": refusal,
        "observed": observed,
        "mismatches": mismatches,
        "ok": not mismatches,
        "classification": "synthetic_demo_only_not_racing_research",
        "scientific_promotion_eligible": False,
        "product_recommendation": "none",
    }


def campaign_specs(root: Path) -> list[Path]:
    return sorted((root / "research" / "campaigns").glob("*.campaign.json"))


def run_all_campaigns(root: Path, *, project_root: Path | None = None) -> dict[str, Any]:
    """Run every checked-in campaign in a throwaway workspace."""
    results = []
    for spec_path in campaign_specs(root):
        with TemporaryDirectory(prefix="apex-labs-campaign-") as directory:
            results.append(run_campaign(spec_path, Path(directory), root, project_root=project_root))
    failures = [item for item in results if not item["ok"]]
    return {
        "ok": not failures,
        "campaigns": len(results),
        "failed": [item["campaign_id"] for item in failures],
        "mismatches": {item["campaign_id"]: item["mismatches"] for item in failures},
        "results": [
            {
                "campaign_id": item["campaign_id"],
                "outcome": item["outcome"],
                "ok": item["ok"],
                "product_recommendation": item["product_recommendation"],
            }
            for item in results
        ],
        "classification": "synthetic_demo_only_not_racing_research",
        "scientific_promotion_eligible": False,
        "product_recommendation": "none",
    }
