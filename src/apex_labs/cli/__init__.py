"""Apex Labs command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from apex_labs import __version__
from apex_labs.analysis import run_analysis, verify_analysis_run
from apex_labs.demo import verify_synthetic_demo
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
from apex_labs.repository_guard import run_repository_guard
from apex_labs.schemas import (
    validate_analysis_definition,
    validate_analysis_run,
    validate_experiment,
    validate_finding,
    validate_finding_validation,
    validate_protocol_amendment,
    validate_protocol_freeze,
    validate_apex_session_manifest,
    validate_collection_record,
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
    "product-annotations": validate_product_annotations,
    "research-export-manifest": validate_research_export_manifest,
    "research-recorder-manifest": validate_research_recorder_manifest,
    "adapter-conformance": validate_adapter_conformance,
    "analysis-definition": validate_analysis_definition,
    "analysis-run": validate_analysis_run,
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
        )
        return {
            "ok": True,
            "dataset_id": manifest["dataset_id"],
            "fingerprint": manifest["dataset_fingerprint"],
            "record_counts": manifest["record_counts"],
            "output": str(args.output),
            "direction": "research-bundle-to-labs-only",
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
