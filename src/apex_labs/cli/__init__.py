"""Apex Labs command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from apex_labs import __version__
from apex_labs.demo import verify_synthetic_demo
from apex_labs.errors import ApexLabsError, ContractValidationError
from apex_labs.experiments import freeze_protocol, verify_protocol_freeze
from apex_labs.exports import generate_product_export, verify_product_export
from apex_labs.findings import validate_finding_with_artifact
from apex_labs.ingestion import ingest_dataset, inspect_dataset
from apex_labs.io import canonical_json_bytes, read_json, read_json_lines
from apex_labs.repository_guard import run_repository_guard
from apex_labs.schemas import (
    validate_experiment,
    validate_finding,
    validate_finding_validation,
    validate_protocol_amendment,
    validate_protocol_freeze,
)
from apex_labs.schemas.validation import VALIDATORS

ALL_VALIDATORS = {
    **VALIDATORS,
    "finding-validation": validate_finding_validation,
    "protocol-amendment": validate_protocol_amendment,
    "protocol-freeze": validate_protocol_freeze,
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
