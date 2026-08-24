"""Apex Labs command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from apex_labs import __version__
from apex_labs.analysis import (
    run_analysis,
    run_inferential_analysis,
    verify_analysis_run,
    verify_inferential_analysis_run,
)
from apex_labs.campaigns import (
    campaign_specs,
    regenerate_reference_artifacts,
    run_all_campaigns,
    run_campaign,
)
from apex_labs.capability import (
    build_capability_map,
    load_variable_inventory,
    rehearsal_readiness,
    validate_variable_inventory,
)
from apex_labs.corpus.admission import admit_corpus, coaching_binding_since
from apex_labs.demo import verify_synthetic_demo
from apex_labs.evidence import build_evidence_set, verify_evidence_set
from apex_labs.findings.review_package import build_review_package, verify_review_package
from apex_labs.hypotheses import (
    bindings_from_run,
    plan_bindings,
    record_transition,
    register_hypothesis,
    replay,
    verify_registry,
)
from apex_labs.science_demo import verify_science_demo
from apex_labs.errors import ApexLabsError, ContractValidationError
from apex_labs.experiments import freeze_protocol, verify_protocol_freeze
from apex_labs.exports import generate_product_export, verify_product_export
from apex_labs.findings import validate_finding_with_artifact
from apex_labs.ingestion import (
    ingest_apex_session_bundle,
    ingest_dataset,
    inspect_apex_session_bundle,
    inspect_dataset,
    validate_apex_session_bundle,
    ingest_research_bundle,
    inspect_research_bundle,
    validate_research_bundle,
)
from apex_labs.io import canonical_json_bytes, read_json, read_json_lines
from apex_labs.provenance import sha256_bytes
from apex_labs.repository_guard import run_repository_guard
from apex_labs.schemas import (
    validate_analysis_definition,
    validate_analysis_run,
    validate_evidence_set,
    validate_evidence_set_definition,
    validate_finding_review_package,
    validate_hypothesis,
    validate_hypothesis_transition,
    validate_inferential_analysis_definition,
    validate_inferential_analysis_run,
    validate_segment_definition,
    validate_experiment,
    validate_finding,
    validate_finding_validation,
    validate_protocol_amendment,
    validate_protocol_freeze,
    validate_apex_session_manifest,
    validate_collection_record,
    validate_exploratory_intake,
    validate_product_annotations,
    validate_research_export_manifest,
    validate_research_recorder_manifest,
    validate_adapter_conformance,
)
from apex_labs.schemas.validation import VALIDATORS

ALL_VALIDATORS = {
    **VALIDATORS,
    "finding-validation": validate_finding_validation,
    "protocol-amendment": validate_protocol_amendment,
    "protocol-freeze": validate_protocol_freeze,
    "apex-session-manifest": validate_apex_session_manifest,
    "collection-record": validate_collection_record,
    "exploratory-intake": validate_exploratory_intake,
    "product-annotations": validate_product_annotations,
    "research-export-manifest": validate_research_export_manifest,
    "research-recorder-manifest": validate_research_recorder_manifest,
    "adapter-conformance": validate_adapter_conformance,
    "analysis-definition": validate_analysis_definition,
    "analysis-run": validate_analysis_run,
    "segment-definition": validate_segment_definition,
    "evidence-set-definition": validate_evidence_set_definition,
    "evidence-set": validate_evidence_set,
    "inferential-analysis-definition": validate_inferential_analysis_definition,
    "inferential-analysis-run": validate_inferential_analysis_run,
    "hypothesis": validate_hypothesis,
    "hypothesis-transition": validate_hypothesis_transition,
    "finding-review-package": validate_finding_review_package,
    "iracing-variable-inventory": validate_variable_inventory,
}


def _print_json(value: Any) -> None:
    sys.stdout.buffer.write(canonical_json_bytes(value))


def _validate_file(kind: str, path: Path) -> dict[str, Any]:
    validator = ALL_VALIDATORS[kind]
    validator(read_json(path))
    return {"valid": True, "kind": kind, "path": str(path)}


def _validate_collection(path: Path, validator: Any, kind: str) -> dict[str, Any]:
    files = [path] if path.is_file() else sorted(path.rglob("*.json"))
    if not files:
        raise ContractValidationError(f"No JSON files found at {path}")
    for item in files:
        validator(read_json(item))
    return {"valid": True, "kind": kind, "files_validated": len(files), "path": str(path)}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="apex-labs",
        description="Reproducible telemetry-research infrastructure; no automatic production promotion.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    ingest = commands.add_parser("ingest", help="Validate, fingerprint, and normalize a declared source dataset")
    ingest.add_argument("manifest", type=Path)
    ingest.add_argument("--output", "-o", type=Path, required=True)

    inspect = commands.add_parser("inspect", help="Verify and summarize a source or normalized dataset")
    inspect.add_argument("manifest", type=Path)

    validate = commands.add_parser("validate", help="Validate one versioned JSON contract")
    validate.add_argument("kind", choices=sorted(ALL_VALIDATORS))
    validate.add_argument("path", type=Path)

    experiment = commands.add_parser("experiment", help="Work with experiment protocols")
    experiment_commands = experiment.add_subparsers(dest="experiment_command", required=True)
    experiment_validate = experiment_commands.add_parser("validate", help="Validate an experiment definition")
    experiment_validate.add_argument("path", type=Path)
    experiment_freeze = experiment_commands.add_parser(
        "freeze", help="Create a new immutable preregistration snapshot"
    )
    experiment_freeze.add_argument("path", type=Path)
    experiment_freeze.add_argument("--registry", type=Path, required=True)
    experiment_freeze.add_argument("--frozen-at", required=True)
    experiment_freeze.add_argument(
        "--strategy",
        choices=["randomized", "counterbalanced", "fixed", "not_applicable"],
        required=True,
    )
    experiment_freeze.add_argument("--method", required=True)
    experiment_freeze.add_argument("--seed", type=int)
    experiment_freeze.add_argument("--schedule-id", required=True)
    experiment_freeze.add_argument(
        "--schedule", type=Path, help="JSON array containing the predetermined schedule"
    )
    experiment_verify = experiment_commands.add_parser(
        "verify-freeze", help="Verify a frozen protocol and its canonical hashes"
    )
    experiment_verify.add_argument("path", type=Path)

    findings = commands.add_parser("findings", help="Work with finding records")
    findings_commands = findings.add_subparsers(dest="findings_command", required=True)
    findings_validate = findings_commands.add_parser("validate", help="Validate one finding or a directory")
    findings_validate.add_argument("path", type=Path)
    findings_verify = findings_commands.add_parser(
        "verify", help="Verify a finding against its independent validation artifact"
    )
    findings_verify.add_argument("finding", type=Path)
    findings_verify.add_argument("validation", type=Path)

    records = commands.add_parser("validate-records", help="Validate every record in normalized JSONL")
    records.add_argument("path", type=Path)

    export = commands.add_parser("export-product-findings", help="Generate a deterministic, review-gated handoff")
    export.add_argument("definition", type=Path)
    export.add_argument("--output", "-o", type=Path, required=True)
    export.add_argument("--root", type=Path, default=Path.cwd())

    verify = commands.add_parser("verify-export", help="Verify all files and hashes in a product export")
    verify.add_argument("directory", type=Path)
    guard = commands.add_parser(
        "repository-guard", help="Heuristically inspect Git-visible content for prohibited data and secrets"
    )
    guard.add_argument("--root", type=Path, default=Path.cwd())
    demo = commands.add_parser(
        "verify-synthetic-demo",
        help="Reproduce the synthetic mechanics path twice; never scientific evidence",
    )
    demo.add_argument("--root", type=Path, default=Path.cwd())

    apex_session = commands.add_parser(
        "apex-session", help="Securely inspect, validate, or normalize an apex-session-export/1.0.0 bundle"
    )
    apex_commands = apex_session.add_subparsers(dest="apex_session_command", required=True)
    apex_inspect = apex_commands.add_parser("inspect", help="Inspect source semantics and capabilities")
    apex_inspect.add_argument("bundle", type=Path)
    apex_validate = apex_commands.add_parser("validate", help="Validate archive and cross-file integrity")
    apex_validate.add_argument("bundle", type=Path)
    apex_validate.add_argument("--collection-record", type=Path)
    apex_ingest = apex_commands.add_parser("ingest", help="Normalize distance-binned source data")
    apex_ingest.add_argument("bundle", type=Path)
    apex_ingest.add_argument("--collection-record", type=Path, required=True)
    apex_ingest.add_argument("--output", "-o", type=Path, required=True)
    apex_ingest.add_argument(
        "--integration-validation",
        action="store_true",
        help="Permit dirty-code real-sample mechanics validation; output is scientifically ineligible",
    )
    analyze = commands.add_parser(
        "analyze", help="Run a declared descriptive analysis over a verified normalized dataset"
    )
    analyze.add_argument("definition", type=Path)
    analyze.add_argument("--dataset", type=Path, required=True, help="Normalized dataset directory")
    analyze.add_argument("--run-id", required=True)
    analyze.add_argument("--created-at", required=True)
    analyze.add_argument("--output", "-o", type=Path, required=True)
    analyze.add_argument(
        "--metric", type=Path, action="append", default=[],
        help="Metric definition to bind into the run artifact; repeatable",
    )
    verify_analysis = commands.add_parser(
        "verify-analysis", help="Reproduce an analysis run from its bound dataset and compare results"
    )
    verify_analysis.add_argument("run", type=Path, help="analysis-run.json or its directory")
    verify_analysis.add_argument("--dataset", type=Path, required=True)

    evidence = commands.add_parser(
        "evidence", help="Build or verify a comparable evidence set over verified normalized datasets"
    )
    evidence_commands = evidence.add_subparsers(dest="evidence_command", required=True)
    for name, helptext in (
        ("build", "Construct a comparable evidence set from declared, verified inputs"),
        ("verify", "Rebuild an evidence set from its declared inputs and compare it"),
    ):
        sub = evidence_commands.add_parser(name, help=helptext)
        sub.add_argument("definition", type=Path)
        sub.add_argument("--segment", type=Path, required=True)
        sub.add_argument("--protocol-freeze", type=Path, required=True)
        sub.add_argument("--metric", type=Path, required=True)
        sub.add_argument(
            "--dataset", type=Path, action="append", required=True,
            help="Normalized dataset directory; repeat once per contributing dataset",
        )
        if name == "build":
            sub.add_argument("--built-at", required=True)
            sub.add_argument("--output", "-o", type=Path, required=True)
        else:
            sub.add_argument("evidence_set", type=Path, help="evidence-set.json or its directory")

    infer = commands.add_parser(
        "infer", help="Run or verify a preregistered inferential analysis over one comparable evidence set"
    )
    infer_commands = infer.add_subparsers(dest="infer_command", required=True)
    infer_run = infer_commands.add_parser("run", help="Run a preregistered inferential analysis")
    infer_run.add_argument("definition", type=Path)
    infer_run.add_argument("--evidence", type=Path, required=True)
    infer_run.add_argument("--protocol-freeze", type=Path, required=True)
    infer_run.add_argument("--run-id", required=True)
    infer_run.add_argument("--created-at", required=True)
    infer_run.add_argument("--output", "-o", type=Path, required=True)
    infer_verify = infer_commands.add_parser(
        "verify", help="Recompute an inferential run from its bound evidence and compare it"
    )
    infer_verify.add_argument("run", type=Path, help="inferential-analysis-run.json or its directory")
    infer_verify.add_argument("--evidence", type=Path, required=True)
    infer_verify.add_argument("--protocol-freeze", type=Path, required=True)

    hypothesis = commands.add_parser("hypothesis", help="Manage the append-only hypothesis lifecycle")
    hypothesis_commands = hypothesis.add_subparsers(dest="hypothesis_command", required=True)
    hypothesis_register = hypothesis_commands.add_parser(
        "register", help="Register a hypothesis and open its lifecycle at generated"
    )
    hypothesis_register.add_argument("path", type=Path)
    hypothesis_register.add_argument("--registry", type=Path, required=True)
    hypothesis_register.add_argument("--recorded-at", required=True)
    hypothesis_transition = hypothesis_commands.add_parser(
        "transition", help="Append one lifecycle transition after re-verifying the whole history"
    )
    hypothesis_transition.add_argument("hypothesis_id")
    hypothesis_transition.add_argument("--registry", type=Path, required=True)
    hypothesis_transition.add_argument("--to-state", required=True)
    hypothesis_transition.add_argument("--rationale", required=True)
    hypothesis_transition.add_argument("--recorded-at", required=True)
    hypothesis_transition.add_argument("--evidence", type=Path, help="Evidence set backing an evidence-bearing state")
    hypothesis_transition.add_argument("--run", type=Path, help="Verified inferential run backing the transition")
    hypothesis_transition.add_argument(
        "--analysis-definition", type=Path,
        help="Frozen inferential analysis definition; use with --evidence to reach analysis_ready before any run exists",
    )
    hypothesis_transition.add_argument("--protocol-freeze", type=Path, help="Frozen protocol for run verification")
    hypothesis_transition.add_argument("--reviewer-id")
    hypothesis_transition.add_argument("--reviewer-state", default="pending",
                                       choices=["unreviewed", "pending", "approved", "rejected"])
    hypothesis_transition.add_argument("--reviewed-at")
    hypothesis_state = hypothesis_commands.add_parser(
        "state", help="Replay one hypothesis history and report its recomputed state"
    )
    hypothesis_state.add_argument("hypothesis_id")
    hypothesis_state.add_argument("--registry", type=Path, required=True)
    hypothesis_verify = hypothesis_commands.add_parser(
        "verify", help="Replay and re-verify every registered hypothesis history"
    )
    hypothesis_verify.add_argument("--registry", type=Path, required=True)

    package = commands.add_parser(
        "review-package", help="Assemble or verify a deterministic finding review package for human review"
    )
    package_commands = package.add_subparsers(dest="package_command", required=True)
    package_build = package_commands.add_parser("build", help="Assemble a review package")
    package_build.add_argument("finding", type=Path)
    package_build.add_argument("validation", type=Path)
    package_build.add_argument("--evidence", type=Path, required=True)
    package_build.add_argument("--run", type=Path, required=True)
    package_build.add_argument("--registry", type=Path, required=True)
    package_build.add_argument("--hypothesis", required=True)
    package_build.add_argument("--metric", type=Path, action="append", required=True)
    package_build.add_argument("--package-id", required=True)
    package_build.add_argument("--created-at", required=True)
    package_build.add_argument("--output", "-o", type=Path, required=True)
    package_build.add_argument(
        "--recomputed-and-verified", action="store_true",
        help="Record that the bound run was independently recomputed before assembly",
    )
    package_verify = package_commands.add_parser("verify", help="Verify a review package and re-render its report")
    package_verify.add_argument("directory", type=Path)
    package_verify.add_argument("--evidence", type=Path, required=True)
    package_verify.add_argument("--run", type=Path, required=True)

    campaign = commands.add_parser(
        "campaign", help="Run known-answer synthetic campaigns; they demonstrate mechanics, never racing science"
    )
    campaign_commands = campaign.add_subparsers(dest="campaign_command", required=True)
    campaign_list = campaign_commands.add_parser("list", help="List the checked-in campaign specifications")
    campaign_list.add_argument("--root", type=Path, default=Path.cwd())
    campaign_verify = campaign_commands.add_parser(
        "verify", help="Run one campaign end to end and compare it with its known answer"
    )
    campaign_verify.add_argument("spec", type=Path)
    campaign_verify.add_argument("--root", type=Path, default=Path.cwd())
    campaign_verify_all = campaign_commands.add_parser(
        "verify-all", help="Run every checked-in campaign and compare each with its known answer"
    )
    campaign_verify_all.add_argument("--root", type=Path, default=Path.cwd())
    campaign_regenerate = campaign_commands.add_parser(
        "regenerate-references",
        help="Generate clean-commit-bound synthetic reference artifacts into a new review directory",
    )
    campaign_regenerate.add_argument("--root", type=Path, default=Path.cwd())
    campaign_regenerate.add_argument("--output", type=Path, required=True)

    science = commands.add_parser(
        "verify-science-demo",
        help="Reproduce the whole synthetic scientific path twice; never scientific evidence",
    )
    science.add_argument("--root", type=Path, default=Path.cwd())
    science.add_argument(
        "--skip-campaigns", action="store_true", help="Skip the known-answer campaign suite"
    )

    capability = commands.add_parser(
        "capability",
        help="Reconcile a sanitized simulator variable inventory against the recorder profile",
    )
    capability_commands = capability.add_subparsers(dest="capability_command", required=True)
    capability_inspect = capability_commands.add_parser(
        "inspect", help="Summarize a sanitized iRacing variable inventory"
    )
    capability_inspect.add_argument("inventory", type=Path)
    capability_map = capability_commands.add_parser(
        "map", help="Build the evidence-backed channel capability map"
    )
    capability_map.add_argument("inventory", type=Path)
    capability_readiness = capability_commands.add_parser(
        "readiness", help="Report rehearsal and campaign channel readiness"
    )
    capability_readiness.add_argument("inventory", type=Path)

    corpus = commands.add_parser(
        "corpus", help="Admit completed bundles into a frozen corpus, or refuse them with reasons"
    )
    corpus_commands = corpus.add_subparsers(dest="corpus_command", required=True)
    corpus_admit = corpus_commands.add_parser(
        "admit",
        help=(
            "Evaluate completed bundles against a verified protocol freeze and its frozen schedule. "
            "Validation proves a bundle is internally consistent; admission proves it is the recording "
            "the protocol asked for"
        ),
    )
    corpus_admit.add_argument("--protocol-snapshot", type=Path, required=True)
    corpus_admit.add_argument(
        "--apex-data-root", type=Path,
        help=(
            "Apex data root, read-only. REQUIRED to admit a control block: "
            "'--coaching disabled' is a recorder declaration, not a product control, so only the "
            "Apex store can show that nothing was delivered during the recording"
        ),
    )
    corpus_admit.add_argument(
        "bundle", type=Path, nargs="+", help="Completed research bundle directories"
    )

    corpus_binding = corpus_commands.add_parser(
        "coaching-binding",
        help=(
            "Read-only: report which Apex coaching sessions have written events since an "
            "instant. The operator condition for the Practice-to-Qualifying rollover, where "
            "the recorder's own binding probe has already latched and prints nothing"
        ),
    )
    corpus_binding.add_argument("--apex-data-root", type=Path, required=True)
    corpus_binding.add_argument(
        "--since", required=True,
        help="UTC instant, ISO-8601. Use the SESSION TRANSITION line's wall-clock time",
    )

    apex_research = commands.add_parser(
        "apex-research", help="Inspect, validate, or normalize a completed local Research Recorder bundle"
    )
    research_commands = apex_research.add_subparsers(dest="apex_research_command", required=True)
    research_inspect = research_commands.add_parser("inspect", help="Inspect recorder capabilities and counts")
    research_inspect.add_argument("bundle", type=Path)
    research_validate = research_commands.add_parser("validate", help="Validate completion, contract, hashes, and semantics")
    research_validate.add_argument("bundle", type=Path)
    research_validate.add_argument("--collection-record", type=Path)
    research_ingest = research_commands.add_parser("ingest", help="Stream recorder samples into normalized v1 records")
    research_ingest.add_argument("bundle", type=Path)
    research_ingest.add_argument("--collection-record", type=Path, required=True)
    research_ingest.add_argument("--protocol-snapshot", type=Path)
    research_ingest.add_argument(
        "--exploratory-intake", type=Path,
        help=(
            "Hash-bound apex-labs.exploratory-intake/v1 admitting a real session collected "
            "before any protocol freeze. Mutually exclusive with --protocol-snapshot; the "
            "resulting dataset is permanently exploratory (descriptive and hypothesis "
            "generation only, never confirmatory, causal, or primary-corpus evidence)"
        ),
    )
    research_ingest.add_argument("--output", "-o", type=Path, required=True)
    research_ingest.add_argument(
        "--integration-validation", action="store_true",
        help="Permit dirty-code real-sample mechanics validation; output is scientifically ineligible",
    )
    return parser


def _run(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "ingest":
        manifest = ingest_dataset(args.manifest, args.output)
        return {
            "ok": True,
            "dataset_id": manifest["dataset_id"],
            "fingerprint": manifest["dataset_fingerprint"],
            "output": str(args.output),
            "record_counts": manifest["record_counts"],
            "synthetic": manifest["synthetic"],
        }
    if args.command == "inspect":
        return inspect_dataset(args.manifest)
    if args.command == "validate":
        return _validate_file(args.kind, args.path)
    if args.command == "experiment":
        if args.experiment_command == "validate":
            return _validate_collection(args.path, validate_experiment, "experiment")
        if args.experiment_command == "freeze":
            schedule = [] if args.schedule is None else read_json(args.schedule)
            if not isinstance(schedule, list):
                raise ContractValidationError("Frozen schedule input must be a JSON array")
            path = freeze_protocol(
                args.path,
                args.registry,
                frozen_at=args.frozen_at,
                strategy=args.strategy,
                method=args.method,
                seed=args.seed,
                schedule_id=args.schedule_id,
                schedule=schedule,
            )
            snapshot = verify_protocol_freeze(read_json(path))
            return {
                "ok": True,
                "freeze_id": snapshot["freeze_id"],
                "freeze_sha256": snapshot["freeze_sha256"],
                "path": str(path),
            }
        if args.experiment_command == "verify-freeze":
            snapshot = verify_protocol_freeze(read_json(args.path))
            return {
                "valid": True,
                "freeze_id": snapshot["freeze_id"],
                "freeze_sha256": snapshot["freeze_sha256"],
            }
    if args.command == "findings":
        if args.findings_command == "validate":
            return _validate_collection(args.path, validate_finding, "finding")
        finding, artifact = validate_finding_with_artifact(
            read_json(args.finding), read_json(args.validation)
        )
        return {
            "valid": True,
            "finding_id": finding["finding_id"],
            "validation_id": artifact["validation_id"],
            "scientific_gate": artifact["gate_evaluations"]["scientific"],
        }
    if args.command == "validate-records":
        records = read_json_lines(args.path)
        for index, record in enumerate(records):
            try:
                VALIDATORS["normalized-record"](record)
            except ContractValidationError as exc:
                raise ContractValidationError(f"record {index}: {exc}") from exc
        return {"valid": True, "kind": "normalized-record", "records_validated": len(records), "path": str(args.path)}
    if args.command == "export-product-findings":
        manifest = generate_product_export(args.definition, args.output, args.root)
        return {
            "ok": True,
            "export_id": manifest["export_id"],
            "output": str(args.output),
            "finding_count": len(manifest["findings"]),
            "review_gate": manifest["review_gate"],
        }
    if args.command == "verify-export":
        manifest = verify_product_export(args.directory)
        return {"valid": True, "export_id": manifest["export_id"], "files_verified": len(manifest["files"])}
    if args.command == "repository-guard":
        result = run_repository_guard(args.root)
        if not result["ok"]:
            raise ContractValidationError(
                f"Repository guard found {len(result['findings'])} issue(s): {result['findings']}"
            )
        return result
    if args.command == "verify-synthetic-demo":
        return verify_synthetic_demo(args.root)
    if args.command == "apex-session":
        if args.apex_session_command == "inspect":
            return inspect_apex_session_bundle(args.bundle)
        if args.apex_session_command == "validate":
            return validate_apex_session_bundle(args.bundle, args.collection_record)
        manifest = ingest_apex_session_bundle(
            args.bundle,
            args.output,
            args.collection_record,
            integration_validation=args.integration_validation,
        )
        return {
            "ok": True,
            "dataset_id": manifest["dataset_id"],
            "fingerprint": manifest["dataset_fingerprint"],
            "record_counts": manifest["record_counts"],
            "source_semantics": manifest["source_semantics"],
            "research_eligibility": manifest["research_eligibility"],
            "output": str(args.output),
        }
    if args.command == "analyze":
        artifact = run_analysis(
            args.definition,
            args.dataset,
            args.output,
            run_id=args.run_id,
            created_at=args.created_at,
            metric_paths=args.metric,
        )
        return {
            "ok": True,
            "run_id": artifact["run_id"],
            "analysis_id": artifact["definition"]["analysis_id"],
            "classification": artifact["classification"],
            "dataset_id": artifact["dataset"]["dataset_id"],
            "run_sha256": artifact["run_sha256"],
            "records_validated": artifact["integrity"]["records_validated"],
            "result_count": len(artifact["results"]),
            "output": str(args.output),
        }
    if args.command == "verify-analysis":
        return verify_analysis_run(args.run, args.dataset)
    if args.command == "evidence":
        if args.evidence_command == "build":
            artifact = build_evidence_set(
                args.definition, args.segment, args.protocol_freeze, args.metric,
                args.dataset, args.output, built_at=args.built_at,
            )
            return {
                "ok": True,
                "evidence_set_id": artifact["evidence_set_id"],
                "evidence_set_sha256": artifact["evidence_set_sha256"],
                "classification": artifact["classification"],
                "comparability": artifact["comparability"]["status"],
                "counts": artifact["counts"],
                "structural_interpretation_ceiling": artifact["structural_interpretation_ceiling"],
                "post_hoc_exclusions_present": artifact["post_hoc_exclusions_present"],
                "output": str(args.output),
            }
        return verify_evidence_set(
            args.evidence_set, args.definition, args.segment, args.protocol_freeze,
            args.metric, args.dataset,
        )
    if args.command == "infer":
        if args.infer_command == "run":
            artifact = run_inferential_analysis(
                args.definition, args.evidence, args.protocol_freeze, args.output,
                run_id=args.run_id, created_at=args.created_at,
            )
            primary = next(
                (item for item in artifact["comparisons"] if item["role"] == "primary"),
                artifact["comparisons"][0],
            )
            return {
                "ok": True,
                "run_id": artifact["run_id"],
                "analysis_id": artifact["definition"]["analysis_id"],
                "classification": artifact["classification"],
                "run_sha256": artifact["run_sha256"],
                "analysis_state": artifact["analysis_state"],
                "sufficiency": artifact["sufficiency"]["status"],
                "effective_ceiling": artifact["interpretation"]["effective_ceiling"],
                "primary_comparison": primary["comparison_id"],
                "primary_estimate": None if primary["effect"] is None else primary["effect"]["estimate"],
                "scientific_eligibility": artifact["scientific_eligibility"]["eligible"],
                "output": str(args.output),
            }
        return verify_inferential_analysis_run(args.run, args.evidence, args.protocol_freeze)
    if args.command == "hypothesis":
        if args.hypothesis_command == "register":
            sealed = register_hypothesis(read_json(args.path), args.registry, recorded_at=args.recorded_at)
            history = replay(args.registry, sealed["hypothesis_id"])
            return {
                "ok": True,
                "hypothesis_id": sealed["hypothesis_id"],
                "hypothesis_sha256": sealed["hypothesis_sha256"],
                "state": history["state"],
                "generation_source": sealed["generation"]["source"],
                "is_evidence": False,
            }
        if args.hypothesis_command == "transition":
            bindings = None
            if args.evidence and args.analysis_definition and not args.run:
                evidence_artifact = validate_evidence_set(
                    read_json(
                        args.evidence / "evidence-set.json" if args.evidence.is_dir() else args.evidence
                    )
                )
                analysis_definition = validate_inferential_analysis_definition(
                    read_json(args.analysis_definition)
                )
                bindings = plan_bindings(
                    evidence_artifact,
                    analysis_definition,
                    sha256_bytes(canonical_json_bytes(analysis_definition)),
                )
            elif args.evidence and args.run:
                if not args.protocol_freeze:
                    raise ContractValidationError(
                        "--protocol-freeze is required to verify the run backing an evidence-bearing transition"
                    )
                evidence_artifact = validate_evidence_set(
                    read_json(
                        args.evidence / "evidence-set.json" if args.evidence.is_dir() else args.evidence
                    )
                )
                verification = verify_inferential_analysis_run(args.run, args.evidence, args.protocol_freeze)
                run_artifact = validate_inferential_analysis_run(
                    read_json(
                        args.run / "inferential-analysis-run.json" if args.run.is_dir() else args.run
                    )
                )
                bindings = bindings_from_run(evidence_artifact, run_artifact, verified=verification["valid"])
            reviewer = {
                "state": args.reviewer_state,
                "reviewer_id": args.reviewer_id,
                "reviewed_at": args.reviewed_at,
                "notes": [],
            }
            transition = record_transition(
                args.registry, args.hypothesis_id, to_state=args.to_state,
                rationale=args.rationale, recorded_at=args.recorded_at,
                bindings=bindings, reviewer=reviewer,
            )
            return {
                "ok": True,
                "hypothesis_id": transition["hypothesis_id"],
                "sequence_index": transition["sequence_index"],
                "from_state": transition["from_state"],
                "to_state": transition["to_state"],
                "transition_sha256": transition["transition_sha256"],
            }
        if args.hypothesis_command == "state":
            history = replay(args.registry, args.hypothesis_id)
            return {
                "valid": True,
                "hypothesis_id": args.hypothesis_id,
                "state": history["state"],
                "transitions": len(history["transitions"]),
                "head_transition_sha256": history["head_transition_sha256"],
            }
        return verify_registry(args.registry)
    if args.command == "review-package":
        if args.package_command == "build":
            history = replay(args.registry, args.hypothesis)
            package = build_review_package(
                read_json(args.finding), read_json(args.validation), args.evidence, args.run,
                history, args.metric, args.output, package_id=args.package_id,
                created_at=args.created_at, recomputed_and_verified=args.recomputed_and_verified,
            )
            return {
                "ok": True,
                "package_id": package["package_id"],
                "package_sha256": package["package_sha256"],
                "classification": package["classification"],
                "finding_status": package["finding"]["status"],
                "hypothesis_state": package["hypothesis"]["state"],
                "interpretation_ceiling": package["interpretation_ceiling"],
                "product_recommendation": package["product_recommendation"]["state"],
                "automatic_production_change": False,
                "output": str(args.output),
            }
        return verify_review_package(args.directory, args.run, args.evidence)
    if args.command == "campaign":
        if args.campaign_command == "list":
            return {
                "campaigns": [path.name for path in campaign_specs(args.root)],
                "classification": "synthetic_demo_only_not_racing_research",
            }
        if args.campaign_command == "verify":
            from tempfile import TemporaryDirectory

            with TemporaryDirectory(prefix="apex-labs-campaign-") as directory:
                result = run_campaign(args.spec, Path(directory), args.root)
            if not result["ok"]:
                raise ContractValidationError(
                    f"Campaign {result['campaign_id']} did not match its known answer: {result['mismatches']}"
                )
            return result
        if args.campaign_command == "regenerate-references":
            return regenerate_reference_artifacts(args.root, args.output)
        result = run_all_campaigns(args.root)
        if not result["ok"]:
            raise ContractValidationError(
                f"Campaigns did not match their known answers: {result['mismatches']}"
            )
        return result
    if args.command == "verify-science-demo":
        return verify_science_demo(args.root, run_campaigns=not args.skip_campaigns)
    if args.command == "capability":
        inventory = load_variable_inventory(args.inventory)
        if args.capability_command == "inspect":
            return inventory.summary()
        if args.capability_command == "map":
            return build_capability_map(inventory)
        return rehearsal_readiness(inventory)

    if args.command == "corpus":
        if args.corpus_command == "coaching-binding":
            return coaching_binding_since(args.apex_data_root, args.since)
        return admit_corpus(
            list(args.bundle), args.protocol_snapshot, apex_data_root=args.apex_data_root)

    if args.command == "apex-research":
        if args.apex_research_command == "inspect":
            return inspect_research_bundle(args.bundle)
        if args.apex_research_command == "validate":
            return validate_research_bundle(args.bundle, args.collection_record)
        manifest = ingest_research_bundle(
            args.bundle,
            args.output,
            args.collection_record,
            integration_validation=args.integration_validation,
            protocol_snapshot_path=args.protocol_snapshot,
            exploratory_intake_path=args.exploratory_intake,
        )
        return {
            "ok": True,
            "dataset_id": manifest["dataset_id"],
            "fingerprint": manifest["dataset_fingerprint"],
            "record_counts": manifest["record_counts"],
            "output": str(args.output),
            "direction": "research-bundle-to-labs-only",
            "scientific_eligibility": manifest.get("scientific_eligibility"),
        }
    raise AssertionError(f"Unhandled command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        _print_json(_run(args))
        return 0
    except (ApexLabsError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
