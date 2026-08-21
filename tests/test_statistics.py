"""Known-answer tests for the statistical kernels.

Every expected value here was worked out independently of the implementation:
exact binomial tails, textbook Holm and Benjamini-Hochberg examples, medians of
pairwise slopes computed by hand, and a fixed percentile-index convention.
"""

from __future__ import annotations

import math
import unittest

from _support import ROOT  # noqa: F401  (ensures src is importable)

from apex_labs.analysis import statistics as stats


class SignTestTests(unittest.TestCase):
    def test_exact_binomial_tails_match_hand_computed_values(self) -> None:
        # 10 trials, 1 discordant: 2 * (C(10,0) + C(10,1)) / 2**10 = 22/1024.
        result = stats.exact_sign_test([1.0] * 9 + [-1.0])
        self.assertEqual(result["trials"], 10)
        self.assertEqual(result["p_value"], 22 / 1024)
        # 6 trials, 0 discordant: 2 * 1 / 64.
        self.assertEqual(stats.exact_sign_test([1.0] * 6)["p_value"], 2 / 64)
        # 18 trials, 0 discordant: 2 / 2**18.
        self.assertEqual(stats.exact_sign_test([1.0] * 18)["p_value"], 2 / 2**18)
        # A near-even split saturates at 1 rather than exceeding it.
        self.assertEqual(stats.exact_sign_test([1.0, 1.0, 1.0, -1.0, -1.0])["p_value"], 1.0)

    def test_ties_are_excluded_rather_than_counted_as_support(self) -> None:
        result = stats.exact_sign_test([0.0, 0.0, 0.0, 5.0])
        self.assertEqual((result["positive"], result["negative"], result["ties"]), (1, 0, 3))
        self.assertEqual(result["trials"], 1)
        self.assertEqual(result["p_value"], 1.0)

    def test_no_informative_pair_returns_no_p_value(self) -> None:
        result = stats.exact_sign_test([0.0, 0.0])
        self.assertIsNone(result["p_value"])

    def test_result_is_independent_of_input_order(self) -> None:
        forward = stats.exact_sign_test([0.4, -0.1, 0.2, 0.0, 0.9])
        backward = stats.exact_sign_test([0.9, 0.0, 0.2, -0.1, 0.4])
        self.assertEqual(forward, backward)


class RobustEstimatorTests(unittest.TestCase):
    def test_theil_sen_recovers_an_exact_line_and_resists_one_outlier(self) -> None:
        self.assertEqual(stats.theil_sen_slope([(0, 0), (1, 2), (2, 4), (3, 6)]), 2.0)
        # Pairwise slopes are 1, 1, 33, 1, 49, 97; their median is (1 + 33) / 2.
        self.assertEqual(stats.theil_sen_slope([(1, 1), (2, 2), (3, 3), (4, 100)]), 17.0)

    def test_theil_sen_is_undefined_without_two_distinct_positions(self) -> None:
        self.assertIsNone(stats.theil_sen_slope([(1.0, 5.0)]))
        self.assertIsNone(stats.theil_sen_slope([(1.0, 5.0), (1.0, 9.0)]))

    def test_median_absolute_deviation_and_iqr(self) -> None:
        values = [1.0, 2.0, 3.0, 4.0, 100.0]
        self.assertEqual(stats.median(values), 3.0)
        # Deviations from 3 are 2, 1, 0, 1, 97; their median is 1.
        self.assertEqual(stats.median_absolute_deviation(values), 1.0)
        self.assertEqual(stats.interquartile_range([1.0, 2.0, 3.0, 4.0, 5.0]), 2.0)

    def test_empty_and_singleton_samples_report_absence_rather_than_a_number(self) -> None:
        self.assertIsNone(stats.median([]))
        self.assertIsNone(stats.mean([]))
        self.assertIsNone(stats.median_absolute_deviation([]))
        self.assertIsNone(stats.interquartile_range([4.0]))

    def test_dispersion_ratio_reports_both_inputs_and_refuses_division_by_zero(self) -> None:
        result = stats.dispersion_ratio([1.0, 1.0, 1.0], [1.0, 3.0, 5.0])
        self.assertIsNone(result["ratio"], "a zero baseline dispersion has no ratio")
        self.assertEqual(result["baseline_mad"], 0.0)
        self.assertEqual(result["intervention_mad"], 2.0)
        halved = stats.dispersion_ratio([0.0, 2.0, 4.0], [1.0, 2.0, 3.0])
        self.assertEqual(halved["ratio"], 0.5)

    def test_estimators_ignore_input_order(self) -> None:
        forward = [3.0, 1.0, 4.0, 1.0, 5.0]
        backward = list(reversed(forward))
        self.assertEqual(stats.median(forward), stats.median(backward))
        self.assertEqual(stats.mean(forward), stats.mean(backward))
        self.assertEqual(
            stats.median_absolute_deviation(forward), stats.median_absolute_deviation(backward)
        )


class DeterministicResamplingTests(unittest.TestCase):
    def test_indices_are_reproducible_and_depend_on_seed_and_label(self) -> None:
        first = stats.deterministic_indices(7, "primary", 64, 5)
        self.assertEqual(first, stats.deterministic_indices(7, "primary", 64, 5))
        self.assertNotEqual(first, stats.deterministic_indices(8, "primary", 64, 5))
        self.assertNotEqual(first, stats.deterministic_indices(7, "secondary", 64, 5))
        self.assertTrue(all(0 <= index < 5 for index in first))

    def test_indices_are_a_prefix_of_a_longer_draw(self) -> None:
        short = stats.deterministic_indices(3, "label", 10, 4)
        long = stats.deterministic_indices(3, "label", 40, 4)
        self.assertEqual(short, long[:10])

    def test_rejection_sampling_removes_modulo_bias(self) -> None:
        # With a modulus that does not divide 2**64, a biased implementation would
        # over-represent the low indices. Observed counts stay close to uniform.
        modulus = 3
        draws = 9000
        indices = stats.deterministic_indices(11, "uniformity", draws, modulus)
        counts = [indices.count(value) for value in range(modulus)]
        expected = draws / modulus
        for count in counts:
            self.assertLess(abs(count - expected) / expected, 0.05)

    def test_cluster_bootstrap_is_order_independent_and_reproducible(self) -> None:
        clusters = [[1.0, 2.0], [3.0, 4.0], [5.0]]
        first = stats.cluster_bootstrap_distribution(
            clusters, stats.median, draws=200, seed=7, label="x"
        )
        reordered = stats.cluster_bootstrap_distribution(
            [list(reversed(cluster)) for cluster in reversed(clusters)],
            stats.median,
            draws=200,
            seed=7,
            label="x",
        )
        self.assertEqual(first, reordered)
        self.assertEqual(len(first), 200)
        self.assertNotEqual(
            first, stats.cluster_bootstrap_distribution(clusters, stats.median, draws=200, seed=8, label="x")
        )

    def test_cluster_bootstrap_travels_whole_clusters(self) -> None:
        # Every cluster is internally constant, so any resample median must be one
        # of the cluster values. A frame-level resample could produce other values.
        clusters = [[0.0, 0.0, 0.0], [10.0, 10.0, 10.0]]
        distribution = stats.cluster_bootstrap_distribution(
            clusters, stats.median, draws=200, seed=1, label="cluster"
        )
        self.assertTrue(set(distribution) <= {0.0, 5.0, 10.0})

    def test_empty_cluster_set_produces_no_distribution(self) -> None:
        self.assertEqual(
            stats.cluster_bootstrap_distribution([], stats.median, draws=100, seed=1, label="x"), []
        )


class PercentileIntervalTests(unittest.TestCase):
    def test_index_convention_is_exactly_as_documented(self) -> None:
        sample = list(range(1000))
        # alpha = 0.05: lower index floor(0.025 * 1000) = 25, upper ceil(0.975 * 1000) - 1 = 974.
        self.assertEqual(stats.percentile_interval(sample, 0.95), (25, 974))
        # The bounds are computed in IEEE double arithmetic, so 1 - 0.80 is
        # 0.19999999999999996 and the lower index floors to 99 rather than 100.
        # That is reproducible on every machine, which is the property that
        # matters; it is not always the textbook round number.
        self.assertEqual(stats.percentile_interval(sample, 0.80), (99, 899))

    def test_interval_ignores_input_order_and_handles_tiny_samples(self) -> None:
        sample = [5.0, 1.0, 3.0]
        self.assertEqual(
            stats.percentile_interval(sample, 0.95), stats.percentile_interval(sorted(sample), 0.95)
        )
        self.assertEqual(stats.percentile_interval([2.0], 0.95), (2.0, 2.0))
        self.assertIsNone(stats.percentile_interval([], 0.95))

    def test_impossible_coverage_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            stats.percentile_interval([1.0, 2.0], 1.0)


class MultiplicityTests(unittest.TestCase):
    def test_holm_matches_the_hand_computed_step_down(self) -> None:
        # m = 3: 3*0.01 = 0.03; 2*0.02 = 0.04; 1*0.03 = 0.03, raised to 0.04 by monotonicity.
        self.assertEqual(stats.holm_bonferroni([0.01, 0.02, 0.03]), [0.03, 0.04, 0.04])

    def test_holm_preserves_input_position_and_enforces_monotonicity(self) -> None:
        # Sorted: 0.001 (position 1), 0.4 (position 2), 0.5 (position 0).
        # 3*0.001 = 0.003; 2*0.4 = 0.8; 1*0.5 = 0.5 raised to 0.8 by monotonicity.
        adjusted = stats.holm_bonferroni([0.5, 0.001, 0.4])
        self.assertEqual(adjusted, [0.8, 0.003, 0.8])

    def test_holm_caps_adjusted_values_at_one(self) -> None:
        self.assertEqual(stats.holm_bonferroni([0.5, 0.6, 0.7]), [1.0, 1.0, 1.0])

    def test_benjamini_hochberg_matches_the_textbook_example(self) -> None:
        raw = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205]
        adjusted = stats.benjamini_hochberg(raw)
        expected = [0.008, 0.032, 0.0672, 0.0672, 0.0672, 0.08, 8 / 7 * 0.074, 0.205]
        for observed, target in zip(adjusted, expected):
            self.assertTrue(math.isclose(observed, target, rel_tol=1e-12))

    def test_family_size_is_the_declared_membership_not_the_computable_subset(self) -> None:
        # A member that produced no p-value still counts toward the correction, so
        # a comparison that fails to compute cannot weaken the others.
        with_missing = stats.holm_bonferroni([0.01, None, None])
        self.assertEqual(with_missing[0], 0.03)
        self.assertIsNone(with_missing[1])
        self.assertEqual(stats.benjamini_hochberg([0.01, None, None])[0], 0.03)

    def test_no_correction_passes_values_through_unchanged(self) -> None:
        self.assertEqual(stats.CORRECTIONS["none"]([0.02, None]), [0.02, None])

    def test_every_correction_is_monotone_in_the_raw_values(self) -> None:
        raw = [0.001, 0.01, 0.02, 0.03, 0.9]
        for name in ("holm_bonferroni", "benjamini_hochberg"):
            adjusted = stats.CORRECTIONS[name](raw)
            for value, target in zip(raw, adjusted):
                self.assertGreaterEqual(target, value, f"{name} must never strengthen evidence")


if __name__ == "__main__":
    unittest.main()
