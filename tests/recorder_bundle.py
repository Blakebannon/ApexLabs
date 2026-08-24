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

import json
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


def coaching_events(delivered: int, provenance: str = "recorded_at_append") -> list[dict]:
    """Authorization/receipt pairs plus the authoritative evidence summary.

    A coached recording without the summary is refused by Labs before any rule under
    test is reached, so a fixture without it would prove nothing.
    """
    events: list[dict] = []
    sequence = 1
    stamp = 100.0
    for index in range(delivered):
        for kind in ("coaching-directive-authorized", "coaching-delivery-receipt"):
            data: dict = {"directive_ref": f"ref-{index:04d}", "observed_utc_provenance": provenance}
            if kind == "coaching-delivery-receipt":
                data["outcome"] = "Delivered"
            else:
                data["message_key"] = "objective/brake-earlier-t7/practice"
            events.append({
                "schema_version": "apex-research-event/1.0.0",
                "sequence": sequence,
                "observed_utc": f"2026-10-05T10:{index // 60:02d}:{index % 60:02d}.0000000Z",
                "session_time_s": stamp,
                "kind": kind,
                "data": data,
            })
            sequence += 1
            stamp += 1.0
    events.append({
        "schema_version": "apex-research-event/1.0.0",
        "sequence": sequence,
        "observed_utc": "2026-10-05T10:29:59.0000000Z",
        "session_time_s": stamp,
        "kind": "coaching-evidence-summary",
        "data": {
            "authorization_count": delivered,
            "decision_count": delivered,
            "delivery_receipt_count": delivered,
            "source": "authoritative committed coaching event stream",
            "source_direct_identifiers_copied": False,
            "events_with_recorded_utc": delivered * 2,
            "events_without_recorded_utc": 0,
            "observed_utc_policy": "coaching-observed-utc/1.1.0",
            "observed_utc_provenance": provenance,
        },
    })
    return events


def build_protocol_block_bundle(
    destination: Path,
    *,
    protocol_identity: str,
    block_id: str,
    condition_id: str,
    participant: str,
    coaching_state: str = "enabled",
    measured: str = "practice",
    measured_raw: str = "Practice",
    car: str = "toyotagr86",
    track: str = "oulton international",
    layout: str = "International",
    minutes: float = 30.0,
    delivered: int = 12,
    classification: str = "private",
    source_revision: str = "a" * 40,
    simulator_version: str = "2026.07.17.02 RELEASE",
    setup_hash: str | None = None,
) -> Path:
    """A REAL-classification bundle carrying a prospective protocol block assignment.

    Built from the committed recorder bytes and re-sealed, so a product change to the
    sample columns or file inventory breaks callers here rather than in a live
    campaign. The default `classification` is `private`, NOT `synthetic`: a synthetic
    bundle skips protocol binding entirely during ingestion, which is precisely the
    path that must not be used to claim the protocol-bound pipeline works.
    """
    shutil.copytree(FIXTURE, destination)

    manifest = read_json(destination / "manifest.json")
    manifest["session"]["participant_pseudonym"] = participant
    manifest["session"]["car"]["id"] = car
    manifest["session"]["track"]["id"] = track
    manifest["session"]["track"]["layout"] = layout
    manifest["session"]["simulator"]["version"] = simulator_version
    manifest["session"]["start_utc"] = "2026-10-05T10:00:00.0000000Z"
    whole = int(minutes)
    seconds = int(round((minutes - whole) * 60))
    manifest["session"]["end_utc"] = f"2026-10-05T10:{whole:02d}:{seconds:02d}.0000000Z"
    manifest["privacy"]["classification"] = classification
    manifest["collection"]["protocol_identity"] = protocol_identity
    (destination / "manifest.json").write_bytes(canonical_json_bytes(manifest))

    metadata = read_json(destination / "recorder-metadata.json")
    metadata["recorder"]["source_revision"] = source_revision
    metadata["privacy"]["classification"] = classification
    metadata["collection"] = {
        "protocol_identity": protocol_identity,
        "experimental_block_id": block_id,
        "condition_id": condition_id,
        "coaching_state": coaching_state,
        "session_type": measured,
        "measured_session_type": measured,
        "measured_session_type_raw": measured_raw,
        "measured_session_type_policy": "research-measured-session-type/1.0.0",
        "operator_condition_rewritten": False,
        "condition_contradicts_measured_session_type": False,
        "block_contradicts_measured_session_type": False,
    }
    (destination / "recorder-metadata.json").write_bytes(canonical_json_bytes(metadata))

    existing = [
        json.loads(line)
        for line in (destination / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    events = [existing[0]]
    events[0]["data"] = {
        "block_id": block_id,
        "coaching_state": coaching_state,
        "condition_id": condition_id,
        "protocol_identity": protocol_identity,
    }
    if coaching_state == "enabled":
        events += coaching_events(delivered)
    (destination / "events.jsonl").write_text(
        "".join(canonical_json_bytes(event).decode("utf-8") for event in events),
        encoding="utf-8", newline="",
    )

    metadata = read_json(destination / "recorder-metadata.json")
    metadata["metrics"]["events_written"] = len(events)
    (destination / "recorder-metadata.json").write_bytes(canonical_json_bytes(metadata))

    if setup_hash is not None:
        manifest = read_json(destination / "manifest.json")
        manifest["collection"]["configuration_setup_hash"] = setup_hash
        (destination / "manifest.json").write_bytes(canonical_json_bytes(manifest))

    rebind(destination)
    return destination
