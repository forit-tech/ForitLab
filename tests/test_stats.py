"""Проверка статистики по табличным значениям.

Смысл этих тестов в том, что мы отказались от scipy и посчитали спецфункции
сами: если формулы поедут, поедут и все выводы сервиса.
"""

from __future__ import annotations

import math
import random

import pytest

from app.tools.drift.stats import (
    chi2_sf,
    chi_square_two_sample,
    cohens_d,
    jensen_shannon_divergence,
    ks_two_sample,
    psi,
    quantile,
    stdev,
    total_variation_distance,
)


@pytest.mark.parametrize(
    ("statistic", "df", "expected"),
    [
        (3.841, 1, 0.05),  # классические критические значения из таблиц
        (5.991, 2, 0.05),
        (11.070, 5, 0.05),
        (6.635, 1, 0.01),
        (9.210, 2, 0.01),
    ],
)
def test_chi2_sf_matches_critical_values(statistic: float, df: int, expected: float) -> None:
    assert chi2_sf(statistic, df) == pytest.approx(expected, abs=5e-4)


def test_chi2_sf_edges() -> None:
    assert chi2_sf(0.0, 3) == 1.0
    assert chi2_sf(100.0, 1) < 1e-20


def test_quantile_linear_interpolation() -> None:
    values = [1.0, 2.0, 3.0, 4.0]
    assert quantile(values, 0.0) == 1.0
    assert quantile(values, 0.5) == 2.5
    assert quantile(values, 1.0) == 4.0


def test_stdev_sample() -> None:
    # Классический пример: ddof=1 даёт ровно 2.0
    assert stdev([2, 4, 4, 4, 5, 5, 7, 9]) == pytest.approx(2.13809, abs=1e-4)
    assert stdev([5]) == 0.0


def test_psi_is_zero_for_identical_distributions() -> None:
    shares = [0.2, 0.3, 0.5]
    assert psi(shares, shares) == pytest.approx(0.0, abs=1e-9)


def test_psi_grows_with_shift() -> None:
    base = [0.25, 0.25, 0.25, 0.25]
    small = psi(base, [0.3, 0.25, 0.25, 0.2])
    large = psi(base, [0.7, 0.1, 0.1, 0.1])
    assert 0 < small < large


def test_ks_identical_samples() -> None:
    values = sorted(float(i) for i in range(500))
    statistic, p_value = ks_two_sample(values, values)
    assert statistic == pytest.approx(0.0, abs=1e-12)
    assert p_value == pytest.approx(1.0)


def test_ks_detects_shift() -> None:
    rng = random.Random(1)
    reference = sorted(rng.gauss(0, 1) for _ in range(2000))
    current = sorted(rng.gauss(1.5, 1) for _ in range(2000))
    statistic, p_value = ks_two_sample(reference, current)
    assert statistic > 0.4
    assert p_value < 1e-10


def test_ks_ignores_noise() -> None:
    rng = random.Random(7)
    reference = sorted(rng.gauss(0, 1) for _ in range(2000))
    current = sorted(rng.gauss(0, 1) for _ in range(2000))
    _, p_value = ks_two_sample(reference, current)
    assert p_value > 0.01


def test_chi_square_two_sample_detects_difference() -> None:
    statistic, df, p_value = chi_square_two_sample([500, 500], [900, 100])
    assert df == 1
    assert statistic > 100
    assert p_value < 1e-20


def test_chi_square_two_sample_identical() -> None:
    _, _, p_value = chi_square_two_sample([300, 200, 100], [300, 200, 100])
    assert p_value == pytest.approx(1.0, abs=1e-6)


def test_jsd_bounds() -> None:
    assert jensen_shannon_divergence([0.5, 0.5], [0.5, 0.5]) == pytest.approx(0.0, abs=1e-12)
    # Непересекающиеся распределения дают ровно 1 бит.
    assert jensen_shannon_divergence([1.0, 0.0], [0.0, 1.0]) == pytest.approx(1.0, abs=1e-9)


def test_total_variation_distance() -> None:
    assert total_variation_distance([0.5, 0.5], [0.5, 0.5]) == 0.0
    assert total_variation_distance([1.0, 0.0], [0.0, 1.0]) == pytest.approx(1.0)


def test_cohens_d_sign_and_scale() -> None:
    assert cohens_d(0.0, 1.0, 100, 1.0, 1.0, 100) == pytest.approx(1.0, abs=1e-6)
    assert cohens_d(1.0, 1.0, 100, 0.0, 1.0, 100) == pytest.approx(-1.0, abs=1e-6)
    # Нулевой разброс не должен приводить к делению на ноль.
    assert cohens_d(1.0, 0.0, 100, 2.0, 0.0, 100) == 0.0


def test_kolmogorov_sf_is_monotonic() -> None:
    from app.tools.drift.stats import kolmogorov_sf

    values = [kolmogorov_sf(x) for x in (0.3, 0.6, 1.0, 1.5, 2.0)]
    assert all(earlier >= later for earlier, later in zip(values, values[1:]))
    assert all(0.0 <= value <= 1.0 for value in values)
    assert math.isclose(kolmogorov_sf(0.0), 1.0)
