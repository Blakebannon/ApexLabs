"""Content-bound Apex Labs code and schema identity."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from apex_labs import __version__
from apex_labs.errors import IntegrityError
from apex_labs.io import canonical_json_bytes
from apex_labs.provenance.fingerprints import sha256_bytes, sha256_file


def find_project_root(start: Path | None = None) -> Path:
    candidates = []
    if start is not None:
        candidates.append(start.resolve())
    candidates.append(Path.cwd().resolve())
    candidates.append(Path(__file__).resolve().parents[3])
    for candidate in candidates:
        current = candidate if candidate.is_dir() else candidate.parent
        for directory in (current, *current.parents):
            if (directory / "pyproject.toml").is_file() and (directory / "src" / "apex_labs").is_dir():
                return directory
    raise IntegrityError("Cannot locate an Apex Labs project root containing pyproject.toml and src/apex_labs")


def _git_identity(root: Path) -> tuple[str, str]:
    commit = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    if commit.returncode != 0:
        return "UNCOMMITTED", "uncommitted"
    status = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all"],
        check=False,
        capture_output=True,
        text=True,
    )
    if status.returncode != 0:
        raise IntegrityError(f"Cannot determine Apex Labs Git state: {status.stderr.strip()}")
    return commit.stdout.strip().lower(), "clean" if not status.stdout.strip() else "dirty"


def _content_inventory(root: Path) -> tuple[list[dict[str, str]], dict[str, str]]:
    package_files = sorted(
        path for path in (root / "src" / "apex_labs").rglob("*.py") if path.is_file()
    )
    schema_files = sorted(
        path for path in (root / "contracts" / "v1").glob("*.schema.json") if path.is_file()
    )
    if not package_files or not schema_files:
        raise IntegrityError("Apex Labs code/schema inventory is incomplete")
    inventory = [
        {"path": path.relative_to(root).as_posix(), "sha256": sha256_file(path)}
        for path in package_files + schema_files
    ]
    schema_hashes = {
        path.relative_to(root).as_posix(): sha256_file(path) for path in schema_files
    }
    return inventory, schema_hashes


def apex_labs_code_identity(project_root: Path | None = None) -> dict[str, Any]:
    """Return a path-independent identity for code and published schemas."""
    root = find_project_root(project_root)
    git_commit, git_state = _git_identity(root)
    inventory, schema_hashes = _content_inventory(root)
    content_sha256 = sha256_bytes(canonical_json_bytes(inventory))
    return {
        "package_version": __version__,
        "git_commit": git_commit,
        "git_state": git_state,
        "code_and_schema_sha256": content_sha256,
        "schema_sha256": schema_hashes,
    }


def require_research_code_identity(identity: dict[str, Any], *, synthetic: bool) -> None:
    """Real research must run from an exact clean Git commit."""
    if synthetic:
        return
    if identity.get("git_state") != "clean" or identity.get("git_commit") == "UNCOMMITTED":
        raise IntegrityError(
            "Real dataset ingestion requires a clean Apex Labs Git commit; synthetic mechanics may be uncommitted"
        )
