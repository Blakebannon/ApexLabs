"""Heuristic repository boundary guard for Git-visible content.

This supplements .gitignore. It is intentionally conservative and does not claim
to replace a dedicated secret scanner, privacy review, or data-governance process.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from apex_labs.io import read_json
from apex_labs.schemas import validate_dataset_manifest

PROHIBITED_EXTENSIONS = {
    ".ibt", ".ld", ".ldx", ".bin", ".parquet", ".feather", ".h5", ".hdf5",
    ".db", ".sqlite", ".sqlite3", ".mdb", ".accdb", ".p12", ".pfx", ".pem",
    ".key", ".cer", ".crt", ".zip",
}
MAX_REPOSITORY_FILE_BYTES = 5 * 1024 * 1024
MAX_SYNTHETIC_FIXTURE_FILE_BYTES = 1 * 1024 * 1024
MAX_SYNTHETIC_FIXTURE_TOTAL_BYTES = 2 * 1024 * 1024

_SECRET_PATTERNS = [
    ("private-key", re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("aws-access-key", re.compile(rb"AKIA[0-9A-Z]{16}")),
    ("openai-like-key", re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("generic-secret-assignment", re.compile(rb"(?i)\b(?:api[_-]?key|client[_-]?secret|password)\s*[:=]\s*['\"][^'\"\r\n]{8,}")),
]
_DIRECT_IDENTIFIER_JSON = re.compile(
    rb'(?i)"(?:full_?name|email(?:_address)?|phone(?:_number)?|street_?address|iracing_?customer_?id|steam_?id)"\s*:'
)
_DIRECT_IDENTIFIER_CSV = re.compile(
    rb"(?i)^(?:[^\r\n]*,)?(?:full_?name|email(?:_address)?|phone(?:_number)?|street_?address|iracing_?customer_?id|steam_?id)(?:,|\r?$)"
)


@dataclass(frozen=True)
class GuardFinding:
    rule: str
    path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"rule": self.rule, "path": self.path, "message": self.message}


def git_visible_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Cannot enumerate Git-visible files: {result.stderr.strip()}")
    paths: list[Path] = []
    for relative in result.stdout.splitlines():
        candidate = root / relative
        if candidate.is_file():
            paths.append(candidate)
    return sorted(paths)


def _fixture_root(root: Path, path: Path) -> Path | None:
    fixture_base = root / "tests" / "fixtures"
    try:
        relative = path.relative_to(fixture_base)
    except ValueError:
        return None
    if not relative.parts:
        return None
    if len(relative.parts) == 1:
        return None
    return fixture_base / relative.parts[0]


def _synthetic_dataset_root(root: Path, path: Path) -> Path | None:
    dataset_base = root / "datasets" / "synthetic"
    try:
        relative = path.relative_to(dataset_base)
    except ValueError:
        return None
    if len(relative.parts) < 2:
        return None
    return dataset_base / relative.parts[0]


def _fixture_classification(fixture_root: Path) -> tuple[bool, str]:
    collection_path = fixture_root / "collection-record.json"
    if collection_path.is_file():
        try:
            from apex_labs.schemas import validate_collection_record

            collection = validate_collection_record(read_json(collection_path))
            if collection["synthetic"] and collection["privacy"]["classification"] == "synthetic":
                return True, "synthetic"
        except Exception:
            pass
    manifests = sorted(fixture_root.glob("*manifest*.json"))
    for manifest_path in manifests:
        try:
            manifest = validate_dataset_manifest(read_json(manifest_path))
        except Exception:
            continue
        if manifest["synthetic"] and manifest["data_classification"] == "synthetic":
            return True, "synthetic"
        if manifest["data_classification"] == "sanitized":
            return True, "sanitized"
    return False, "unclassified"


def scan_repository_files(root: Path, files: Iterable[Path]) -> list[GuardFinding]:
    root = root.resolve()
    findings: list[GuardFinding] = []
    files = sorted({path.resolve() for path in files})
    fixture_totals: dict[Path, int] = {}
    fixture_classifications: dict[Path, tuple[bool, str]] = {}
    for path in files:
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError:
            findings.append(GuardFinding("path-escape", str(path), "Git-visible path escapes repository root"))
            continue
        stat = path.stat()
        suffix = path.suffix.casefold()
        filename = path.name.casefold()
        fixture = _fixture_root(root, path)
        classified_root = fixture or _synthetic_dataset_root(root, path)
        allowed_fixture = False
        if classified_root is not None:
            classification = fixture_classifications.setdefault(
                classified_root, _fixture_classification(classified_root)
            )
            allowed_fixture = classification[0]
        if fixture is not None:
            fixture_totals[fixture] = fixture_totals.get(fixture, 0) + stat.st_size
            if stat.st_size > MAX_SYNTHETIC_FIXTURE_FILE_BYTES:
                findings.append(
                    GuardFinding("fixture-size", relative, "Synthetic/sanitized fixture file exceeds 1 MiB")
                )
            if path.name != "README.md" and not allowed_fixture:
                findings.append(
                    GuardFinding("fixture-classification", relative, "Fixture is not explicitly synthetic or sanitized in a valid dataset manifest")
                )
        if stat.st_size > MAX_REPOSITORY_FILE_BYTES:
            findings.append(GuardFinding("large-file", relative, "Git-visible file exceeds 5 MiB"))
        if suffix in PROHIBITED_EXTENSIONS:
            findings.append(GuardFinding("prohibited-binary", relative, f"Prohibited raw/binary/credential extension: {suffix}"))
        if filename == ".env" or filename.startswith(".env."):
            findings.append(GuardFinding("environment-file", relative, "Environment files may contain credentials"))
        lower_relative = relative.casefold()
        if "telemetry" in filename and suffix in {".csv", ".json", ".jsonl"}:
            if not allowed_fixture:
                findings.append(GuardFinding("raw-telemetry", relative, "Telemetry-like data is outside an explicitly classified synthetic/sanitized fixture"))
        if lower_relative.startswith("datasets/manifests/") and suffix != ".json":
            findings.append(GuardFinding("manifest-allowlist", relative, "datasets/manifests may contain JSON manifests only"))
        try:
            content = path.read_bytes()
        except OSError as exc:
            findings.append(GuardFinding("unreadable", relative, f"Cannot inspect file: {exc}"))
            continue
        for rule, pattern in _SECRET_PATTERNS:
            if pattern.search(content):
                findings.append(GuardFinding(rule, relative, "Potential credential/private-key material detected"))
        if b"\x00" in content and suffix not in PROHIBITED_EXTENSIONS:
            findings.append(GuardFinding("unrecognized-binary", relative, "NUL bytes detected in a Git-visible file"))
        if (fixture is not None or lower_relative.startswith("datasets/")) and suffix in {".json", ".csv", ".jsonl", ".yaml", ".yml"}:
            if _DIRECT_IDENTIFIER_JSON.search(content) or _DIRECT_IDENTIFIER_CSV.search(content):
                findings.append(GuardFinding("direct-identifier", relative, "Potential direct participant identifier field detected"))
    for fixture, total in fixture_totals.items():
        if total > MAX_SYNTHETIC_FIXTURE_TOTAL_BYTES:
            findings.append(
                GuardFinding(
                    "fixture-total-size",
                    fixture.relative_to(root).as_posix(),
                    "Synthetic/sanitized fixture directory exceeds 2 MiB",
                )
            )
    return sorted(findings, key=lambda item: (item.path, item.rule))


def run_repository_guard(root: Path) -> dict[str, object]:
    files = git_visible_files(root)
    findings = scan_repository_files(root, files)
    return {
        "ok": not findings,
        "files_scanned": len(files),
        "findings": [finding.as_dict() for finding in findings],
        "limitations": (
            "Heuristic guard only: passing does not prove absence of secrets, personal data, or raw telemetry; human privacy review remains required."
        ),
    }
