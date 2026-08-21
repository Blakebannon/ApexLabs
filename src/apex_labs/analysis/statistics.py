"""Robust, interpretable, deterministic statistics for small driving corpora.

Everything here is standard library. The methods are deliberately modest: a
robust paired estimate with transparent uncertainty is preferable to a fragile
model fitted to evidence that cannot support it.

Three properties are load-bearing and are tested directly:

* **Order independence.** Every kernel sorts its input before computing, so the
  order in which records were streamed can never change a result.
* **Machine independence.** Resampling draws come from a SHA-256 counter stream
  with rejection sampling, not from a platform or version dependent PRNG.
* **Honest absence.** A statistic that is not defined for the available evidence
  returns ``None`` rather than a plausible-looking number.
"""

from __future__ import annotations

import hashlib
import math
import statistics
from typing import Any, Callable, Iterable, Sequence

_UINT64 = 1 << 64


def median(values: Sequence[float]) -> float | None:
    """Median of a finite sample, or None when the sample is empty."""
    if not values:
        return None
    return statistics.median(sorted(values))


def mean(values: Sequence[float]) -> float | None:
    """Arithmetic mean computed with exact summation, or None when empty."""
    if not values:
        return None
    return math.fsum(sorted(values)) / len(values)


def median_absolute_deviation(values: Sequence[float]) -> float | None:
    """Unscaled MAD: the median absolute deviation from the median."""
    if not values:
        return None
    centre = statistics.median(sorted(values))
    return statistics.median(sorted(abs(value - centre) for value in values))


def interquartile_range(values: Sequence[float]) -> float | None:
    """Inclusive-method IQR, or None when fewer than two values are available."""
    if len(values) < 2:
        return None
    lower, _, upper = statistics.quantiles(sorted(values), n=4, method="inclusive")
    return upper - lower


def _uint64_stream(seed: int, label: str) -> Iterable[int]:
    """Deterministic unsigned 64-bit stream derived from SHA-256.

    The stream depends only on the declared seed and label, never on the host,
    the Python build, or the order in which evidence reached this process.
    """
    counter = 0
    while True:
        block = hashlib.sha256(f"{seed}:{label}:{counter}".encode("utf-8")).digest()
        for offset in range(0, 32, 8):
            yield int.from_bytes(block[offset : offset + 8], "big")
        counter += 1


def deterministic_indices(seed: int, label: str, count: int, modulus: int) -> list[int]:
    """`count` indices in [0, modulus) drawn without modulo bias.

    Rejection sampling discards the unrepresentable tail of the 64-bit range so
    that every index is exactly equally likely; the result is reproducible on
    any machine from the seed and label alone.
    """
    if modulus < 1:
        raise ValueError("modulus must be positive")
    if count < 0:
        raise ValueError("count must be non-negative")
    limit = (_UINT64 // modulus) * modulus
    stream = _uint64_stream(seed, label)
    drawn: list[int] = []
    while len(drawn) < count:
        value = next(stream)
        if value < limit:
            drawn.append(value % modulus)
    return drawn


def percentile_interval(
    statistics_sample: Sequence[float], coverage_level: float
) -> tuple[float, float] | None:
    """Percentile interval over a bootstrap distribution.

    With ``B`` draws sorted ascending and ``alpha = 1 - coverage_level``, the
    bounds are ``s[floor(alpha / 2 * B)]`` and ``s[ceil((1 - alpha / 2) * B) - 1]``.
    The convention is fixed here so that an interval is reproducible and its
    meaning is stated rather than assumed. The indices are computed in IEEE
    double arithmetic, so a coverage level whose complement is not exactly
    representable can land one index away from the textbook round number. That
    is identical on every machine, which is the property an interval needs.
    """
    if not statistics_sample:
        return None
    if not 0 < coverage_level < 1:
        raise ValueError("coverage_level must lie strictly within (0, 1)")
    ordered = sorted(statistics_sample)
    draws = len(ordered)
    alpha = 1.0 - coverage_level
    lower_index = math.floor(alpha / 2 * draws)
    upper_index = math.ceil((1 - alpha / 2) * draws) - 1
    lower_index = min(max(lower_index, 0), draws - 1)
    upper_index = min(max(upper_index, 0), draws - 1)
    if lower_index > upper_index:
        lower_index = upper_index
    return ordered[lower_index], ordered[upper_index]


def cluster_bootstrap_distribution(
    clusters: Sequence[Sequence[Any]],
    statistic: Callable[[Sequence[Any]], float | None],
    *,
    draws: int,
    seed: int,
    label: str,
) -> list[float]:
    """Resample whole clusters with replacement and recompute the statistic.

    Clusters are the declared resampling unit. Observations nested inside one
    cluster travel together, because they are not independent evidence about a
    factor that varies only between clusters. Draws that produce an undefined
    statistic are discarded and reported through the caller's draw accounting.
    """
    if not clusters:
        return []
    # Canonicalize within and across clusters so that neither the order in which
    # records arrived nor the order in which clusters were assembled can move an
    # interval. Clusters with identical contents are interchangeable by
    # construction, so sorting by contents discards nothing.
    ordered = sorted(sorted(cluster) for cluster in clusters)
    cluster_count = len(ordered)
    indices = deterministic_indices(seed, label, draws * cluster_count, cluster_count)
    distribution: list[float] = []
    for draw in range(draws):
        window = indices[draw * cluster_count : (draw + 1) * cluster_count]
        resampled: list[float] = []
        for index in window:
            resampled.extend(ordered[index])
        value = statistic(resampled)
        if value is not None:
            distribution.append(value)
    return distribution


def exact_sign_test(differences: Sequence[float]) -> dict[str, object]:
    """Two-sided exact paired sign test.

    Zero differences are ties and are excluded from the test rather than being
    counted as support for either direction. The p-value is the exact binomial
    tail under a fair-coin null; it is the probability of evidence at least this
    extreme if the null were true, and it is never the probability that a
    hypothesis is true.
    """
    positive = sum(1 for value in differences if value > 0)
    negative = sum(1 for value in differences if value < 0)
    ties = sum(1 for value in differences if value == 0)
    trials = positive + negative
    if trials == 0:
        return {
            "positive": positive,
            "negative": negative,
            "ties": ties,
            "trials": 0,
            "p_value": None,
        }
    extreme = min(positive, negative)
    tail = sum(math.comb(trials, index) for index in range(extreme + 1))
    p_value = min(1.0, 2 * tail / (2**trials))
    return {
        "positive": positive,
        "negative": negative,
        "ties": ties,
        "trials": trials,
        "p_value": p_value,
    }


def theil_sen_slope(points: Sequence[tuple[float, float]]) -> float | None:
    """Median of pairwise slopes: a robust, interpretable ordered-trend estimate.

    Session or lap order is an ordering, not a cause. A non-zero slope describes
    how the metric moved across the ordered units and says nothing on its own
    about why.
    """
    ordered = sorted(points)
    slopes: list[float] = []
    for index, (x_left, y_left) in enumerate(ordered):
        for x_right, y_right in ordered[index + 1 :]:
            if x_right != x_left:
                slopes.append((y_right - y_left) / (x_right - x_left))
    if not slopes:
        return None
    return statistics.median(sorted(slopes))


def paired_differences(pairs: Sequence[tuple[float, float]]) -> list[float]:
    """Intervention minus baseline for each pair, in the caller's pair order."""
    return [intervention - baseline for baseline, intervention in pairs]


def dispersion_ratio(baseline: Sequence[float], intervention: Sequence[float]) -> dict[str, object]:
    """Compare consistency between arms without claiming less variation is better.

    Lower dispersion can mean a steadier technique, a narrower sample, or a
    driver who stopped exploring. The ratio is reported with both inputs so a
    reviewer can see which.
    """
    baseline_mad = median_absolute_deviation(baseline)
    intervention_mad = median_absolute_deviation(intervention)
    baseline_iqr = interquartile_range(baseline)
    intervention_iqr = interquartile_range(intervention)
    ratio: float | None
    if baseline_mad is None or intervention_mad is None or baseline_mad == 0:
        ratio = None
    else:
        ratio = intervention_mad / baseline_mad
    return {
        "baseline_mad": baseline_mad,
        "intervention_mad": intervention_mad,
        "baseline_iqr": baseline_iqr,
        "intervention_iqr": intervention_iqr,
        "ratio": ratio,
    }


def group_summary(values: Sequence[float]) -> dict[str, object]:
    """Robust arm summary retained beside every comparison."""
    return {
        "n": len(values),
        "median": median(values),
        "mean": mean(values),
        "mad": median_absolute_deviation(values),
        "minimum": min(values) if values else None,
        "maximum": max(values) if values else None,
    }


def holm_bonferroni(p_values: Sequence[float | None]) -> list[float | None]:
    """Step-down familywise correction for a small preregistered family.

    The family size is the number of declared members, not the number that
    happened to produce a p-value, so a comparison that fails to compute cannot
    weaken the correction applied to the others.
    """
    family_size = len(p_values)
    indexed = sorted(
        (value, index) for index, value in enumerate(p_values) if value is not None
    )
    adjusted: list[float | None] = [None] * family_size
    running = 0.0
    for rank, (value, index) in enumerate(indexed):
        candidate = min(1.0, (family_size - rank) * value)
        running = max(running, candidate)
        adjusted[index] = running
    return adjusted


def benjamini_hochberg(p_values: Sequence[float | None]) -> list[float | None]:
    """Step-up false-discovery-rate correction for a broad exploratory family.

    Controlling the expected proportion of false discoveries is the appropriate
    guarantee when many relationships are searched. It is not a statement that
    any surviving relationship is true, and a survivor still requires
    independent replication.
    """
    family_size = len(p_values)
    indexed = sorted(
        (value, index) for index, value in enumerate(p_values) if value is not None
    )
    adjusted: list[float | None] = [None] * family_size
    running = 1.0
    for rank in range(len(indexed) - 1, -1, -1):
        value, index = indexed[rank]
        candidate = min(1.0, family_size / (rank + 1) * value)
        running = min(running, candidate)
        adjusted[index] = running
    return adjusted


CORRECTIONS: dict[str, Callable[[Sequence[float | None]], list[float | None]]] = {
    "holm_bonferroni": holm_bonferroni,
    "benjamini_hochberg": benjamini_hochberg,
    "none": lambda values: [None if value is None else min(1.0, value) for value in values],
}
