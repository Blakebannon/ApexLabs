from __future__ import annotations

import unittest

from _support import ROOT, run_cli

from apex_labs.demo import verify_synthetic_demo


class SyntheticEndToEndTests(unittest.TestCase):
    def test_full_demo_is_reproducible_and_scientifically_ineligible(self) -> None:
        result = verify_synthetic_demo(ROOT)
        self.assertTrue(result["deterministic_normalization"])
        self.assertTrue(result["deterministic_export"])
        self.assertEqual("synthetic_demo_only_not_racing_research", result["classification"])
        self.assertEqual("inconclusive", result["finding_status"])
        self.assertEqual("unresolved", result["scientific_gate"])
        self.assertEqual("do_not_implement", result["product_action"])

    def test_cli_exposes_same_controlled_demo_verification(self) -> None:
        result = run_cli("verify-synthetic-demo", "--root", str(ROOT))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("synthetic_demo_only_not_racing_research", result.stdout)


if __name__ == "__main__":
    unittest.main()
