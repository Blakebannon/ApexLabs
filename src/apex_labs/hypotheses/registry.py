"""Append-only, hash-chained hypothesis lifecycle.

A hypothesis moves `generated -> analysis_ready -> tested -> ...`. States are
never skipped, transitions are never rewritten, and the current state is
recomputed by replaying the chain rather than read from a stored summary.

Where a hypothesis came from is recorded and never confers authority. A
deterministic search, a person, and a language model can all propose one; none
of them is evidence, and only a completed, independently verified analysis run
can carry a hypothesis into an evidence-bearing state.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from apex_labs.errors import IntegrityError, LifecycleError
from apex_labs.io import read_json, write_json
from apex_labs.provenance import apex_labs_code_identity, require_research_code_identity
from apex_labs.schemas import (
    hypothesis_hash,
    transition_hash,
    validate_hypothesis,
    validate_hypothesis_transition,
)
from apex_labs.schemas.science_vocabulary import (
    EVIDENCE_BEARING_STATES,
    HYPOTHESIS_TRANSITIONS,
)
from apex_labs.schemas.versions import HYPOTHESIS, HYPOTHESIS_TRANSITION

EMPTY_BINDINGS: dict[str, Any] = {
    "protocol": None,
    "evidence_set": None,
    "analysis_definition": None,
    "analysis_run": None,
    "interpretation_ceiling": None,
    "multiple_comparison": None,
    "falsification": None,
    "replication": None,
}
UNREVIEWED: dict[str, Any] = {"state": "unreviewed", "reviewer_id": None, "reviewed_at": None, "notes": []}


def hypothesis_directory(registry_dir: Path, hypothesis_id: str) -> Path:
    return registry_dir / hypothesis_id


def _transition_path(directory: Path, sequence_index: int, from_state: str | None, to_state: str) -> Path:
    origin = from_state or "start"
    return directory / "transitions" / f"{sequence_index:04d}-{origin}-to-{to_state}.json"


def seal_hypothesis(hypothesis: dict[str, Any]) -> dict[str, Any]:
    """Stamp a hypothesis with its own canonical content hash."""
    sealed = {**hypothesis, "hypothesis_sha256": "0" * 64}
    sealed["hypothesis_sha256"] = hypothesis_hash(sealed)
    return validate_hypothesis(sealed)


def bindings_from_run(
    evidence: dict[str, Any], run: dict[str, Any], *, verified: bool
) -> dict[str, Any]:
    """Assemble the complete bindings an evidence-bearing transition requires."""
    definition = run["definition"]
    sensitivity = run["sensitivity"]
    return {
        "protocol": {
            "freeze_id": evidence["protocol"]["freeze_id"],
            "freeze_sha256": evidence["protocol"]["freeze_sha256"],
        },
        "evidence_set": {
            "evidence_set_id": evidence["evidence_set_id"],
            "version": evidence["version"],
            "evidence_set_sha256": evidence["evidence_set_sha256"],
            "synthetic": evidence["synthetic"],
        },
        "analysis_definition": {
            "analysis_id": definition["analysis_id"],
            "version": definition["version"],
            "definition_sha256": run["definition_sha256"],
            "classification": definition["classification"],
        },
        "analysis_run": {
            "run_id": run["run_id"],
            "run_sha256": run["run_sha256"],
            "analysis_state": run["analysis_state"],
            "verified": verified,
            "synthetic": run["synthetic"],
        },
        "interpretation_ceiling": run["interpretation"]["effective_ceiling"],
        "multiple_comparison": {
            "family_id": run["multiplicity"]["family_id"],
            "correction": run["multiplicity"]["correction"],
            "member_count": len(run["multiplicity"]["members"]),
        },
        "falsification": {
            "tests_run": len(sensitivity),
            "fragile_count": sum(1 for item in sensitivity if item["outcome"] == "fragile"),
        },
        "replication": {
            "state": definition["replication_policy"]["state"],
            "scope": definition["replication_policy"]["required_scope"],
        },
    }


def plan_bindings(
    evidence: dict[str, Any], analysis_definition: dict[str, Any], definition_sha256: str
) -> dict[str, Any]:
    """Bindings for `analysis_ready`: everything frozen, but no run yet."""
    return {
        **EMPTY_BINDINGS,
        "protocol": {
            "freeze_id": evidence["protocol"]["freeze_id"],
            "freeze_sha256": evidence["protocol"]["freeze_sha256"],
        },
        "evidence_set": {
            "evidence_set_id": evidence["evidence_set_id"],
            "version": evidence["version"],
            "evidence_set_sha256": evidence["evidence_set_sha256"],
            "synthetic": evidence["synthetic"],
        },
        "analysis_definition": {
            "analysis_id": analysis_definition["analysis_id"],
            "version": analysis_definition["version"],
            "definition_sha256": definition_sha256,
            "classification": analysis_definition["classification"],
        },
    }


def register_hypothesis(
    hypothesis: dict[str, Any],
    registry_dir: Path,
    *,
    recorded_at: str,
    project_root: Path | None = None,
    code_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a hypothesis and its opening `generated` transition."""
    sealed = seal_hypothesis(hypothesis)
    identity = code_identity or apex_labs_code_identity(project_root)
    require_research_code_identity(identity, synthetic=sealed["synthetic"])
    directory = hypothesis_directory(registry_dir, sealed["hypothesis_id"])
    if directory.exists():
        raise LifecycleError(
            f"Hypothesis {sealed['hypothesis_id']} already exists; a lifecycle is never restarted in place"
        )
    (directory / "transitions").mkdir(parents=True)
    write_json(directory / "hypothesis.json", sealed)
    transition = _seal_transition(
        {
            "schema_version": HYPOTHESIS_TRANSITION,
            "transition_id": f"{sealed['hypothesis_id']}.t0000",
            "sequence_index": 0,
            "hypothesis_id": sealed["hypothesis_id"],
            "hypothesis_version": sealed["version"],
            "hypothesis_sha256": sealed["hypothesis_sha256"],
            "recorded_at": recorded_at,
            "synthetic": sealed["synthetic"],
            "from_state": None,
            "to_state": "generated",
            "previous_transition_sha256": None,
            "transition_sha256": "0" * 64,
            "rationale": (
                f"Hypothesis proposed by {sealed['generation']['source']}: {sealed['generation']['detail']} "
                "A proposal is not evidence."
            ),
            "bindings": dict(EMPTY_BINDINGS),
            "reviewer": dict(UNREVIEWED),
            "code_identity": identity,
        }
    )
    write_json(_transition_path(directory, 0, None, "generated"), transition)
    return sealed


def _seal_transition(transition: dict[str, Any]) -> dict[str, Any]:
    sealed = {**transition, "transition_sha256": "0" * 64}
    sealed["transition_sha256"] = transition_hash(sealed)
    return validate_hypothesis_transition(sealed)


def load_transitions(registry_dir: Path, hypothesis_id: str) -> list[dict[str, Any]]:
    directory = hypothesis_directory(registry_dir, hypothesis_id)
    if not directory.is_dir():
        raise LifecycleError(f"Hypothesis {hypothesis_id} is not registered")
    paths = sorted((directory / "transitions").glob("*.json"))
    if not paths:
        raise LifecycleError(f"Hypothesis {hypothesis_id} has no lifecycle history")
    return [read_json(path) for path in paths]


def replay(registry_dir: Path, hypothesis_id: str) -> dict[str, Any]:
    """Recompute the current state by replaying and re-verifying the chain."""
    directory = hypothesis_directory(registry_dir, hypothesis_id)
    if not directory.is_dir():
        raise LifecycleError(f"Hypothesis {hypothesis_id} is not registered")
    hypothesis = validate_hypothesis(read_json(directory / "hypothesis.json"))
    if hypothesis["hypothesis_sha256"] != hypothesis_hash(hypothesis):
        raise IntegrityError("Hypothesis content does not match its recorded hash")
    transitions = [validate_hypothesis_transition(item) for item in load_transitions(registry_dir, hypothesis_id)]
    state: str | None = None
    previous_hash: str | None = None
    for index, transition in enumerate(transitions):
        if transition["sequence_index"] != index:
            raise IntegrityError(
                f"Transition {index} declares sequence index {transition['sequence_index']}; the history is not contiguous"
            )
        if transition["hypothesis_id"] != hypothesis_id:
            raise IntegrityError("A transition in this history targets a different hypothesis")
        if transition["hypothesis_sha256"] != hypothesis["hypothesis_sha256"]:
            raise IntegrityError(
                "A transition is bound to different hypothesis content; hypothesis text cannot be rewritten under its history"
            )
        if transition["transition_sha256"] != transition_hash(transition):
            raise IntegrityError(f"Transition {index} hash does not match its content")
        if transition["from_state"] != state:
            raise IntegrityError(
                f"Transition {index} claims to start from {transition['from_state']!r} but the history is at {state!r}"
            )
        if transition["previous_transition_sha256"] != previous_hash:
            raise IntegrityError(f"Transition {index} does not chain to its predecessor")
        if state is not None and transition["to_state"] not in HYPOTHESIS_TRANSITIONS[state]:
            raise IntegrityError(
                f"Transition {index} takes a state path {state!r} does not permit"
            )
        state = transition["to_state"]
        previous_hash = transition["transition_sha256"]
    return {
        "hypothesis": hypothesis,
        "transitions": transitions,
        "state": state,
        "head_transition_sha256": previous_hash,
    }


def record_transition(
    registry_dir: Path,
    hypothesis_id: str,
    *,
    to_state: str,
    rationale: str,
    recorded_at: str,
    bindings: dict[str, Any] | None = None,
    reviewer: dict[str, Any] | None = None,
    project_root: Path | None = None,
    code_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append one lifecycle transition after re-verifying the whole history."""
    history = replay(registry_dir, hypothesis_id)
    hypothesis = history["hypothesis"]
    current = history["state"]
    if to_state not in HYPOTHESIS_TRANSITIONS[current]:
        permitted = sorted(HYPOTHESIS_TRANSITIONS[current])
        raise LifecycleError(
            f"{current!r} does not permit a transition to {to_state!r}; permitted next states are "
            f"{permitted or 'none: this state is terminal'}"
        )
    identity = code_identity or apex_labs_code_identity(project_root)
    require_research_code_identity(identity, synthetic=hypothesis["synthetic"])
    sequence_index = len(history["transitions"])
    transition = _seal_transition(
        {
            "schema_version": HYPOTHESIS_TRANSITION,
            "transition_id": f"{hypothesis_id}.t{sequence_index:04d}",
            "sequence_index": sequence_index,
            "hypothesis_id": hypothesis_id,
            "hypothesis_version": hypothesis["version"],
            "hypothesis_sha256": hypothesis["hypothesis_sha256"],
            "recorded_at": recorded_at,
            "synthetic": hypothesis["synthetic"],
            "from_state": current,
            "to_state": to_state,
            "previous_transition_sha256": history["head_transition_sha256"],
            "transition_sha256": "0" * 64,
            "rationale": rationale,
            "bindings": {**EMPTY_BINDINGS, **(bindings or {})},
            "reviewer": reviewer or dict(UNREVIEWED),
            "code_identity": identity,
        }
    )
    directory = hypothesis_directory(registry_dir, hypothesis_id)
    path = _transition_path(directory, sequence_index, current, to_state)
    if path.exists():
        raise LifecycleError(f"Transition {path.name} already exists; lifecycle history is append-only")
    write_json(path, transition)
    return transition


def verify_registry(registry_dir: Path) -> dict[str, Any]:
    """Replay every registered hypothesis and report its recomputed state."""
    if not registry_dir.is_dir():
        raise LifecycleError(f"Hypothesis registry not found: {registry_dir}")
    entries = []
    for directory in sorted(path for path in registry_dir.iterdir() if path.is_dir()):
        history = replay(registry_dir, directory.name)
        entries.append(
            {
                "hypothesis_id": directory.name,
                "version": history["hypothesis"]["version"],
                "state": history["state"],
                "transitions": len(history["transitions"]),
                "generation_source": history["hypothesis"]["generation"]["source"],
                "evidence_bearing": history["state"] in EVIDENCE_BEARING_STATES,
                "synthetic": history["hypothesis"]["synthetic"],
            }
        )
    return {"valid": True, "registry": str(registry_dir), "hypotheses": entries}


HYPOTHESIS_CONTRACT = HYPOTHESIS
