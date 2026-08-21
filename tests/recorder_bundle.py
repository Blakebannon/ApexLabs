"""Helpers over the committed Research Recorder conformance fixture.

`tests/fixtures/research_recorder_v1` holds a bundle produced by the actual Apex Sim Coach
Research Recorder (`ApexTrackCoach.ResearchRecorder synthetic`) at product commit
4ac145bf6f90169df21371744f10e16c3cbecbd0 plus this checkpoint's recorder changes. It is wholly
synthetic and deterministic: fabricated values, an explicitly synthetic participant, fixed
timestamps, and no real driver, session or simulator data of any kind.

Binding the Labs tests to real recorder bytes is the point. If the product changes its sample
columns, metadata declarations or file inventory without Labs changing with it, the
conformance tests fail here rather than during a live rehearsal.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from _support import ROOT

from apex_labs.io import canonical_json_bytes, read_json
from apex_labs.provenance import sha256_bytes

FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "research_recorder_v1"
FIXTURE = FIXTURE_ROOT / "bundle"
FIXTURE_COLLECTION = FIXTURE_ROOT / "collection-record.json"

# The exact header the product recorder emitted, read from its own output rather than
# restated here, so this list cannot drift away from what the recorder actually writes.
RECORDER_COLUMNS = (FIXTURE / "samples.csv").read_text(encoding="utf-8").splitlines()[0].split(",")


def _sha(content: bytes) -> str:
    return sha256_bytes(content)


def rebind(bundle: Path) -> None:
    """Re-seal a bundle after a deliberate mutation, so tests exercise the intended failure.

    Without this a mutation would merely trip the hash check, which proves nothing about the
    rule under test.
    """
    manifest = read_json(bundle / "manifest.json")
    manifest["files"] = [
        {
            **entry,
            "size_bytes": (bundle / entry["path"]).stat().st_size,
            "sha256": _sha((bundle / entry["path"]).read_bytes()),
        }
        for entry in manifest["files"]
    ]
    manifest["collection"]["configuration_setup_hash"] = _sha(
        (bundle / "configuration-setup.json").read_bytes()
    )
    (bundle / "manifest.json").write_bytes(canonical_json_bytes(manifest))
    (bundle / "COMPLETE").write_bytes(
        f"apex-research-complete/v1\n{_sha((bundle / 'manifest.json').read_bytes())}\n".encode("utf-8")
    )


def build_recorder_bundle(destination: Path, *, track_surface: int | None = None) -> Path:
    """Copy the recorder fixture, optionally forcing a track_surface value.

    `track_surface` lets a test supply an enumeration value the declared dictionary does not
    define, proving an unknown simulator value never acquires a meaning.
    """
    shutil.copytree(FIXTURE, destination)
    if track_surface is not None:
        rows = (destination / "samples.csv").read_text(encoding="utf-8").splitlines()
        index = RECORDER_COLUMNS.index("track_surface")
        rebuilt = [rows[0]]
        for row in rows[1:]:
            columns = row.split(",")
            columns[index] = str(track_surface)
            rebuilt.append(",".join(columns))
        (destination / "samples.csv").write_text("\n".join(rebuilt) + "\n", encoding="utf-8")
        rebind(destination)
    return destination


def collection_record(bundle: Path, destination: Path) -> Path:
    """Build the Labs-side operator record that binds this exact bundle."""
    record = read_json(FIXTURE_COLLECTION)
    manifest = read_json(bundle / "manifest.json")
    session = manifest["session"]
    record["dataset_id"] = "synthetic-recorder-conformance"
    record["participant"]["pseudonymous_participant_id"] = session["participant_pseudonym"]
    record["source_bundle"] = {
        "schema_version": "apex-research-session-export/1.0.0",
        "sha256": _sha((bundle / "manifest.json").read_bytes()),
    }
    record["session_identity"] = {
        "simulator": session["simulator"]["id"],
        "car": session["car"]["id"],
        "track": session["track"]["id"],
        "layout": session["track"]["layout"],
        "confirmation_method": "synthetic recorder conformance fixture",
    }
    destination.write_bytes(canonical_json_bytes(record))
    return destination
