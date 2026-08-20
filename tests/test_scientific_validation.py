from __future__ import annotations

import copy
import unittest

from _support import FINDING, VALIDATION

from apex_labs.errors import ContractValidationError
from apex_labs.findings import finding_hash, validate_finding_with_artifact
from apex_labs.io import read_json
from apex_labs.schemas import validate_finding, validate_finding_validation


class ScientificStatusTests(unittest.TestCase):
    def test_demo_finding_and_validation_remain_unresolved_and_inconclusive(self) -> None:
        finding, artifact = validate_finding_with_artifact(
            read_json(FINDING), read_json(VALIDATION)
        )
        self.assertEqual("inconclusive", finding["status"])
        self.assertEqual("unresolved", artifact["gate_evaluations"]["scientific"])
        self.assertEqual("unreviewed", artifact["review"]["state"])
        self.assertEqual("not_requested", artifact["product_review_state"])

    def test_analyst_sufficiency_and_comparability_claims_cannot_validate_finding(self) -> None:
        finding = read_json(FINDING)
        finding["synthetic"] = False
        finding["evidence_classification"] = "controlled"
        finding["status"] = "validated"
        finding["scope"] = "algorithmic"
        finding["sample_sufficiency"]["status"] = "sufficient"
        finding["comparability_assessment"]["status"] = "adequate"
        finding["validation_artifact_reference"] = None
        finding["scientific_review_state"] = "unresolved"
        finding["safe_for_global_consideration"] = True
        finding["recommended_product_action"] = "consider"
        with self.assertRaises(ContractValidationError):
            validate_finding(finding)

    def test_scientific_gate_rejects_analyst_claim_provenance(self) -> None:
        artifact = read_json(VALIDATION)
        artifact["synthetic"] = False
        artifact["datasets"][0]["synthetic"] = False
        artifact["analysis_code_identity"]["git_commit"] = "1234567"
        artifact["analysis_code_identity"]["git_state"] = "clean"
        artifact["gate_evaluations"] = {
            "structural": "passed",
            "reproducibility": "passed",
            "scientific": "passed",
        }
        artifact["review"] = {
            "state": "approved",
            "reviewers": [{"reviewer_id": "reviewer-01", "role": "scientific-review"}],
            "reviewed_at": "2026-08-19T03:00:00Z",
            "notes": ["Test review state only"],
        }
        artifact["computed_evidence"]["sample_sufficiency"].update(
            {
                "status": "sufficient",
                "provenance": "analyst_claim",
                "evidence_references": ["evidence/sample-sufficiency.json"],
            }
        )
        artifact["computed_evidence"]["comparability"].update(
            {
                "status": "adequate",
                "provenance": "computed",
                "evidence_references": ["evidence/comparability.json"],
            }
        )
        with self.assertRaises(ContractValidationError):
            validate_finding_validation(artifact)

    def test_synthetic_artifact_can_never_pass_scientific_or_product_review(self) -> None:
        for mutation in ("scientific", "review", "product"):
            artifact = read_json(VALIDATION)
            if mutation == "scientific":
                artifact["gate_evaluations"]["scientific"] = "passed"
            elif mutation == "review":
                artifact["review"]["state"] = "approved"
                artifact["review"]["reviewers"] = [
                    {"reviewer_id": "reviewer-01", "role": "scientific-review"}
                ]
                artifact["review"]["reviewed_at"] = "2026-08-19T03:00:00Z"
            else:
                artifact["product_review_state"] = "approved"
            with self.subTest(mutation=mutation), self.assertRaises(ContractValidationError):
                validate_finding_validation(artifact)

    def test_population_support_requires_preregistered_population_design(self) -> None:
        artifact = read_json(VALIDATION)
        artifact["scope_assessment"]["scope"] = "population_supported"
        with self.assertRaises(ContractValidationError):
            validate_finding_validation(artifact)

    def test_cross_file_binding_detects_finding_dataset_protocol_and_code_changes(self) -> None:
        finding = read_json(FINDING)
        artifact = read_json(VALIDATION)
        mutations = [
            ("finding", lambda value: value["dataset_references"][0].update({"fingerprint": "f" * 64})),
            ("finding", lambda value: value["protocol_reference"].update({"freeze_sha256": "e" * 64})),
            ("finding", lambda value: value["analysis_code_identity"].update({"code_and_schema_sha256": "d" * 64})),
            ("artifact", lambda value: value["computed_evidence"]["sample_counts"]["values"].update({"observations": 7})),
        ]
        for target, mutate in mutations:
            changed_finding = copy.deepcopy(finding)
            changed_artifact = copy.deepcopy(artifact)
            mutate(changed_finding if target == "finding" else changed_artifact)
            if target == "finding":
                changed_artifact["finding_sha256"] = finding_hash(changed_finding)
            with self.subTest(target=target), self.assertRaises(ContractValidationError):
                validate_finding_with_artifact(changed_finding, changed_artifact)

    def test_finding_hash_prevents_post_validation_rewrite(self) -> None:
        finding = read_json(FINDING)
        artifact = read_json(VALIDATION)
        finding["conclusion"] = "Rewritten after validation"
        with self.assertRaises(ContractValidationError):
            validate_finding_with_artifact(finding, artifact)

    def test_product_approval_cannot_precede_scientific_review(self) -> None:
        finding = read_json(FINDING)
        finding["product_review_state"] = "approved"
        with self.assertRaises(ContractValidationError):
            validate_finding(finding)


if __name__ == "__main__":
    unittest.main()
