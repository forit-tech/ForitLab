"""Статистика на чистом stdlib.

Ни numpy, ни scipy: на бесплатном shared hosting они съедают и квоту диска,
и инодов, и память. Все формулы здесь классические и проверяемые руками.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

EPS = 1e-10


# ---------------------------------------------------------------------------
# Базовые описательные статистики
# ---------------------------------------------------------------------------


def quantile(sorted_values: Sequence[float], q: float) -> float:
    """Линейная интерполяция по отсортированному массиву (как numpy linear)."""
    if not sorted_values:
        return math.nan
    if q <= 0:
        return float(sorted_values[0])
    if q >= 1:
        return float(sorted_values[-1])
    pos = (len(sorted_values) - 1) * q
    low = math.floor(pos)
    high = math.ceil(pos)
    if low == high:
        return float(sorted_values[int(pos)])
    frac = pos - low
    return float(sorted_values[low]) * (1 - frac) + float(sorted_values[high]) * frac


def mean(values: Sequence[float]) -> float:
    return math.fsum(values) / len(values) if values else math.nan


def stdev(values: Sequence[float]) -> float:
    """Выборочное СКО (ddof=1)."""
    n = len(values)
    if n < 2:
        return 0.0
    mu = mean(values)
    var = math.fsum((v - mu) ** 2 for v in values) / (n - 1)
    return math.sqrt(max(var, 0.0))


def skewness(values: Sequence[float]) -> float:
    """Асимметрия (Фишер, без поправки на смещение)."""
    n = len(values)
    if n < 3:
        return 0.0
    mu = mean(values)
    m2 = math.fsum((v - mu) ** 2 for v in values) / n
    if m2 < EPS:
        return 0.0
    m3 = math.fsum((v - mu) ** 3 for v in values) / n
    return m3 / (m2**1.5)


# ---------------------------------------------------------------------------
# Специальные функции: нужны для p-value без scipy
# ---------------------------------------------------------------------------


def _gamma_series(a: float, x: float) -> float:
    """Нижняя регуляризованная гамма P(a, x) рядом (Numerical Recipes, gser)."""
    ap = a
    total = 1.0 / a
    delta = total
    for _ in range(500):
        ap += 1.0
        delta *= x / ap
        total += delta
        if abs(delta) < abs(total) * 1e-12:
            break
    return total * math.exp(-x + a * math.log(x) - math.lgamma(a))


def _gamma_continued_fraction(a: float, x: float) -> float:
    """Верхняя регуляризованная гамма Q(a, x) цепной дробью (gcf)."""
    tiny = 1e-300
    b = x + 1.0 - a
    c = 1.0 / tiny
    d = 1.0 / b
    h = d
    for i in range(1, 500):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-12:
            break
    return h * math.exp(-x + a * math.log(x) - math.lgamma(a))


def gamma_sf(a: float, x: float) -> float:
    """Q(a, x) — верхняя регуляризованная неполная гамма-функция."""
    if x <= 0 or a <= 0:
        return 1.0
    if x < a + 1.0:
        return max(0.0, min(1.0, 1.0 - _gamma_series(a, x)))
    return max(0.0, min(1.0, _gamma_continued_fraction(a, x)))


def chi2_sf(statistic: float, df: int) -> float:
    """P(X > statistic) для хи-квадрат с df степенями свободы."""
    if df <= 0 or statistic <= 0:
        return 1.0
    return gamma_sf(df / 2.0, statistic / 2.0)


def kolmogorov_sf(x: float) -> float:
    """Q_KS(x) = 2 * sum_j (-1)^(j-1) * exp(-2 j^2 x^2)."""
    if x <= 0:
        return 1.0
    if x < 0.18:  # ряд сходится медленно, а хвост всё равно ~1
        return 1.0
    total = 0.0
    for j in range(1, 101):
        term = math.exp(-2.0 * j * j * x * x)
        total += (-1) ** (j - 1) * term
        if term < 1e-14:
            break
    return max(0.0, min(1.0, 2.0 * total))


# ---------------------------------------------------------------------------
# Метрики дрейфа
# ---------------------------------------------------------------------------


def psi(expected: Sequence[float], actual: Sequence[float]) -> float:
    """Population Stability Index по уже посчитанным долям.

    PSI = sum (actual_i - expected_i) * ln(actual_i / expected_i).
    Пустые бины сглаживаются EPS, иначе получаем бесконечность.
    """
    total = 0.0
    for e, a in zip(expected, actual):
        e_safe = max(e, EPS)
        a_safe = max(a, EPS)
        total += (a_safe - e_safe) * math.log(a_safe / e_safe)
    return total


def jensen_shannon_divergence(p: Sequence[float], q: Sequence[float]) -> float:
    """JSD в битах: 0 — распределения совпадают, 1 — не пересекаются."""

    def kl(a: Sequence[float], b: Sequence[float]) -> float:
        return math.fsum(
            ai * math.log2(ai / bi) for ai, bi in zip(a, b) if ai > EPS and bi > EPS
        )

    m = [(pi + qi) / 2.0 for pi, qi in zip(p, q)]
    return max(0.0, 0.5 * kl(p, m) + 0.5 * kl(q, m))


def total_variation_distance(p: Sequence[float], q: Sequence[float]) -> float:
    """TVD = 0.5 * sum |p_i - q_i| — доля переехавшей вероятностной массы."""
    return 0.5 * math.fsum(abs(pi - qi) for pi, qi in zip(p, q))


def ks_two_sample(reference: Sequence[float], current: Sequence[float]) -> tuple[float, float]:
    """Двухвыборочный тест Колмогорова–Смирнова.

    Оба входа должны быть отсортированы. Возвращает (D, p-value).
    p-value — асимптотическое приближение с поправкой Стефенса; на маленьких
    выборках оно консервативно, что для мониторинга дрейфа нас устраивает.
    """
    n1, n2 = len(reference), len(current)
    if n1 == 0 or n2 == 0:
        return 0.0, 1.0

    i = j = 0
    cdf1 = cdf2 = 0.0
    d = 0.0
    while i < n1 and j < n2:
        x1, x2 = reference[i], current[j]
        if x1 <= x2:
            value = x1
            while i < n1 and reference[i] == value:
                i += 1
            cdf1 = i / n1
        if x2 <= x1:
            value = x2
            while j < n2 and current[j] == value:
                j += 1
            cdf2 = j / n2
        d = max(d, abs(cdf1 - cdf2))

    en = math.sqrt(n1 * n2 / (n1 + n2))
    p_value = kolmogorov_sf((en + 0.12 + 0.11 / en) * d)
    return d, p_value


def chi_square_two_sample(
    ref_counts: Sequence[int], cur_counts: Sequence[int]
) -> tuple[float, int, float]:
    """Хи-квадрат однородности для двух выборок категорий.

    Возвращает (статистика, число степеней свободы, p-value).
    Категории с нулевым суммарным весом выбрасываются.
    """
    pairs = [(r, c) for r, c in zip(ref_counts, cur_counts) if (r + c) > 0]
    if len(pairs) < 2:
        return 0.0, 0, 1.0

    n_ref = sum(r for r, _ in pairs)
    n_cur = sum(c for _, c in pairs)
    n_total = n_ref + n_cur
    if n_ref == 0 or n_cur == 0:
        return 0.0, 0, 1.0

    statistic = 0.0
    for r, c in pairs:
        row_total = r + c
        exp_ref = row_total * n_ref / n_total
        exp_cur = row_total * n_cur / n_total
        if exp_ref > EPS:
            statistic += (r - exp_ref) ** 2 / exp_ref
        if exp_cur > EPS:
            statistic += (c - exp_cur) ** 2 / exp_cur

    df = len(pairs) - 1
    return statistic, df, chi2_sf(statistic, df)


def cohens_d(
    mean_ref: float, std_ref: float, n_ref: int, mean_cur: float, std_cur: float, n_cur: int
) -> float:
    """Размер эффекта: на больших выборках p-value значимо всегда, d — нет."""
    if n_ref < 2 or n_cur < 2:
        return 0.0
    pooled_var = ((n_ref - 1) * std_ref**2 + (n_cur - 1) * std_cur**2) / (n_ref + n_cur - 2)
    pooled = math.sqrt(max(pooled_var, 0.0))
    if pooled < EPS:
        return 0.0
    return (mean_cur - mean_ref) / pooled
