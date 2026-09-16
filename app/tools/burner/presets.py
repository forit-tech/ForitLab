"""Готовые схемы и сценарии порчи.

Пресет — это не «набор случайностей», а воспроизводимая история: какой
именно дефект вы хотите увидеть в своём пайплайне.
"""

from __future__ import annotations

import copy
import hashlib
import random
from datetime import date

from .spec import ColumnDefects, ColumnSpec, DatasetDefects, DatasetSpec, DriftSpec

REGIONS = ["MSK", "SPB", "NSK", "EKB", "KZN", "ROV"]
CHANNELS = ["web", "mobile", "partner", "offline"]
SEGMENTS = ["retail", "sme", "corporate"]


def base_columns() -> list[ColumnSpec]:
    """Схема, похожая на обычную клиентскую выгрузку."""
    return [
        ColumnSpec(name="client_id", type="identifier"),
        ColumnSpec(name="signup_date", type="datetime", start="2024-01-01", end="2025-06-30"),
        ColumnSpec(name="region", type="categorical", categories=REGIONS),
        ColumnSpec(name="channel", type="categorical", categories=CHANNELS),
        ColumnSpec(name="segment", type="categorical", categories=SEGMENTS),
        ColumnSpec(name="age", type="integer", mean=38, std=12, minimum=18, maximum=95),
        ColumnSpec(
            name="income",
            type="float",
            distribution="lognormal",
            mean=90000,
            std=45000,
            minimum=0,
        ),
        ColumnSpec(
            name="transaction_amount",
            type="money",
            distribution="lognormal",
            mean=4500,
            std=3000,
            minimum=0,
        ),
        ColumnSpec(name="score", type="float", mean=0.5, std=0.18, decimals=4),
        ColumnSpec(name="is_active", type="boolean"),
        ColumnSpec(name="email", type="email"),
        ColumnSpec(name="comment", type="text"),
    ]


def _with_defects(columns: list[ColumnSpec], mapping: dict[str, dict[str, float]]) -> list[ColumnSpec]:
    result = copy.deepcopy(columns)
    for column in result:
        if column.name in mapping:
            column.defects = ColumnDefects(**mapping[column.name])
    return result


PRESET_DESCRIPTIONS = {
    "clean": "Ровные данные без единого дефекта — базовая линия для сравнения.",
    "dirty": "Умеренная реальность: пропуски, выбросы, дубли, шум в регистре.",
    "etl_torture": "Всё сразу: BOM, CRLF, рваные строки, битые даты, unicode-ловушки.",
    "imbalanced": "Жёсткий перекос классов — 95% в одной категории.",
    "nulls": "Только пропуски, зато много и в самых неудобных местах.",
    "unicode": "Гомоглифы, zero-width и NBSP в ключевых для JOIN колонках.",
    "broken_dates": "Даты во всех форматах сразу, включая несуществующие.",
    "duplicates": "Каждая пятая строка — точный дубль другой.",
}


def preset_spec(name: str, rows: int, output_format: str, seed: int | None) -> DatasetSpec:
    columns = base_columns()
    defects = DatasetDefects()

    if name == "dirty":
        columns = _with_defects(
            columns,
            {
                "income": {"null_rate": 0.12, "outlier_rate": 0.02},
                "age": {"null_rate": 0.03, "outlier_rate": 0.01},
                "region": {"case_noise_rate": 0.15, "whitespace_rate": 0.1},
                "email": {"null_rate": 0.08, "broken_format_rate": 0.05},
                "transaction_amount": {"outlier_rate": 0.03, "mixed_type_rate": 0.02},
            },
        )
        defects = DatasetDefects(duplicate_row_rate=0.05)
    elif name == "etl_torture":
        columns = _with_defects(
            columns,
            {
                "signup_date": {"broken_format_rate": 0.25},
                "income": {"null_rate": 0.2, "mixed_type_rate": 0.1},
                "region": {"unicode_trap_rate": 0.3, "whitespace_rate": 0.2},
                "email": {"broken_format_rate": 0.2, "case_noise_rate": 0.3},
                "comment": {"unicode_trap_rate": 0.4},
                "transaction_amount": {"broken_format_rate": 0.15, "outlier_rate": 0.05},
            },
        )
        defects = DatasetDefects(
            duplicate_row_rate=0.08,
            empty_row_rate=0.02,
            ragged_rows=True,
            bom=True,
            crlf=True,
        )
    elif name == "imbalanced":
        for column in columns:
            if column.name in {"region", "segment"}:
                column.imbalance = 0.95
    elif name == "nulls":
        columns = _with_defects(
            columns,
            {
                "income": {"null_rate": 0.45},
                "age": {"null_rate": 0.2},
                "email": {"null_rate": 0.35},
                "comment": {"null_rate": 0.6},
                "score": {"null_rate": 0.15},
            },
        )
    elif name == "unicode":
        columns = _with_defects(
            columns,
            {
                "region": {"unicode_trap_rate": 0.5},
                "segment": {"unicode_trap_rate": 0.4},
                "email": {"unicode_trap_rate": 0.3},
                "comment": {"unicode_trap_rate": 0.6},
            },
        )
    elif name == "broken_dates":
        columns = _with_defects(columns, {"signup_date": {"broken_format_rate": 0.4}})
    elif name == "duplicates":
        defects = DatasetDefects(duplicate_row_rate=0.2)

    return DatasetSpec(
        rows=rows,
        columns=columns,
        defects=defects,
        format=output_format,  # type: ignore[arg-type]
        seed=seed,
        name=name,
    )


def drifted_spec(reference: DatasetSpec, drift: DriftSpec, seed: int | None) -> DatasetSpec:
    """Строит current-выгрузку из reference по описанию дрейфа."""
    current = copy.deepcopy(reference)
    current.name = f"{reference.name}-current"
    current.seed = (seed if seed is not None else 0) + 1
    current.rows = max(1, int(reference.rows * (1 + drift.row_count_change)))

    for column in current.columns:
        if column.type in {"integer", "float", "money"}:
            column.mean += drift.numeric_shift * column.std
            column.std *= drift.variance_ratio
            if drift.change_type and column.type == "integer":
                # Целые превращаются в дробные — самая частая поломка контракта.
                column.type = "float"
                column.decimals = 1
        if column.type == "categorical" and column.categories:
            categories = list(column.categories)
            for index in range(drift.dropped_categories):
                if len(categories) > 2:
                    categories.pop()
            for index in range(drift.new_categories):
                categories.append(f"NEW_{index + 1}" if index else "UNKNOWN")
            column.categories = categories
            column.weights = None
    if drift.null_rate_increase:
        # Всплеск пропусков бьёт по нескольким колонкам, а не по всем сразу:
        # «во всей выгрузке стало больше NULL» — это не дрейф, а сбой выгрузки.
        affected = [c for c in current.columns if c.type not in {"identifier", "boolean"}][:2]
        for column in affected:
            column.defects.null_rate = min(
                1.0, column.defects.null_rate + drift.null_rate_increase
            )
            # Пропуски пишем пустотой: иначе колонка сменит тип, и отчёт
            # покажет смену схемы вместо роста пропусков.
            column.defects.disguised_null_rate = 0.0

    if drift.add_column:
        current.columns.append(
            ColumnSpec(name="client_type", type="categorical", categories=["a", "b", "c"])
        )
    if drift.drop_column and len(current.columns) > 2:
        current.columns = [c for c in current.columns if c.name != "comment"]

    return current


#: Дефекты, из которых собирается «странный датасет дня».
WEIRD_CASES: list[tuple[str, dict[str, dict[str, float]], DatasetDefects, str]] = [
    (
        "silent_duplicates",
        {},
        DatasetDefects(duplicate_row_rate=0.18),
        "Каждая шестая строка — точный дубль другой. Агрегаты завышены, а COUNT(*) выглядит нормально.",
    ),
    (
        "homoglyph_join_killer",
        {"region": {"unicode_trap_rate": 0.35}},
        DatasetDefects(),
        "В region часть латинских букв заменена визуально идентичными кириллическими: "
        "JOIN по этой колонке молча теряет строки.",
    ),
    (
        "null_flood",
        {"income": {"null_rate": 0.42}},
        DatasetDefects(),
        "Колонка income потеряла 42% значений, но заполнены они не пустотой, "
        "а словами вроде «нет данных» — наивная проверка на NULL их не поймает.",
    ),
    (
        "outlier_bomb",
        {"transaction_amount": {"outlier_rate": 0.04}},
        DatasetDefects(),
        "4% сумм умножены на сотни. Среднее уехало, медиана — нет.",
    ),
    (
        "date_chaos",
        {"signup_date": {"broken_format_rate": 0.3}},
        DatasetDefects(),
        "Даты в шести форматах сразу, включая 2024-02-31 и unix timestamp.",
    ),
    (
        "whitespace_ghosts",
        {"segment": {"whitespace_rate": 0.4}},
        DatasetDefects(),
        "В segment у части значений неразрывные пробелы по краям: GROUP BY даёт лишние группы.",
    ),
    (
        "ragged_file",
        {},
        DatasetDefects(ragged_rows=True, bom=True, crlf=True),
        "BOM, CRLF и строки с нехваткой полей — файл, на котором спотыкается половина парсеров.",
    ),
    (
        "class_collapse",
        {},
        DatasetDefects(),
        "Категориальные колонки перекошены до 95/5: модель, обученная на этом, выучит константу.",
    ),
]


def weird_of_the_day(
    for_date: date, rows: int, output_format: str
) -> tuple[DatasetSpec, str, str]:
    """Детерминированно по дате выбирает один подложенный дефект.

    Один и тот же день даёт один и тот же файл — иначе игру «найди, что не
    так» невозможно ни обсудить, ни перепроверить.
    """
    digest = hashlib.sha256(for_date.isoformat().encode()).hexdigest()
    seed = int(digest[:12], 16)
    case_id, column_defects, dataset_defects, answer = WEIRD_CASES[seed % len(WEIRD_CASES)]

    columns = _with_defects(base_columns(), column_defects)
    if case_id == "class_collapse":
        for column in columns:
            if column.type == "categorical":
                column.imbalance = 0.95

    rng = random.Random(seed)
    spec = DatasetSpec(
        rows=rows,
        columns=columns,
        defects=dataset_defects,
        format=output_format,  # type: ignore[arg-type]
        seed=rng.randint(1, 10**9),
        name=f"weird-{for_date.isoformat()}",
    )
    return spec, case_id, answer
