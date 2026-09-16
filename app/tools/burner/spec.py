"""Описание того, что именно сгенерировать и как это испортить."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

ColumnType = Literal[
    "integer",
    "float",
    "categorical",
    "boolean",
    "datetime",
    "identifier",
    "text",
    "email",
    "phone",
    "money",
]

Distribution = Literal["normal", "lognormal", "uniform", "exponential"]
OutputFormat = Literal["csv", "tsv", "json", "ndjson"]


class ColumnDefects(BaseModel):
    """Порча, которая применяется к конкретной колонке."""

    null_rate: float = Field(default=0.0, ge=0.0, le=1.0, description="Доля пропусков")
    disguised_null_rate: float = Field(
        default=0.2,
        ge=0.0,
        le=1.0,
        description=(
            "Какая доля пропусков записывается словами («нет данных», «N/A») "
            "вместо пустоты. Именно такие пропуски не ловит проверка на NULL."
        ),
    )
    outlier_rate: float = Field(
        default=0.0, ge=0.0, le=0.5, description="Доля выбросов (числовые колонки)"
    )
    broken_format_rate: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Доля значений в чужом формате"
    )
    whitespace_rate: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Доля значений с лишними пробелами и NBSP"
    )
    unicode_trap_rate: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Доля значений с гомоглифами и zero-width"
    )
    mixed_type_rate: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Доля значений чужого типа"
    )
    case_noise_rate: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Доля значений со случайным регистром"
    )


class ColumnSpec(BaseModel):
    name: str = Field(max_length=64)
    type: ColumnType = "float"

    # Числовые параметры.
    distribution: Distribution = "normal"
    mean: float = 100.0
    std: float = 25.0
    minimum: float | None = None
    maximum: float | None = None
    decimals: int = Field(default=2, ge=0, le=6)

    # Категориальные параметры.
    categories: list[str] | None = None
    weights: list[float] | None = None
    #: 0 — ровные доли, 1 — почти всё в одной категории.
    imbalance: float = Field(default=0.0, ge=0.0, le=1.0)

    # Даты.
    start: str = "2024-01-01"
    end: str = "2026-01-01"

    defects: ColumnDefects = Field(default_factory=ColumnDefects)

    @field_validator("weights")
    @classmethod
    def _weights_match_categories(cls, weights, info):
        categories = info.data.get("categories")
        if weights and categories and len(weights) != len(categories):
            raise ValueError("Число весов должно совпадать с числом категорий")
        return weights


class DatasetDefects(BaseModel):
    """Порча уровня всей таблицы."""

    duplicate_row_rate: float = Field(
        default=0.0, ge=0.0, le=0.5, description="Доля строк-дублей"
    )
    empty_row_rate: float = Field(default=0.0, ge=0.0, le=0.2, description="Доля пустых строк")
    shuffled_columns: bool = Field(
        default=False, description="Переставить колонки местами относительно спецификации"
    )
    ragged_rows: bool = Field(
        default=False, description="У части строк не хватает полей (только для csv/tsv)"
    )
    bom: bool = Field(default=False, description="Добавить BOM в начало файла")
    crlf: bool = Field(default=False, description="Переводы строк в стиле Windows")


class DatasetSpec(BaseModel):
    rows: int = Field(default=1000, ge=1)
    columns: list[ColumnSpec] = Field(min_length=1)
    defects: DatasetDefects = Field(default_factory=DatasetDefects)
    format: OutputFormat = "csv"
    seed: int | None = Field(default=None, description="Фиксирует генерацию")
    name: str = Field(default="dataset", max_length=64)


class DriftSpec(BaseModel):
    """Чем current-выгрузка должна отличаться от reference."""

    numeric_shift: float = Field(
        default=0.6, ge=0.0, le=5.0, description="Сдвиг среднего в стандартных отклонениях"
    )
    variance_ratio: float = Field(default=1.0, ge=0.1, le=10.0, description="Во сколько раз изменить разброс")
    new_categories: int = Field(default=2, ge=0, le=20, description="Сколько новых категорий добавить")
    dropped_categories: int = Field(default=1, ge=0, le=20, description="Сколько категорий убрать")
    null_rate_increase: float = Field(default=0.12, ge=0.0, le=0.9)
    row_count_change: float = Field(
        default=0.15, ge=-0.9, le=5.0, description="Изменение числа строк, доля"
    )
    add_column: bool = True
    drop_column: bool = False
    change_type: bool = Field(default=True, description="Превратить целые в дробные")
    id_overlap: float = Field(
        default=0.1, ge=0.0, le=1.0, description="Доля идентификаторов, совпадающих с reference"
    )
