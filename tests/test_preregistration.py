from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from _support import DATASET_MANIFEST, DEMO_PROTOCOL, ROOT, copy_fixture

from apex_labs.errors import ContractValidationError, IntegrityError
from apex_labs.experiments import (
    create_protocol_amendment,
    freeze_protocol,
    verify_protocol_amendment,
    verify_protocol_freeze,
)
from apex_labs.ingestion import ingest_dataset
from apex_labs.io import read_json, write_json


def synthetic_code_identity() -> dict:
    return {
        "package_version": "0.1.1",
        "git_commit": "UNCOMMITTED",
        "git_state": "uncommitted",
        "code_and_schema_sha256": "1" * 64,
        "schema_sha256": {"contracts/v1/test.schema.json": "2" * 64},
    }


def freeze(path: Path, registry: Path, **overrides) -> Path:
    arguments = {
        "frozen_at": "2026-08-19T00:00:00Z",
        "strategy": "not_applicable",
        "method": "Deterministic test; no participant assignment",
        "seed": None,
        "schedule_id": "not-applicable",
        "schedule": [],
        "code_identity": synthetic_code_identity(),
    }
    arguments.update(overrides)
    return freeze_protocol(path, registry, **arguments)


class PreregistrationTests(unittest.TestCase):
    def test_freeze_binds_protocol_code_time_and_randomization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            snapshot_path = freeze(DEMO_PROTOCOL, Path(directory) / "registry")
            snapshot = verify_protocol_freeze(read_json(snapshot_path))
            self.assertEqual("synthetic-mechanics-demo-protocol", snapshot["protocol_id"])
            self.assertEqual("not-applicable", snapshot["randomization"]["schedule_id"])
            self.assertEqual(
                read_json(DEMO_PROTOCOL)["apex_labs_source_commit"],
                snapshot["source_commit"],
            )
            self.assertEqual("2026-08-19T00:00:00Z", snapshot["frozen_at"])

    def test_frozen_content_mutation_and_same_version_rewrite_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry = Path(directory) / "registry"
            snapshot_path = freeze(DEMO_PROTOCOL, registry)
            original = snapshot_path.read_bytes()
            mutated = read_json(snapshot_path)
            mutated["protocol"]["hypothesis"] = "rewritten after collection"
            with self.assertRaises(ContractValidationError):
                verify_protocol_freeze(mutated)
            with self.assertRaises(ContractValidationError):
                freeze(DEMO_PROTOCOL, registry)
            self.assertEqual(original, snapshot_path.read_bytes())

    def test_protocol_change_requires_a_new_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            registry = base / "registry"
            first = freeze(DEMO_PROTOCOL, registry)
            protocol = read_json(DEMO_PROTOCOL)
            protocol["version"] = "1.0.1"
            changed = base / "protocol-v1.0.1.json"
            write_json(changed, protocol)
            second = freeze(changed, registry)
            self.assertNotEqual(first.parent, second.parent)
            self.assertNotEqual(
                read_json(first)["freeze_sha256"], read_json(second)["freeze_sha256"]
            )

    def test_amendments_are_append_only_hash_bound_and_chainable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            snapshot_path = freeze(DEMO_PROTOCOL, base / "freezes")
            original_snapshot = snapshot_path.read_bytes()
            first = create_protocol_amendment(
                snapshot_path,
                base / "amendments",
                amendment_id="demo-amendment",
                version="1.0.0",
                created_at="2026-08-19T01:00:00Z",
                source_commit="UNCOMMITTED",
                reason="Clarify a documentation-only note without changing the frozen protocol",
                changes=[
                    {
                        "field_path": "notes[0]",
                        "before_sha256": "3" * 64,
                        "after_value": "Clarified note",
                        "rationale": "Make the mechanics-only boundary explicit",
                    }
                ],
                impact_assessment="No collection or analysis behavior changes.",
                requires_new_protocol_version=False,
            )
            first_value = verify_protocol_amendment(read_json(first))
            self.assertEqual(original_snapshot, snapshot_path.read_bytes())
            with self.assertRaises(ContractValidationError):
                create_protocol_amendment(
                    snapshot_path,
                    base / "amendments",
                    amendment_id="demo-amendment",
                    version="1.0.0",
                    created_at="2026-08-19T01:00:00Z",
                    source_commit="UNCOMMITTED",
                    reason="attempted rewrite",
                    changes=[{"field_path": "notes[0]", "before_sha256": "3" * 64, "after_value": "x", "rationale": "x"}],
                    impact_assessment="rewrite",
                    requires_new_protocol_version=False,
                )
            second = create_protocol_amendment(
                snapshot_path,
                base / "amendments",
                amendment_id="demo-amendment",
                version="1.0.1",
                created_at="2026-08-19T02:00:00Z",
                source_commit="UNCOMMITTED",
                reason="Record a second explicit clarification",
                changes=[{"field_path": "notes[1]", "before_sha256": "4" * 64, "after_value": "Clarified", "rationale": "Audit history"}],
                impact_assessment="No collection or analysis behavior changes.",
                requires_new_protocol_version=False,
                prior_amendments=[
                    {
                        "amendment_id": first_value["amendment_id"],
                        "version": first_value["version"],
                        "amendment_sha256": first_value["amendment_sha256"],
                    }
                ],
            )
            self.assertEqual(1, len(verify_protocol_amendment(read_json(second))["prior_amendments"]))
            corrupted = read_json(second)
            corrupted["impact_assessment"] = "silently altered"
            with self.assertRaises(ContractValidationError):
                verify_protocol_amendment(corrupted)

    def test_randomized_freeze_requires_seed_or_schedule(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ContractValidationError):
                freeze(
                    DEMO_PROTOCOL,
                    Path(directory) / "registry",
                    strategy="randomized",
                )

    def test_real_freeze_requires_matching_clean_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            protocol = read_json(DEMO_PROTOCOL)
            protocol["synthetic"] = False
            protocol["apex_labs_source_commit"] = "1234567"
            path = base / "real-protocol.json"
            write_json(path, protocol)
            dirty = synthetic_code_identity()
            dirty.update({"git_commit": "1234567", "git_state": "dirty"})
            with self.assertRaises(IntegrityError):
                freeze(path, base / "registry", code_identity=dirty)

    def test_dataset_must_link_exact_frozen_protocol_and_schedule(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = copy_fixture(Path(directory) / "source")
            manifest = read_json(manifest_path)
            manifest["collection_context"]["protocol_snapshot"]["schedule_sha256"] = "f" * 64
            write_json(manifest_path, manifest)
            with self.assertRaises(IntegrityError):
                ingest_dataset(manifest_path, Path(directory) / "output", project_root=ROOT)


if __name__ == "__main__":
    unittest.main()
