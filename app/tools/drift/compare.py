"""Сравнение двух профилей: схема, распределения, пропуски, категории.

Логика отчёта строится вокруг находок (Finding), а не вокруг «есть дрейф /
нет дрейфа». Каждая находка знает свой код, серьёзность и человеческое
объяснение — ради этого инструмент и затевался.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from .profiling import ColumnProfile, TableProfile
from .stats import (
    chi_square_two_sample,
    cohens_d,
    jensen_shannon_divergence,
    ks_two_sample,
    psi,
    quantile,
    total_variation_distance,
)

OK = "ok"
WARN = "warn"
ALERT = "alert"
INFO = "info"

_SEVERITY_ORDER = {OK: 0, INFO: 1, WARN: 2, ALERT: 3}

#: Сколько категорий держим в сравнении; остальное схлопываем в __other__.
CATEGORY_LIMIT = 50


@dataclass
class Finding:
    code: str
    severity: str
    message: str
    detail: dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class ColumnReport:
    column: str
    status: str
    analysis: str
    reference_type: str | None
    current_type: str | None
    metrics: dict[str, object] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "column": self.column,
            "status": self.status,
            "analysis": self.analysis,
            "reference_type": self.reference_type,
            "current_type": self.current_type,
            "metrics": self.metrics,
            "findings": [finding.as_dict() for finding in self.findings],
        }


@dataclass
class Thresholds:
    psi_warn: float
    psi_alert: float
    p_value_alert: float
    missing_warn: float
    missing_alert: float
    numeric_bins: int


def _worst(severities: list[str]) -> str:
    return max(severities, key=lambda s: _SEVERITY_ORDER[s], default=OK) if severities else OK


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _plural(count: int, forms: tuple[str, str, str]) -> str:
    """Русское склонение: 1 значение, 2 значения, 5 значений."""
    tail = abs(count) % 100
    if 11 <= tail <= 14:
        return forms[2]
    tail %= 10
    if tail == 1:
        return forms[0]
    if 2 <= tail <= 4:
        return forms[1]
    return forms[2]


# ---------------------------------------------------------------------------
# Числовые колонки
# ---------------------------------------------------------------------------


def _bin_edges(sorted_values: list[float], bins: int) -> list[float]:
    """Границы по квантилям reference: равнонаполненные бины устойчивее равномерных."""
    edges = [quantile(sorted_values, i / bins) for i in range(1, bins)]
    unique_edges: list[float] = []
    for edge in edges:
        if not unique_edges or edge > unique_edges[-1]:
            unique_edges.append(edge)
    return unique_edges


def _bin_counts(values: list[float], edges: list[float]) -> list[int]:
    counts = [0] * (len(edges) + 1)
    for value in values:
        index = 0
        # Бинов мало (обычно 10), линейный поиск дешевле bisect-импорта в цикле.
        while index < len(edges) and value > edges[index]:
            index += 1
        counts[index] += 1
    return counts


def smoothed_shares(counts: list[int]) -> list[float]:
    """Доли с поправкой Джеффриса (+0.5).

    Без неё пустая корзина превращает PSI в произвольно большое число:
    ln(0.15 / 1e-10) даёт 21, и метрика перестаёт что-либо значить. С +0.5
    новая категория всё ещё даёт крупный вклад, но в сопоставимом масштабе.
    """
    total = sum(counts) + 0.5 * len(counts)
    if total <= 0:
        return [0.0] * len(counts)
    return [(count + 0.5) / total for count in counts]


def _shares(counts: list[int]) -> list[float]:
    total = sum(counts) or 1
    return [count / total for count in counts]


def _numeric_drift(
    ref: ColumnProfile, cur: ColumnProfile, thresholds: Thresholds
) -> tuple[dict[str, object], list[Finding]]:
    findings: list[Finding] = []
    ref_values = list(ref.numeric_sample)
    cur_values = list(cur.numeric_sample)
    metrics: dict[str, object] = {}

    if not ref_values or not cur_values:
        return metrics, findings

    edges = _bin_edges(ref_values, thresholds.numeric_bins)
    psi_value = psi(
        smoothed_shares(_bin_counts(ref_values, edges)),
        smoothed_shares(_bin_counts(cur_values, edges)),
    )
    ks_stat, p_value = ks_two_sample(ref_values, cur_values)

    ref_stats, cur_stats = ref.numeric, cur.numeric
    assert ref_stats and cur_stats  # numeric-профиль всегда есть у numeric-колонки

    effect = cohens_d(
        ref_stats.mean, ref_stats.std, ref_stats.count, cur_stats.mean, cur_stats.std, cur_stats.count
    )
    mean_shift = cur_stats.mean - ref_stats.mean
    relative = abs(mean_shift) / abs(ref_stats.mean) if abs(ref_stats.mean) > 1e-12 else None

    metrics.update(
        {
            "psi": round(psi_value, 4),
            "ks_statistic": round(ks_stat, 4),
            "ks_p_value": round(p_value, 6),
            "cohens_d": round(effect, 4),
            "mean_reference": round(ref_stats.mean, 4),
            "mean_current": round(cur_stats.mean, 4),
            "mean_shift": round(mean_shift, 4),
            "median_reference": round(ref_stats.median, 4),
            "median_current": round(cur_stats.median, 4),
            "std_reference": round(ref_stats.std, 4),
            "std_current": round(cur_stats.std, 4),
            "sample_reference": len(ref_values),
            "sample_current": len(cur_values),
        }
    )
    if relative is not None:
        metrics["mean_shift_relative"] = round(relative, 4)

    if psi_value >= thresholds.psi_alert:
        findings.append(
            Finding(
                "distribution.psi",
                ALERT,
                f"Распределение сильно сместилось: PSI {psi_value:.2f} "
                f"(порог {thresholds.psi_alert:g})",
                {"psi": round(psi_value, 4)},
            )
        )
    elif psi_value >= thresholds.psi_warn:
        findings.append(
            Finding(
                "distribution.psi",
                WARN,
                f"Заметное смещение распределения: PSI {psi_value:.2f}",
                {"psi": round(psi_value, 4)},
            )
        )

    # На больших выборках p-value значимо почти всегда, поэтому требуем
    # ещё и заметный размер расхождения самой CDF.
    if p_value < thresholds.p_value_alert and ks_stat >= 0.1:
        findings.append(
            Finding(
                "distribution.ks",
                WARN if ks_stat < 0.2 else ALERT,
                f"KS-тест: D={ks_stat:.3f}, p={p_value:.2e} — выборки из разных распределений",
                {"ks_statistic": round(ks_stat, 4), "p_value": p_value},
            )
        )

    if abs(effect) >= 0.5:
        findings.append(
            Finding(
                "distribution.mean_shift",
                WARN if abs(effect) < 0.8 else ALERT,
                f"Среднее сдвинулось с {ref_stats.mean:.4g} на {cur_stats.mean:.4g} "
                f"(эффект d={effect:.2f})",
                {"cohens_d": round(effect, 4), "shift": round(mean_shift, 4)},
            )
        )

    if cur_stats.min < ref_stats.min or cur_stats.max > ref_stats.max:
        findings.append(
            Finding(
                "distribution.range_expanded",
                INFO,
                f"Диапазон вышел за границы reference: "
                f"[{ref_stats.min:.4g}; {ref_stats.max:.4g}] → [{cur_stats.min:.4g}; {cur_stats.max:.4g}]",
                {
                    "reference": [ref_stats.min, ref_stats.max],
                    "current": [cur_stats.min, cur_stats.max],
                },
            )
        )

    if ref_stats.negatives == 0 and cur_stats.negatives > 0:
        findings.append(
            Finding(
                "distribution.negatives_appeared",
                WARN,
                f"Появились отрицательные значения: {cur_stats.negatives}",
                {"count": cur_stats.negatives},
            )
        )

    if ref_stats.std > 1e-12 and cur_stats.std > 1e-12:
        ratio = cur_stats.std / ref_stats.std
        if ratio >= 2.0 or ratio <= 0.5:
            findings.append(
                Finding(
                    "distribution.variance_change",
                    WARN,
                    f"Разброс изменился в {ratio:.2f}× "
                    f"(std {ref_stats.std:.4g} → {cur_stats.std:.4g})",
                    {"std_ratio": round(ratio, 3)},
                )
            )

    return metrics, findings


# ---------------------------------------------------------------------------
# Категориальные колонки
# ---------------------------------------------------------------------------


def _aligned_categories(
    ref: Counter, cur: Counter, limit: int = CATEGORY_LIMIT
) -> tuple[list[str], list[int], list[int]]:
    """Общий алфавит категорий: топ по суммарной частоте + __other__."""
    combined: Counter = Counter()
    combined.update(ref)
    combined.update(cur)
    keys = [key for key, _ in combined.most_common(limit)]

    ref_counts = [ref.get(key, 0) for key in keys]
    cur_counts = [cur.get(key, 0) for key in keys]

    rest_ref = sum(ref.values()) - sum(ref_counts)
    rest_cur = sum(cur.values()) - sum(cur_counts)
    if rest_ref or rest_cur:
        keys.append("__other__")
        ref_counts.append(rest_ref)
        cur_counts.append(rest_cur)
    return keys, ref_counts, cur_counts


def _categorical_drift(
    ref: ColumnProfile, cur: ColumnProfile, thresholds: Thresholds
) -> tuple[dict[str, object], list[Finding]]:
    findings: list[Finding] = []
    metrics: dict[str, object] = {}

    if not ref.categories or not cur.categories:
        return metrics, findings

    keys, ref_counts, cur_counts = _aligned_categories(ref.categories, cur.categories)
    ref_shares = _shares(ref_counts)
    cur_shares = _shares(cur_counts)

    # PSI считаем на сглаженных долях, остальное — на настоящих:
    # TVD и JSD с нулями ведут себя корректно, а PSI нет.
    psi_value = psi(smoothed_shares(ref_counts), smoothed_shares(cur_counts))
    jsd = jensen_shannon_divergence(ref_shares, cur_shares)
    tvd = total_variation_distance(ref_shares, cur_shares)
    chi2, df, p_value = chi_square_two_sample(ref_counts, cur_counts)

    new_categories = sorted(set(cur.categories) - set(ref.categories))
    gone_categories = sorted(set(ref.categories) - set(cur.categories))

    metrics.update(
        {
            "psi": round(psi_value, 4),
            "jensen_shannon": round(jsd, 4),
            "total_variation": round(tvd, 4),
            "chi2": round(chi2, 3),
            "chi2_df": df,
            "chi2_p_value": round(p_value, 6),
            "cardinality_reference": ref.unique,
            "cardinality_current": cur.unique,
            "new_categories": new_categories[:25],
            "missing_categories": gone_categories[:25],
            "top_shifts": _top_share_shifts(keys, ref_shares, cur_shares),
        }
    )

    if psi_value >= thresholds.psi_alert:
        findings.append(
            Finding(
                "category.psi",
                ALERT,
                f"Состав категорий сильно изменился: PSI {psi_value:.2f}",
                {"psi": round(psi_value, 4)},
            )
        )
    elif psi_value >= thresholds.psi_warn:
        findings.append(
            Finding(
                "category.psi",
                WARN,
                f"Состав категорий сместился: PSI {psi_value:.2f}",
                {"psi": round(psi_value, 4)},
            )
        )

    if p_value < thresholds.p_value_alert and tvd >= 0.05:
        findings.append(
            Finding(
                "category.chi_square",
                WARN,
                f"Хи-квадрат: chi2={chi2:.1f}, df={df}, p={p_value:.2e}; "
                f"переехало {_pct(tvd)} массы",
                {"chi2": round(chi2, 3), "p_value": p_value, "tvd": round(tvd, 4)},
            )
        )

    if new_categories:
        findings.append(
            Finding(
                "category.new",
                WARN,
                f"Новые категории ({len(new_categories)}): "
                + ", ".join(new_categories[:5])
                + ("…" if len(new_categories) > 5 else ""),
                {"values": new_categories[:25], "count": len(new_categories)},
            )
        )

    if gone_categories:
        findings.append(
            Finding(
                "category.disappeared",
                INFO,
                f"Пропали категории ({len(gone_categories)}): "
                + ", ".join(gone_categories[:5])
                + ("…" if len(gone_categories) > 5 else ""),
                {"values": gone_categories[:25], "count": len(gone_categories)},
            )
        )

    if ref.unique and cur.unique:
        ratio = cur.unique / ref.unique
        if ratio >= 1.5 or ratio <= 0.67:
            findings.append(
                Finding(
                    "cardinality.change",
                    WARN,
                    f"Кардинальность изменилась: {ref.unique} → {cur.unique} "
                    + _plural(cur.unique, ("значение", "значения", "значений")),
                    {"reference": ref.unique, "current": cur.unique},
                )
            )

    return metrics, findings


def _top_share_shifts(
    keys: list[str], ref_shares: list[float], cur_shares: list[float], limit: int = 5
) -> list[dict[str, object]]:
    shifts = [
        {
            "value": key,
            "reference": round(ref_share, 4),
            "current": round(cur_share, 4),
            "delta": round(cur_share - ref_share, 4),
        }
        for key, ref_share, cur_share in zip(keys, ref_shares, cur_shares)
    ]
    shifts.sort(key=lambda item: abs(item["delta"]), reverse=True)
    return [shift for shift in shifts[:limit] if abs(shift["delta"]) >= 0.005]


# ---------------------------------------------------------------------------
# Общие проверки — применимы к любому типу
# ---------------------------------------------------------------------------


def _missingness_findings(
    ref: ColumnProfile, cur: ColumnProfile, thresholds: Thresholds
) -> list[Finding]:
    delta = cur.missing_rate - ref.missing_rate
    if abs(delta) < thresholds.missing_warn:
        return []

    severity = ALERT if abs(delta) >= thresholds.missing_alert else WARN
    if ref.missing == 0 and cur.missing > 0:
        return [
            Finding(
                "missing.appeared",
                ALERT,
                f"Пропуски появились там, где их не было: 0% → {_pct(cur.missing_rate)}",
                {"reference": 0.0, "current": round(cur.missing_rate, 6)},
            )
        ]
    direction = "выросли" if delta > 0 else "снизились"
    return [
        Finding(
            "missing.rate_change",
            severity,
            f"Пропуски {direction}: {_pct(ref.missing_rate)} → {_pct(cur.missing_rate)}",
            {
                "reference": round(ref.missing_rate, 6),
                "current": round(cur.missing_rate, 6),
                "delta": round(delta, 6),
            },
        )
    ]


def _structural_findings(ref: ColumnProfile, cur: ColumnProfile) -> list[Finding]:
    findings: list[Finding] = []

    if ref.inferred_type != cur.inferred_type:
        findings.append(
            Finding(
                "schema.type_changed",
                ALERT,
                f"Тип изменился: {ref.inferred_type} → {cur.inferred_type}",
                {"reference": ref.inferred_type, "current": cur.inferred_type},
            )
        )
    elif ref.base_type != cur.base_type:
        findings.append(
            Finding(
                "schema.base_type_changed",
                WARN,
                f"Внутреннее представление изменилось: {ref.base_type} → {cur.base_type}",
                {"reference": ref.base_type, "current": cur.base_type},
            )
        )

    if cur.mixed_types and not ref.mixed_types:
        findings.append(
            Finding(
                "quality.mixed_types",
                WARN,
                "В колонке появились значения разных типов: "
                + ", ".join(f"{k} {_pct(v)}" for k, v in sorted(cur.type_shares.items())),
                {"type_shares": {k: round(v, 4) for k, v in cur.type_shares.items()}},
            )
        )

    if ref.unique > 1 and cur.unique == 1 and cur.present:
        findings.append(
            Finding(
                "quality.became_constant",
                ALERT,
                f"Колонка схлопнулась в константу: {cur.samples[0] if cur.samples else '?'}",
                {"value": cur.samples[0] if cur.samples else None},
            )
        )
    elif ref.unique == 1 and cur.unique > 1:
        findings.append(
            Finding(
                "quality.no_longer_constant",
                INFO,
                f"Раньше константа, теперь {cur.unique} "
                + _plural(cur.unique, ("значение", "значения", "значений")),
                {"current_unique": cur.unique},
            )
        )

    if ref.present and not cur.present:
        findings.append(
            Finding(
                "quality.became_empty",
                ALERT,
                "Колонка полностью опустела",
                {},
            )
        )

    return findings


def _identifier_findings(ref: ColumnProfile, cur: ColumnProfile) -> list[Finding]:
    """Пересечение идентификаторов — классический признак утечки."""
    findings: list[Finding] = []
    if not ref.value_hashes or not cur.value_hashes:
        return findings

    shared = ref.value_hashes & cur.value_hashes
    if not shared:
        return findings

    share_of_current = len(shared) / max(len(cur.value_hashes), 1)
    severity = ALERT if share_of_current >= 0.5 else WARN if share_of_current >= 0.05 else INFO
    findings.append(
        Finding(
            "leakage.identifier_overlap",
            severity,
            f"{len(shared)} идентификаторов встречаются в обеих выгрузках "
            f"({_pct(share_of_current)} от current) — возможная утечка или повторная выгрузка",
            {
                "shared": len(shared),
                "share_of_current": round(share_of_current, 4),
                "approximate": ref.hashes_capped or cur.hashes_capped,
            },
        )
    )
    return findings


# ---------------------------------------------------------------------------
# Сборка отчёта
# ---------------------------------------------------------------------------


def _analysis_kind(ref: ColumnProfile, cur: ColumnProfile) -> str:
    if ref.inferred_type in {"integer", "float"} and cur.inferred_type in {"integer", "float"}:
        return "numeric"
    if ref.inferred_type in {"categorical", "boolean"} and cur.inferred_type in {
        "categorical",
        "boolean",
    }:
        return "categorical"
    if ref.inferred_type == "identifier" or cur.inferred_type == "identifier":
        return "identifier"
    if ref.inferred_type == "datetime" and cur.inferred_type == "datetime":
        return "datetime"
    if ref.inferred_type == "text" or cur.inferred_type == "text":
        return "text"
    return "structural"


def _datetime_metrics(ref: ColumnProfile, cur: ColumnProfile) -> tuple[dict, list[Finding]]:
    metrics: dict[str, object] = {}
    findings: list[Finding] = []
    if ref.datetime_range:
        metrics["reference_range"] = list(ref.datetime_range)
    if cur.datetime_range:
        metrics["current_range"] = list(cur.datetime_range)
    if ref.datetime_range and cur.datetime_range:
        if cur.datetime_range[0] < ref.datetime_range[0]:
            findings.append(
                Finding(
                    "datetime.earlier_than_reference",
                    INFO,
                    f"В current появились даты раньше начала reference: "
                    f"{cur.datetime_range[0]} < {ref.datetime_range[0]}",
                    {"reference_min": ref.datetime_range[0], "current_min": cur.datetime_range[0]},
                )
            )
        if cur.datetime_range[0] > ref.datetime_range[1]:
            findings.append(
                Finding(
                    "datetime.disjoint_period",
                    INFO,
                    f"Периоды не пересекаются: reference заканчивается "
                    f"{ref.datetime_range[1]}, current начинается {cur.datetime_range[0]}",
                    {"reference_max": ref.datetime_range[1], "current_min": cur.datetime_range[0]},
                )
            )
    return metrics, findings


def compare_columns(
    ref: ColumnProfile, cur: ColumnProfile, thresholds: Thresholds
) -> ColumnReport:
    analysis = _analysis_kind(ref, cur)
    findings = _structural_findings(ref, cur) + _missingness_findings(ref, cur, thresholds)
    metrics: dict[str, object] = {
        "missing_reference": round(ref.missing_rate, 6),
        "missing_current": round(cur.missing_rate, 6),
    }

    if analysis == "numeric":
        extra_metrics, extra_findings = _numeric_drift(ref, cur, thresholds)
    elif analysis == "categorical":
        extra_metrics, extra_findings = _categorical_drift(ref, cur, thresholds)
    elif analysis == "datetime":
        extra_metrics, extra_findings = _datetime_metrics(ref, cur)
    elif analysis == "identifier":
        extra_metrics, extra_findings = {
            "unique_reference": ref.unique,
            "unique_current": cur.unique,
        }, _identifier_findings(ref, cur)
    else:
        extra_metrics, extra_findings = {
            "unique_reference": ref.unique,
            "unique_current": cur.unique,
        }, []

    metrics.update(extra_metrics)
    findings.extend(extra_findings)

    return ColumnReport(
        column=ref.name,
        status=_worst([finding.severity for finding in findings]),
        analysis=analysis,
        reference_type=ref.inferred_type,
        current_type=cur.inferred_type,
        metrics=metrics,
        findings=findings,
    )


def compare_profiles(
    reference: TableProfile, current: TableProfile, thresholds: Thresholds
) -> dict[str, object]:
    ref_columns = set(reference.columns)
    cur_columns = set(current.columns)

    shared = [name for name in reference.column_names if name in cur_columns]
    added = [name for name in current.column_names if name not in ref_columns]
    removed = [name for name in reference.column_names if name not in cur_columns]

    column_reports = [
        compare_columns(reference.columns[name], current.columns[name], thresholds)
        for name in shared
    ]

    schema_findings: list[Finding] = []
    for name in added:
        profile = current.columns[name]
        schema_findings.append(
            Finding(
                "schema.column_added",
                WARN,
                f"Новая колонка: {name} ({profile.inferred_type})",
                {"column": name, "type": profile.inferred_type},
            )
        )
    for name in removed:
        profile = reference.columns[name]
        schema_findings.append(
            Finding(
                "schema.column_removed",
                ALERT,
                f"Колонка исчезла: {name} ({profile.inferred_type})",
                {"column": name, "type": profile.inferred_type},
            )
        )

    type_changed = [
        {
            "column": report.column,
            "from": report.reference_type,
            "to": report.current_type,
        }
        for report in column_reports
        if report.reference_type != report.current_type
    ]

    row_diff = current.row_count - reference.row_count
    row_change = row_diff / reference.row_count if reference.row_count else None

    all_findings = schema_findings + [f for report in column_reports for f in report.findings]
    alerts = sum(1 for f in all_findings if f.severity == ALERT)
    warnings = sum(1 for f in all_findings if f.severity == WARN)
    infos = sum(1 for f in all_findings if f.severity == INFO)

    ranked = sorted(
        (report for report in column_reports if report.status in {WARN, ALERT}),
        key=lambda report: (
            _SEVERITY_ORDER[report.status],
            float(report.metrics.get("psi") or 0.0),
        ),
        reverse=True,
    )

    verdict_status = ALERT if alerts else WARN if warnings else OK
    verdict_text = {
        ALERT: f"Найдено {alerts} критичных и {warnings} заметных изменений — данные разъехались",
        WARN: f"Найдено {warnings} заметных изменений — стоит посмотреть глазами",
        OK: "Значимых расхождений не найдено",
    }[verdict_status]

    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "reference": reference.as_dict(include_columns=False),
            "current": current.as_dict(include_columns=False),
        },
        "rows": {
            "reference": reference.row_count,
            "current": current.row_count,
            "diff": row_diff,
            "change": round(row_change, 4) if row_change is not None else None,
        },
        "schema": {
            "columns_reference": len(reference.columns),
            "columns_current": len(current.columns),
            "unchanged": [
                report.column for report in column_reports if report.reference_type == report.current_type
            ],
            "added": added,
            "removed": removed,
            "type_changed": type_changed,
            "findings": [finding.as_dict() for finding in schema_findings],
        },
        "columns": [report.as_dict() for report in column_reports],
        "summary": {
            "status": verdict_status,
            "verdict": verdict_text,
            "columns_analyzed": len(column_reports),
            "columns_with_findings": sum(1 for r in column_reports if r.findings),
            "alerts": alerts,
            "warnings": warnings,
            "notes": infos,
            "significant_changes": alerts + warnings,
            "top_offenders": [
                {"column": report.column, "status": report.status, "metrics": report.metrics}
                for report in ranked[:5]
            ],
        },
        "thresholds": asdict(thresholds),
    }
