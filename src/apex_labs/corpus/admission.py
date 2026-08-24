"""The automated corpus-admission gate.

A bundle that merely validates is not corpus evidence. Validation proves the
bundle is internally consistent and unmutated; admission proves it is *the
recording the frozen protocol asked for*. The 2026-08-23 livestream is the
argument for the distinction: every completed bundle there passed both product
and Labs validation, and two of them still carried an operator condition label
that named the wrong session type. Nothing refused them, because nothing was
checking a plan.

Every check here fails CLOSED. A missing declaration is a refusal, never a pass:
a corpus is the one place where "we could not tell" and "it was fine" must not
produce the same outcome.

The gate is deliberately free of any product dependency and never writes to the
bundle. It reads a completed bundle, a verified protocol freeze, and the frozen
schedule, and returns a verdict.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from apex_labs.errors import ContractValidationError
from apex_labs.experiments.preregistration import verify_protocol_freeze
from apex_labs.ingestion.apex_research import audit_research_bundle
from apex_labs.io import read_json

#: Every coaching event in a corpus bundle must carry this provenance. Milestone
#: 55B made a truthful append-time UTC durable; a corpus must not rest on import
#: time, so a legacy-timestamped stream is refused rather than accepted with a note.
REQUIRED_OBSERVED_UTC_PROVENANCE = "recorded_at_append"

#: Session-type token the recorder writes for a measured iRacing session type.
_SESSION_TYPE_TOKENS = {"unknown", "offline-testing", "practice", "qualifying", "race"}

_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")


@dataclass(frozen=True)
class AdmissionFinding:
    """One reason a bundle is refused, or one recorded deviation."""

    code: str
    severity: str  # "refusal" | "deviation"
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "severity": self.severity, "message": self.message}


def _refuse(findings: list[AdmissionFinding], code: str, message: str) -> None:
    findings.append(AdmissionFinding(code=code, severity="refusal", message=message))


def _deviate(findings: list[AdmissionFinding], code: str, message: str) -> None:
    findings.append(AdmissionFinding(code=code, severity="deviation", message=message))


def _schedule_index(freeze: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Frozen schedule keyed by block id.

    Keyed by block id rather than by ordinal because the block id is the only
    schedule field the recorder actually writes into the bundle. Matching on
    anything the bundle does not carry would mean trusting the operator's word
    about which recording this is.
    """
    index: dict[str, dict[str, Any]] = {}
    for entry in freeze["randomization"]["schedule"]:
        if not isinstance(entry, dict) or "block_id" not in entry:
            raise ContractValidationError(
                "Frozen schedule entries must be objects carrying block_id for corpus admission"
            )
        block_id = entry["block_id"]
        if block_id in index:
            raise ContractValidationError(f"Frozen schedule repeats block id {block_id!r}")
        index[block_id] = entry
    if not index:
        raise ContractValidationError("Frozen schedule is empty; nothing can be admitted against it")
    return index


def _coaching_events(root: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with (root / "events.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            import json

            event = json.loads(line)
            if isinstance(event, dict) and str(event.get("kind", "")).startswith("coaching"):
                events.append(event)
    return events


def coaching_activity_in_window(
    apex_data_root: Path, start_utc: str, end_utc: str
) -> dict[str, Any]:
    """Count coaching events the Apex store recorded inside a wall-clock window.

    This is the control-arm verifier, and it is only possible because Milestone
    55B put a truthful append-time UTC on every persisted coaching event. Before
    that, every event carried the finalization instant and overlap with a
    recording window was unanswerable.

    Why it is needed: ``--coaching disabled`` is a RECORDER declaration. It makes
    the recorder skip the evidence import and write the disabled marker; it does
    NOT stop Apex Sim Coach from coaching. An operator who forgets to press Stop
    Coaching produces a bundle that looks like a clean control while the driver
    was in fact being coached. The bundle alone cannot reveal that. The store can.

    Read-only, immutable, and total: an absent or unreadable store reports
    ``readable: False`` rather than raising, so the caller can refuse for a stated
    reason instead of crashing mid-corpus.
    """
    import sqlite3
    from datetime import datetime

    events_db = apex_data_root / "coaching" / "coaching-events.db"
    result: dict[str, Any] = {
        "readable": False, "recorded_utc_available": False,
        "events_in_window": 0, "delivered_in_window": 0,
    }
    if not events_db.is_file():
        return result

    def parse(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    try:
        start, end = parse(start_utc), parse(end_utc)
        connection = sqlite3.connect(f"file:{events_db}?mode=ro&immutable=1", uri=True)
    except Exception:  # noqa: BLE001
        return result

    try:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(Events)")}
        result["readable"] = True
        if "RecordedUtc" not in columns:
            # A pre-Milestone-55B store cannot answer the question at all.
            return result
        result["recorded_utc_available"] = True
        for recorded, payload in connection.execute(
            "SELECT RecordedUtc, Payload FROM Events WHERE RecordedUtc IS NOT NULL"
        ):
            try:
                stamp = parse(recorded)
            except Exception:  # noqa: BLE001
                continue
            if not (start <= stamp <= end):
                continue
            result["events_in_window"] += 1
            if '"receipt-recorded"' in payload and '"Delivered"' in payload:
                result["delivered_in_window"] += 1
    finally:
        connection.close()
    return result


def coaching_binding_since(apex_data_root: Path, since_utc: str) -> dict[str, Any]:
    """Report which coaching sessions the Apex store has written since an instant.

    This exists for exactly one operational moment: the Practice -> Qualifying
    rollover. The recorder's own binding probe latches after it reports Bound once
    (``CoachingBindingProbe.Evaluate`` returns Quiet forever once
    ``_reportedBound`` is set), so on the far side of a transition it prints
    nothing at all -- neither the bound line nor a warning. The operator would
    otherwise have no console condition to wait for, and stopping the recorder
    early finalizes the rolled-over bundle as INCOMPLETE.

    Read-only, immutable, and total, on the same terms as
    :func:`coaching_activity_in_window`: an absent or unreadable store reports
    ``readable: False`` rather than raising. It answers a question, it never
    decides anything, and it touches nothing.
    """
    import sqlite3
    from datetime import datetime

    events_db = apex_data_root / "coaching" / "coaching-events.db"
    result: dict[str, Any] = {
        "readable": False,
        "recorded_utc_available": False,
        "since_utc": since_utc,
        "sessions_since": [],
        "delivered_since": 0,
        "binding_ready": False,
    }
    if not events_db.is_file():
        return result

    def parse(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    try:
        since = parse(since_utc)
        connection = sqlite3.connect(f"file:{events_db}?mode=ro&immutable=1", uri=True)
    except Exception:  # noqa: BLE001
        return result

    try:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(Events)")}
        result["readable"] = True
        if "RecordedUtc" not in columns or "SessionId" not in columns:
            # A pre-Milestone-55B store cannot place an event in wall-clock time.
            return result
        result["recorded_utc_available"] = True

        sessions: dict[str, dict[str, Any]] = {}
        for session_id, recorded, payload in connection.execute(
            "SELECT SessionId, RecordedUtc, Payload FROM Events WHERE RecordedUtc IS NOT NULL"
        ):
            try:
                stamp = parse(recorded)
            except Exception:  # noqa: BLE001
                continue
            if stamp < since:
                continue
            row = sessions.setdefault(
                session_id,
                {"session_id": session_id, "events": 0, "delivered": 0,
                 "first_utc": recorded, "last_utc": recorded},
            )
            row["events"] += 1
            row["last_utc"] = max(str(row["last_utc"]), recorded)
            row["first_utc"] = min(str(row["first_utc"]), recorded)
            if '"receipt-recorded"' in payload and '"Delivered"' in payload:
                row["delivered"] += 1
    finally:
        connection.close()

    ordered = sorted(sessions.values(), key=lambda row: str(row["first_utc"]))
    result["sessions_since"] = ordered
    result["delivered_since"] = sum(int(row["delivered"]) for row in ordered)
    # A delivered receipt is the strongest available proof that a coaching session
    # exists for the new iRacing session AND is past its observation window: Apex
    # cannot deliver a cue for a session it has not created and bound.
    result["binding_ready"] = any(int(row["delivered"]) > 0 for row in ordered)
    return result


def evaluate_bundle(
    bundle_root: Path,
    freeze: dict[str, Any],
    *,
    schedule: dict[str, dict[str, Any]] | None = None,
    apex_data_root: Path | None = None,
) -> dict[str, Any]:
    """Evaluate one completed bundle against a verified frozen protocol.

    Returns a verdict document. Raises only when the freeze itself is unusable —
    a bad bundle is a refusal with reasons, not an exception, because the
    operator needs every reason at once rather than the first one.
    """
    index = schedule if schedule is not None else _schedule_index(freeze)
    findings: list[AdmissionFinding] = []
    protocol = freeze["protocol"]

    # ---- the bundle must first be a valid, unmutated, completed bundle --------
    try:
        audit = audit_research_bundle(bundle_root)
    except Exception as error:  # noqa: BLE001 - every failure mode is a refusal
        return {
            "bundle": str(bundle_root),
            "admitted": False,
            "block_id": None,
            "findings": [
                AdmissionFinding(
                    code="bundle-invalid",
                    severity="refusal",
                    message=f"Bundle failed Apex Labs validation ({type(error).__name__}): {error}",
                ).as_dict()
            ],
        }

    manifest = audit.manifest
    metadata = audit.metadata
    collection = metadata.get("collection", {})
    session = manifest["session"]

    block_id = collection.get("experimental_block_id")
    entry = index.get(block_id)

    # ---- is this recording in the plan at all? --------------------------------
    if entry is None:
        _refuse(
            findings,
            "block-not-in-schedule",
            f"Block id {block_id!r} does not appear in frozen schedule "
            f"{freeze['randomization']['schedule_id']!r}. A corpus admits only recordings the frozen "
            "schedule asked for.",
        )
        return _verdict(bundle_root, block_id, findings, audit, freeze)

    # ---- protocol identity ----------------------------------------------------
    if collection.get("protocol_identity") != protocol["experiment_id"]:
        _refuse(
            findings,
            "protocol-identity-mismatch",
            f"Recorder protocol identity {collection.get('protocol_identity')!r} is not the frozen "
            f"protocol {protocol['experiment_id']!r}.",
        )

    # ---- arm and condition must be the ones the schedule assigned -------------
    if collection.get("condition_id") != entry["condition_id"]:
        _refuse(
            findings,
            "condition-mismatch",
            f"Block {block_id!r} recorded condition {collection.get('condition_id')!r} but the frozen "
            f"schedule assigns {entry['condition_id']!r}. Assignment is not the operator's to change.",
        )

    if collection.get("coaching_state") != entry["coaching_state"]:
        _refuse(
            findings,
            "coaching-state-mismatch",
            f"Block {block_id!r} recorded coaching_state {collection.get('coaching_state')!r} but the "
            f"frozen schedule assigns {entry['coaching_state']!r}.",
        )

    # ---- measured session type is the observation, not the label --------------
    measured = collection.get("measured_session_type")
    if measured is None:
        _refuse(
            findings,
            "measured-session-type-absent",
            "recorder-metadata.json declares no measured_session_type. A corpus cannot stratify on a "
            "session type nobody measured; re-record with a build that reports it.",
        )
    elif measured not in _SESSION_TYPE_TOKENS:
        _refuse(
            findings,
            "measured-session-type-unknown-token",
            f"measured_session_type {measured!r} is not a recognised token.",
        )
    elif measured == "unknown":
        _refuse(
            findings,
            "measured-session-type-unknown",
            "The simulator reported no usable session type. An unknown stratum cannot enter a corpus "
            "that stratifies on session type.",
        )
    elif measured != entry["measured_session_type_required"]:
        _refuse(
            findings,
            "measured-session-type-mismatch",
            f"Block {block_id!r} measured session type {measured!r} but the frozen schedule requires "
            f"{entry['measured_session_type_required']!r}.",
        )

    # A label that contradicts the measurement is the exact 2026-08-23 failure.
    for field in ("condition_contradicts_measured_session_type", "block_contradicts_measured_session_type"):
        if collection.get(field) is True:
            _refuse(
                findings,
                "operator-label-contradicts-measurement",
                f"{field} is true: the operator label names a different session type than the simulator "
                "measured. This is the 2026-08-23 mislabel and it is refused, not annotated.",
            )

    # ---- car, track and layout ------------------------------------------------
    for bundle_value, planned_key, name in (
        (session["car"]["id"], "car", "car"),
        (session["track"]["id"], "track", "track"),
        (session["track"].get("layout"), "layout", "layout"),
    ):
        if bundle_value != entry[planned_key]:
            _refuse(
                findings,
                f"{name}-mismatch",
                f"Block {block_id!r} recorded {name} {bundle_value!r} but the frozen schedule requires "
                f"{entry[planned_key]!r}. Comparability is structural, not a judgement call.",
            )

    # ---- timestamp provenance: the M55 corpus-facing requirement --------------
    _check_timestamp_provenance(bundle_root, collection, findings)

    # ---- control arm: was Apex actually silent? -------------------------------
    if collection.get("coaching_state") == "disabled":
        _check_control_arm_was_truly_uncoached(
            apex_data_root, session, block_id, findings)

    # ---- capture integrity ----------------------------------------------------
    metrics = metadata.get("metrics", {})
    if metrics.get("events_dropped", 0):
        _refuse(
            findings,
            "events-dropped",
            f"{metrics['events_dropped']} evidence events were dropped. A completed bundle that lost "
            "evidence is not corpus material.",
        )
    offered = metrics.get("samples_offered") or 0
    dropped = metrics.get("samples_dropped_by_backpressure") or 0
    if offered and dropped / offered > 0.001:
        _refuse(
            findings,
            "excessive-sample-loss",
            f"{dropped} of {offered} samples were dropped by backpressure "
            f"({dropped / offered:.3%}), above the 0.1% corpus tolerance.",
        )

    # ---- duration against the plan --------------------------------------------
    _check_duration(session, entry, findings)

    # ---- the corpus is not a place for retrospective admission ----------------
    if manifest.get("privacy", {}).get("classification") == "synthetic":
        _refuse(findings, "synthetic-bundle", "A synthetic bundle can never enter a real corpus.")

    return _verdict(bundle_root, block_id, findings, audit, freeze)


def _check_timestamp_provenance(
    bundle_root: Path, collection: dict[str, Any], findings: list[AdmissionFinding]
) -> None:
    """Every coaching event must carry a truthful append-time UTC.

    Milestone 55B made this recoverable. Before it, every imported coaching event
    carried the finalization instant and a bundle could not say so. A corpus that
    accepted such a stream would be unable to state when anything happened, so a
    legacy-timestamped stream is refused rather than admitted with a caveat.
    """
    events = _coaching_events(bundle_root)
    if collection.get("coaching_state") == "disabled":
        # A control block carries the explicit disabled marker and no imported
        # stream. Requiring append-time provenance from events that were never
        # imported would refuse a correct control block.
        kinds = {event.get("kind") for event in events}
        if "coaching-disabled-control" not in kinds:
            _refuse(
                findings,
                "control-block-missing-disabled-marker",
                "A control block must carry the explicit coaching-disabled-control marker; delivery "
                "being absent is not the same as delivery being declared off.",
            )
        delivered = [
            event for event in events
            if event.get("kind") == "coaching-delivery-receipt"
            and (event.get("data") or {}).get("outcome") == "Delivered"
        ]
        if delivered:
            _refuse(
                findings,
                "control-block-delivered-cues",
                f"A control block recorded {len(delivered)} delivered cues. The manipulation failed; "
                "this is not a null result.",
            )
        return

    imported = [
        event for event in events
        if event.get("kind") not in {"coaching-disabled-control"}
    ]
    if not imported:
        _refuse(
            findings,
            "coached-block-no-coaching-evidence",
            "A coached block carries no coaching evidence at all.",
        )
        return

    delivered = [
        event for event in imported
        if event.get("kind") == "coaching-delivery-receipt"
        and (event.get("data") or {}).get("outcome") == "Delivered"
    ]
    if not delivered:
        _refuse(
            findings,
            "coached-block-no-delivered-cues",
            "A coached block delivered no cues at all. The manipulation did not happen, so the block "
            "is not a coached observation however valid the bundle is. This is the Race-stratum failure "
            "mode from 2026-08-23, where a whole session produced two cues.",
        )

    missing: list[str] = []
    legacy: list[str] = []
    for event in imported:
        data = event.get("data") or {}
        if "observed_utc_provenance" not in data:
            missing.append(str(event.get("kind")))
        elif data["observed_utc_provenance"] != REQUIRED_OBSERVED_UTC_PROVENANCE:
            legacy.append(str(event.get("kind")))

    if missing:
        _refuse(
            findings,
            "timestamp-provenance-absent",
            f"{len(missing)} coaching events declare no observed_utc_provenance. This bundle predates "
            "durable append-time UTC; its coaching timing is unrecoverable and it cannot enter a corpus.",
        )
    if legacy:
        _refuse(
            findings,
            "timestamp-provenance-legacy",
            f"{len(legacy)} coaching events are marked "
            f"{REQUIRED_OBSERVED_UTC_PROVENANCE!r}-absent (legacy stream). Their observed_utc is import "
            "time, not occurrence time, and a corpus cannot rest on it.",
        )

    # Ordering must be non-decreasing on the recorded clock.
    stamps = [event.get("observed_utc") for event in imported if isinstance(event.get("observed_utc"), str)]
    if any(not _ISO.match(value) for value in stamps):
        _refuse(findings, "timestamp-unparseable", "A coaching event carries an unparseable observed_utc.")
    elif stamps != sorted(stamps):
        _refuse(
            findings,
            "timestamp-not-monotonic",
            "Coaching observed_utc values decrease against committed order. Ordering authority is the "
            "event version; a decreasing stamp means the read-side clamp did not hold.",
        )


def _check_control_arm_was_truly_uncoached(
    apex_data_root: Path | None,
    session: dict[str, Any],
    block_id: str | None,
    findings: list[AdmissionFinding],
) -> None:
    """A control block must be silent in fact, not merely by declaration.

    The bundle of a control block is silent by construction: the recorder never
    opened the coaching store. So the bundle can never prove the driver was
    uncoached — only the Apex store can, and only since Milestone 55B gave its
    events a truthful append-time UTC.

    Without the store this is unverifiable, and unverifiable is refused. A corpus
    whose control arm rests on the operator remembering to press Stop Coaching is
    a corpus with no control arm.
    """
    if apex_data_root is None:
        _refuse(
            findings,
            "control-arm-unverified",
            f"Control block {block_id!r} cannot be verified without --apex-data-root. "
            "'--coaching disabled' is a recorder declaration, not a product control: it stops the "
            "recorder importing evidence, not Apex from coaching. Supply the Apex data root so the "
            "store can be asked whether anything was delivered during this recording.",
        )
        return

    activity = coaching_activity_in_window(
        apex_data_root, session["start_utc"], session["end_utc"])

    if not activity["readable"]:
        _refuse(
            findings,
            "control-arm-store-unreadable",
            f"The Apex coaching store under {apex_data_root} could not be read, so control block "
            f"{block_id!r} cannot be shown to have been uncoached.",
        )
        return

    if not activity["recorded_utc_available"]:
        _refuse(
            findings,
            "control-arm-store-predates-recorded-utc",
            "The Apex coaching store has no RecordedUtc column, so no event can be placed inside "
            "this recording's window. A pre-Milestone-55B store cannot support a control arm.",
        )
        return

    if activity["delivered_in_window"]:
        _refuse(
            findings,
            "control-arm-was-coached",
            f"The Apex store recorded {activity['delivered_in_window']} delivered cues inside control "
            f"block {block_id!r}'s wall-clock window. The driver was coached; this is a fabricated "
            "control, not a control.",
        )
    elif activity["events_in_window"]:
        _deviate(
            findings,
            "control-arm-coaching-session-active",
            f"The Apex store recorded {activity['events_in_window']} coaching events inside control "
            f"block {block_id!r}'s window but delivered nothing. Apex was running and observing. "
            "Recorded as a deviation: no cue reached the driver, but the control was not fully idle.",
        )


def _check_duration(
    session: dict[str, Any], entry: dict[str, Any], findings: list[AdmissionFinding]
) -> None:
    from datetime import datetime

    def parse(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    try:
        minutes = (parse(session["end_utc"]) - parse(session["start_utc"])).total_seconds() / 60.0
    except Exception:  # noqa: BLE001
        _refuse(findings, "duration-unreadable", "Session start/end timestamps could not be read.")
        return

    planned = float(entry["planned_minutes"])
    # A short block cannot be padded and a long one changes tyre and fuel state,
    # so both directions matter. 20% is wide enough for ordinary operator
    # variation and narrow enough that a mis-run recording is caught.
    if minutes < planned * 0.8:
        _refuse(
            findings,
            "recording-too-short",
            f"Recording ran {minutes:.1f} min against a planned {planned:.0f} min "
            f"(below the 80% floor). A short block yields too few clean laps to contribute.",
        )
    elif minutes > planned * 1.2:
        _deviate(
            findings,
            "recording-long",
            f"Recording ran {minutes:.1f} min against a planned {planned:.0f} min (above 120%). "
            "Recorded as a deviation: extra running changes tyre and fuel state across the pair.",
        )


def _verdict(
    bundle_root: Path,
    block_id: str | None,
    findings: list[AdmissionFinding],
    audit: Any,
    freeze: dict[str, Any],
) -> dict[str, Any]:
    refusals = [f for f in findings if f.severity == "refusal"]
    return {
        "bundle": str(bundle_root),
        "block_id": block_id,
        "session_id": audit.manifest["session"]["session_id"] if audit is not None else None,
        "manifest_sha256": audit.manifest_sha256 if audit is not None else None,
        "sample_count": audit.sample_count if audit is not None else None,
        "event_count": audit.event_count if audit is not None else None,
        "protocol_freeze_sha256": freeze["freeze_sha256"],
        "admitted": not refusals,
        "refusal_count": len(refusals),
        "deviation_count": len(findings) - len(refusals),
        "findings": [f.as_dict() for f in findings],
    }


def admit_corpus(
    bundle_roots: list[Path],
    freeze_path: Path,
    *,
    apex_data_root: Path | None = None,
) -> dict[str, Any]:
    """Evaluate every bundle and decide whether the corpus as a whole is admissible.

    A corpus is admissible only when every scheduled block is present exactly
    once and every one of them is individually admitted. Partial admission is
    deliberately not offered: a half-collected counterbalanced design is not a
    smaller version of the design, it is a different and unbalanced one.
    """
    freeze = verify_protocol_freeze(read_json(freeze_path))
    index = _schedule_index(freeze)

    results = [
        evaluate_bundle(root, freeze, schedule=index, apex_data_root=apex_data_root)
        for root in bundle_roots
    ]

    seen: dict[str, int] = {}
    for result in results:
        if result["block_id"]:
            seen[result["block_id"]] = seen.get(result["block_id"], 0) + 1

    corpus_findings: list[AdmissionFinding] = []
    missing = sorted(set(index) - set(seen))
    if missing:
        _refuse(
            corpus_findings,
            "schedule-incomplete",
            f"{len(missing)} scheduled blocks were not supplied: {missing[:5]}"
            + (" ..." if len(missing) > 5 else "")
            + ". A counterbalanced design is not admissible in part.",
        )
    duplicates = sorted(block for block, count in seen.items() if count > 1)
    if duplicates:
        _refuse(
            corpus_findings,
            "duplicate-block",
            f"Blocks supplied more than once: {duplicates}. Which recording is the evidence would be "
            "the analyst's choice, made after seeing the data.",
        )

    # One setup and one product build across the whole corpus, or the arms are
    # not comparable however well each individual bundle validates.
    _check_corpus_wide_identity(bundle_roots, corpus_findings)

    refused = [r for r in results if not r["admitted"]]
    admitted = not refused and not [f for f in corpus_findings if f.severity == "refusal"]

    return {
        "schema": "apex-labs.corpus-admission/v1-local",
        "protocol_id": freeze["protocol_id"],
        "protocol_version": freeze["protocol_version"],
        "freeze_sha256": freeze["freeze_sha256"],
        "schedule_id": freeze["randomization"]["schedule_id"],
        "schedule_sha256": freeze["randomization"]["schedule_sha256"],
        "scheduled_blocks": len(index),
        "supplied_bundles": len(results),
        "admitted_bundles": sum(1 for r in results if r["admitted"]),
        "refused_bundles": len(refused),
        "corpus_admitted": admitted,
        "corpus_findings": [f.as_dict() for f in corpus_findings],
        "bundles": results,
    }


def _check_corpus_wide_identity(bundle_roots: list[Path], findings: list[AdmissionFinding]) -> None:
    setups: set[str] = set()
    revisions: set[str] = set()
    simulators: set[str] = set()
    participants: set[str] = set()
    for root in bundle_roots:
        try:
            audit = audit_research_bundle(root)
        except Exception:  # noqa: BLE001 - already refused individually
            continue
        setups.add(audit.manifest["collection"]["configuration_setup_hash"])
        revisions.add(audit.metadata["recorder"]["source_revision"])
        simulators.add(audit.manifest["session"]["simulator"]["version"])
        participants.add(audit.manifest["session"]["participant_pseudonym"])

    for values, code, label in (
        (setups, "setup-varies", "car setup"),
        (revisions, "product-build-varies", "product source revision"),
        (simulators, "simulator-varies", "simulator version"),
        (participants, "participant-varies", "participant"),
    ):
        if len(values) > 1:
            _refuse(
                findings,
                code,
                f"The corpus spans {len(values)} distinct {label} identities. The frozen protocol holds "
                f"{label} constant, and missing or varying identity is never a match.",
            )
