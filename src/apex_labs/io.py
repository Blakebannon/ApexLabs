"""Deterministic JSON and path-safety helpers."""

from __future__ import annotations

import json
import re
from pathlib import Path
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Iterable

from apex_labs.errors import ContractValidationError


def _reject_constant(value: str) -> None:
    raise ContractValidationError(f"Non-finite JSON number is forbidden: {value}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractValidationError(f"Duplicate JSON object key is forbidden: {key!r}")
        result[key] = value
    return result


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize JSON deterministically using UTF-8 and one trailing newline."""
    text = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return (text + "\n").encode("utf-8")


def read_json(path: Path) -> Any:
    try:
        return parse_json_bytes(path.read_bytes(), source=str(path))
    except FileNotFoundError as exc:
        raise ContractValidationError(f"File not found: {path}") from exc


def parse_json_bytes(content: bytes, *, source: str = "<bytes>") -> Any:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractValidationError(f"JSON must be UTF-8 in {source}: {exc}") from exc
    try:
        return json.loads(
            text,
            parse_constant=_reject_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except json.JSONDecodeError as exc:
        raise ContractValidationError(
            f"Malformed JSON in {source} at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc


def read_json_lines(path: Path) -> list[Any]:
    return list(iter_json_lines(path))


def iter_json_lines(path: Path) -> Iterable[Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    yield json.loads(
                        line,
                        parse_constant=_reject_constant,
                        object_pairs_hook=_reject_duplicate_keys,
                    )
                except json.JSONDecodeError as exc:
                    raise ContractValidationError(
                        f"Malformed JSONL in {path} at line {line_number}: {exc.msg}"
                    ) from exc
    except FileNotFoundError as exc:
        raise ContractValidationError(f"File not found: {path}") from exc
    except UnicodeDecodeError as exc:
        raise ContractValidationError(f"JSONL must be UTF-8 in {path}: {exc}") from exc


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def write_json_lines(path: Path, records: Iterable[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        for record in records:
            handle.write(canonical_json_bytes(record))


def validate_contract_path(relative: str) -> str:
    """Validate a portable, canonical, repository-relative contract path."""
    if not isinstance(relative, str) or not relative:
        raise ContractValidationError("Contract paths must be non-empty strings")
    lowered = relative.casefold()
    if "\\" in relative:
        raise ContractValidationError(
            f"Contract paths must use canonical POSIX separators, not backslashes: {relative}"
        )
    windows = PureWindowsPath(relative)
    posix = PurePosixPath(relative)
    device_prefixes = ("//?/", "//./", "/??/", "globalroot/")
    normalized_prefix = lowered.replace("\\", "/")
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or bool(windows.drive)
        or normalized_prefix.startswith(device_prefixes)
        or relative.startswith("//")
        or ":" in relative
    ):
        raise ContractValidationError(f"Contract paths must be relative: {relative}")
    parts = relative.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ContractValidationError(f"Contract path is not canonical or contains traversal: {relative}")
    if re.search(r"[\x00-\x1f]", relative):
        raise ContractValidationError(f"Contract path contains a control character: {relative!r}")
    reserved = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
    for part in parts:
        device_stem = part.split(".", 1)[0].casefold().rstrip(" ")
        if device_stem in reserved or part.endswith((" ", ".")):
            raise ContractValidationError(f"Contract path contains a Windows device/ambiguous segment: {relative}")
    return relative


def resolve_relative_file(base: Path, relative: str) -> Path:
    """Resolve a contract path without permitting absolute paths or traversal."""
    validate_contract_path(relative)
    parts = relative.split("/")
    candidate = Path(*parts)
    base_resolved = base.resolve()
    resolved = (base_resolved / candidate).resolve()
    try:
        resolved.relative_to(base_resolved)
    except ValueError as exc:
        raise ContractValidationError(f"Path escapes its contract directory: {relative}") from exc
    if not resolved.is_file():
        raise ContractValidationError(f"Referenced file does not exist: {relative}")
    return resolved
