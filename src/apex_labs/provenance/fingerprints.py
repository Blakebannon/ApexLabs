"""Content hashes and deterministic dataset identities."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from apex_labs.errors import IntegrityError
from apex_labs.io import canonical_json_bytes, resolve_relative_file
from apex_labs.schemas.versions import NORMALIZATION_VERSION


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def verify_source_files(manifest: dict[str, Any], manifest_dir: Path) -> list[Path]:
    """Resolve and hash every declared source file before any ingestion occurs."""
    resolved: list[Path] = []
    for source in manifest["source_files"]:
        path = resolve_relative_file(manifest_dir, source["path"])
        actual = sha256_file(path)
        if actual != source["sha256"]:
            raise IntegrityError(
                f"Source hash mismatch for {source['path']}: declared {source['sha256']}, actual {actual}"
            )
        resolved.append(path)
    return resolved


def _canonical_manifest_content(manifest: dict[str, Any]) -> dict[str, Any]:
    """Normalize fields whose enumeration order has no scientific meaning."""
    content = dict(manifest)
    content["source_files"] = sorted(
        (dict(item) for item in manifest["source_files"]),
        key=lambda item: (item["role"], item["sha256"], item["path"].casefold()),
    )
    if "tags" in content:
        content["tags"] = sorted(content["tags"])
    return content


def canonical_manifest_sha256(manifest: dict[str, Any]) -> str:
    return sha256_bytes(canonical_json_bytes(_canonical_manifest_content(manifest)))


def dataset_fingerprint(manifest: dict[str, Any]) -> str:
    """Fingerprint declared source/transformation inputs before normalized output exists.

    This compatibility helper is an input fingerprint, not the final normalized
    scientific fingerprint. New code should label it ``source_fingerprint``.
    """
    identity = {
        "contract": manifest["schema_version"],
        "synthetic": manifest["synthetic"],
        "simulator": manifest["simulator"],
        "source_files": sorted(
            (
                {"sha256": item["sha256"], "role": item["role"], "media_type": item["media_type"]}
                for item in manifest["source_files"]
            ),
            key=lambda item: (item["role"], item["sha256"], item["media_type"]),
        ),
        "adapter": manifest["adapter"],
        "normalization_version": NORMALIZATION_VERSION,
        "canonical_source_manifest_sha256": canonical_manifest_sha256(manifest),
    }
    return sha256_bytes(canonical_json_bytes(identity))


def build_dataset_fingerprint(provenance_inputs: dict[str, Any]) -> str:
    """Bind final normalized content to complete declared transformation evidence."""
    return sha256_bytes(canonical_json_bytes(provenance_inputs))


def normalized_dataset_fingerprint_basis(manifest: dict[str, Any]) -> dict[str, Any]:
    """Select every field that defines normalized scientific content/behavior."""
    return {
        "synthetic": manifest["synthetic"],
        "source_fingerprint": manifest["source_fingerprint"],
        "canonical_source_manifest_sha256": manifest["canonical_source_manifest_sha256"],
        "source_files": sorted(
            (
                {
                    "sha256": item["sha256"],
                    "role": item["role"],
                    "media_type": item["media_type"],
                }
                for item in manifest["source_files"]
            ),
            key=lambda item: (item["role"], item["sha256"], item["media_type"]),
        ),
        "adapter": manifest["adapter"],
        "normalization_version": manifest["normalization_version"],
        "code_identity": manifest["code_identity"],
        "preprocessing": manifest["preprocessing"],
        "collection_context": manifest["collection_context"],
        "temporal_policy": manifest["temporal_policy"],
        "conventions": manifest["conventions"],
        "records_sha256": manifest["records_sha256"],
        "record_counts": manifest["record_counts"],
        "integrity_summary": manifest["integrity_summary"],
    }


def snapshot_source_files(
    manifest: dict[str, Any], manifest_dir: Path, snapshot_dir: Path
) -> dict[str, Path]:
    """Copy, hash, and later parse the exact same immutable snapshot bytes."""
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshots: dict[str, Path] = {}
    declarations = sorted(manifest["source_files"], key=lambda item: item["path"].casefold())
    for index, source in enumerate(declarations):
        resolved = resolve_relative_file(manifest_dir, source["path"])
        destination = snapshot_dir / f"{index:04d}-{source['sha256']}"
        digest = hashlib.sha256()
        with resolved.open("rb") as source_handle, destination.open("wb") as target_handle:
            while chunk := source_handle.read(1024 * 1024):
                digest.update(chunk)
                target_handle.write(chunk)
        actual = digest.hexdigest()
        if actual != source["sha256"]:
            destination.unlink(missing_ok=True)
            raise IntegrityError(
                f"Source hash mismatch for {source['path']}: declared {source['sha256']}, actual {actual}"
            )
        snapshots[source["path"]] = destination
    return snapshots
