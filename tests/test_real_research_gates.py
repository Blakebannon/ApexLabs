"""Gates that separate fabricated mechanics from real research.

Synthetic work may run from an uncommitted, dirty tree. Real evidence may not:
every entry point that produces a preserved artifact re-asks the same question
before it computes anything.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _support import BUILT_AT, ROOT, prepared_campaign, synthetic_hypothesis

from apex_labs.analysis import run_inferential_analysis
from apex_labs.errors import IntegrityError
from apex_labs.evidence import build_evidence_set
from apex_labs.hypotheses import register_hypothesis
from apex_labs.provenance import require_research_code_identity

DIRTY = {
    "package_version": "0.3.0",
    "git_commit": "0123456789abcdef0123456789abcdef01234567",
    "git_state": "dirty",
    "code_and_schema_sha256": "a" * 64,
    "schema_sha256": {"contracts/v1/evidence-set.schema.json": "b" * 64},
}
UNCOMMITTED = {**DIRTY, "git_commit": "UNCOMMITTED", "git_state": "uncommitted"}
CLEAN = {**DIRTY, "git_state": "clean"}


class CodeIdentityGuardTests(unittest.TestCase):
    def test_synthetic_mechanics_may_run_from_an_unclean_tree(self) -> None:
        for identity in (DIRTY, UNCOMMITTED, CLEAN):
            with self.subTest(state=identity["git_state"]):
                self.assertIsNone(require_research_code_identity(identity, synthetic=True))

    def test_real_research_requires_a_clean_committed_tree(self) -> None:
        for identity in (DIRTY, UNCOMMITTED):
            with self.subTest(state=identity["git_state"]):
                with self.assertRaises(IntegrityError) as error:
                    require_research_code_identity(identity, synthetic=False)
                self.assertIn("clean Apex Labs Git commit", str(error.exception))
        self.assertIsNone(require_research_code_identity(CLEAN, synthetic=False))


class EntryPointGuardTests(unittest.TestCase):
    """Every preserving entry point must ask the guard, not assume the answer."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._directory = tempfile.TemporaryDirectory(prefix="apex-labs-gate-tests-")
        cls.addClassCleanup(cls._directory.cleanup)
        cls.base = Path(cls._directory.name)
        cls.prepared = prepared_campaign(cls.base / "demo")

    def test_evidence_construction_consults_the_guard(self) -> None:
        target = "apex_labs.evidence.builder.require_research_code_identity"
        with mock.patch(target) as guard:
            build_evidence_set(
                self.prepared["paths"]["evidence_definition"],
                self.prepared["paths"]["segment"],
                self.prepared["paths"]["protocol_freeze"],
                self.prepared["paths"]["metric"],
                self.prepared["dataset_dirs"],
                self.base / "guarded-evidence",
                built_at=BUILT_AT,
                project_root=ROOT,
            )
        guard.assert_called_once()
        self.assertEqual(guard.call_args.kwargs, {"synthetic": True})

    def test_evidence_construction_refuses_real_evidence_from_an_unclean_tree(self) -> None:
        target = "apex_labs.evidence.builder.apex_labs_code_identity"
        with mock.patch(target, return_value=DIRTY):
            with mock.patch(
                "apex_labs.evidence.builder.require_research_code_identity",
                side_effect=lambda identity, synthetic: require_research_code_identity(
                    identity, synthetic=False
                ),
            ):
                with self.assertRaises(IntegrityError):
                    build_evidence_set(
                        self.prepared["paths"]["evidence_definition"],
                        self.prepared["paths"]["segment"],
                        self.prepared["paths"]["protocol_freeze"],
                        self.prepared["paths"]["metric"],
                        self.prepared["dataset_dirs"],
                        self.base / "refused-evidence",
                        built_at=BUILT_AT,
                    )
        self.assertFalse((self.base / "refused-evidence").exists())

    def test_inference_consults_the_guard(self) -> None:
        target = "apex_labs.analysis.inferential.require_research_code_identity"
        with mock.patch(target) as guard:
            run_inferential_analysis(
                self.prepared["paths"]["analysis_definition"],
                self.prepared["evidence_dir"],
                self.prepared["paths"]["protocol_freeze"],
                self.base / "guarded-run",
                run_id="guarded-run",
                created_at=BUILT_AT,
                project_root=ROOT,
            )
        guard.assert_called_once()
        self.assertEqual(guard.call_args.kwargs, {"synthetic": True})

    def test_hypothesis_registration_consults_the_guard(self) -> None:
        target = "apex_labs.hypotheses.registry.require_research_code_identity"
        with mock.patch(target) as guard:
            register_hypothesis(
                synthetic_hypothesis("guard-hypothesis"),
                self.base / "guarded-registry",
                recorded_at=BUILT_AT,
                project_root=ROOT,
            )
        guard.assert_called_once()
        self.assertEqual(guard.call_args.kwargs, {"synthetic": True})


class SyntheticIneligibilityTests(unittest.TestCase):
    def test_every_fabricated_artifact_declares_its_ineligibility(self) -> None:
        with tempfile.TemporaryDirectory(prefix="apex-labs-ineligible-") as directory:
            base = Path(directory)
            prepared = prepared_campaign(base / "demo")
            evidence = prepared["evidence"]
            self.assertTrue(evidence["synthetic"])
            self.assertTrue(
                any("permanently ineligible" in item for item in evidence["limitations"])
            )
            run = run_inferential_analysis(
                prepared["paths"]["analysis_definition"],
                prepared["evidence_dir"],
                prepared["paths"]["protocol_freeze"],
                base / "run",
                run_id="ineligible-run",
                created_at=BUILT_AT,
                project_root=ROOT,
            )
            self.assertTrue(run["synthetic"])
            self.assertFalse(run["scientific_eligibility"]["eligible"])

    def test_synthetic_and_real_evidence_can_never_be_combined(self) -> None:
        from apex_labs.errors import EvidenceError
        from apex_labs.io import read_json, write_json
        from apex_labs.schemas import validate_normalized_manifest

        with tempfile.TemporaryDirectory(prefix="apex-labs-mixed-") as directory:
            base = Path(directory)
            prepared = prepared_campaign(base / "demo")
            # Relabel one contributing dataset as real; the builder must refuse to
            # combine it with the fabricated ones.
            manifest_path = prepared["dataset_dirs"][0] / "manifest.json"
            manifest = read_json(manifest_path)
            manifest["synthetic"] = False
            write_json(manifest_path, manifest)
            validate_normalized_manifest(manifest)
            with self.assertRaises((EvidenceError, IntegrityError)):
                build_evidence_set(
                    prepared["paths"]["evidence_definition"],
                    prepared["paths"]["segment"],
                    prepared["paths"]["protocol_freeze"],
                    prepared["paths"]["metric"],
                    prepared["dataset_dirs"],
                    base / "mixed",
                    built_at=BUILT_AT,
                    project_root=ROOT,
                )


if __name__ == "__main__":
    unittest.main()
