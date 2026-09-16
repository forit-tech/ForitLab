"""Профилирование колонок: тип, пропуски, распределение, категории.

Профиль — это то, что остаётся от выгрузки после чтения. Дальше сравнение
работает только с профилями, а исходную таблицу можно отпустить: на Host-0
память дороже, чем повторный парсинг.
"""

from __future__ import annotations

import random
import re
from array import array
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from .stats import mean, quantile, skewness, stdev
from .tabular import Table

#: Сколько числовых значений оставляем на колонку для KS-теста.
#: Полный массив держать незачем: при 1e4+ точках D стабилен до третьего знака.
MAX_NUMERIC_SAMPLE = 20_000
SAMPLE_SEED = 20260916

#: Потолок множества хешей значений. Оно нужно для двух вещей: точного числа
#: уникальных (Counter обрезан лимитом категорий и для этого не годится) и
#: пересечения идентификаторов между выгрузками.
MAX_VALUE_HASHES = 100_000

BOOL_TRUE = frozenset({"true", "yes", "y", "1", "t", "да", "истина"})
BOOL_FALSE = frozenset({"false", "no", "n", "0", "f", "нет", "ложь"})

_INT_RE = re.compile(r"^[+-]?\d+$")
#: Числа с пробелами-разделителями и запятой как десятичной точкой — обычное
#: дело для выгрузок из Excel и 1С.
_SPACES_RE = re.compile(r"[\s  ]")

DATE_FORMATS = (
    "%Y-%m-%d",
    "%d.%m.%Y",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%Y/%m/%d",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%d.%m.%Y %H:%M",
    "%d.%m.%Y %H:%M:%S",
    "%Y%m%d",
)

#: Типы, для которых считаем числовой дрейф.
NUMERIC_TYPES = frozenset({"integer", "float"})
#: Типы, для которых считаем категориальный дрейф.
DISCRETE_TYPES = frozenset({"categorical", "boolean"})


def parse_number(raw: str) -> float | None:
    text = _SPACES_RE.sub("", raw)
    if not text:
        return None
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    try:
        value = float(text)
    except ValueError:
        return None
    # inf/nan формально парсятся, но как значения признака это мусор.
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def is_integer_text(raw: str) -> bool:
    return bool(_INT_RE.match(_SPACES_RE.sub("", raw)))


def looks_like_datetime(text: str) -> bool:
    """Дешёвый фильтр перед strptime.

    Разбор даты — самая дорогая часть профилирования, а подавляющее
    большинство ячеек датами не являются. Отсекаем их по виду.
    """
    if len(text) < 6 or len(text) > 40:
        return False
    if not text[0].isdigit():
        return False
    return text.isdigit() or any(sep in text for sep in "-/.")


def parse_datetime(raw: str) -> datetime | None:
    text = raw.strip()
    if not looks_like_datetime(text):
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if isinstance(parsed, datetime) else datetime.combine(parsed, datetime.min.time())
    except ValueError:
        pass
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def parse_bool(raw: str) -> bool | None:
    text = raw.strip().lower()
    if text in BOOL_TRUE:
        return True
    if text in BOOL_FALSE:
        return False
    return None


@dataclass
class NumericSummary:
    count: int
    min: float
    max: float
    mean: float
    std: float
    median: float
    p01: float
    p05: float
    p25: float
    p75: float
    p95: float
    p99: float
    skew: float
    zeros: int
    negatives: int

    def as_dict(self) -> dict[str, float | int]:
        return {
            "count": self.count,
            "min": round(self.min, 6),
            "max": round(self.max, 6),
            "mean": round(self.mean, 6),
            "std": round(self.std, 6),
            "median": round(self.median, 6),
            "p01": round(self.p01, 6),
            "p05": round(self.p05, 6),
            "p25": round(self.p25, 6),
            "p75": round(self.p75, 6),
            "p95": round(self.p95, 6),
            "p99": round(self.p99, 6),
            "skew": round(self.skew, 4),
            "zeros": self.zeros,
            "negatives": self.negatives,
        }


@dataclass
class ColumnProfile:
    name: str
    inferred_type: str
    base_type: str
    total: int
    present: int
    missing: int
    unique: int
    unique_capped: bool
    type_shares: dict[str, float]
    mixed_types: bool
    numeric: NumericSummary | None = None
    categories: Counter = field(default_factory=Counter)
    text_lengths: tuple[int, int, float] | None = None
    datetime_range: tuple[str, str] | None = None
    samples: list[str] = field(default_factory=list)
    #: Отсортированная подвыборка численных значений — только для KS.
    numeric_sample: array = field(default_factory=lambda: array("d"))
    #: Хеши значений: точный подсчёт уникальных и поиск пересечений.
    value_hashes: set[int] = field(default_factory=set)
    hashes_capped: bool = False

    @property
    def missing_rate(self) -> float:
        return self.missing / self.total if self.total else 0.0

    @property
    def uniqueness_ratio(self) -> float:
        return self.unique / self.present if self.present else 0.0

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "name": self.name,
            "type": self.inferred_type,
            "base_type": self.base_type,
            "rows": self.total,
            "present": self.present,
            "missing": self.missing,
            "missing_rate": round(self.missing_rate, 6),
            "unique": self.unique,
            "unique_capped": self.unique_capped,
            "uniqueness_ratio": round(self.uniqueness_ratio, 6),
            "mixed_types": self.mixed_types,
            "type_shares": {k: round(v, 4) for k, v in self.type_shares.items() if v > 0},
        }
        if self.numeric:
            payload["numeric"] = self.numeric.as_dict()
        if self.categories:
            payload["top_categories"] = [
                {"value": value, "count": count, "share": round(count / self.present, 6)}
                for value, count in self.categories.most_common(15)
            ]
        if self.text_lengths:
            low, high, avg = self.text_lengths
            payload["length"] = {"min": low, "max": high, "avg": round(avg, 2)}
        if self.datetime_range:
            payload["range"] = {"min": self.datetime_range[0], "max": self.datetime_range[1]}
        if self.samples:
            payload["samples"] = self.samples
        return payload


@dataclass
class TableProfile:
    name: str
    row_count: int
    source_format: str
    encoding: str
    delimiter: str | None
    truncated: bool
    dropped_columns: list[str]
    columns: dict[str, ColumnProfile]

    @property
    def column_names(self) -> list[str]:
        return list(self.columns)

    def as_dict(self, *, include_columns: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "name": self.name,
            "rows": self.row_count,
            "columns": len(self.columns),
            "format": self.source_format,
            "encoding": self.encoding,
            "delimiter": self.delimiter,
            "truncated": self.truncated,
        }
        if self.dropped_columns:
            payload["dropped_columns"] = self.dropped_columns
        if include_columns:
            payload["column_profiles"] = [profile.as_dict() for profile in self.columns.values()]
        return payload


def _numeric_summary(values: list[float]) -> NumericSummary:
    ordered = sorted(values)
    return NumericSummary(
        count=len(ordered),
        min=ordered[0],
        max=ordered[-1],
        mean=mean(ordered),
        std=stdev(ordered),
        median=quantile(ordered, 0.5),
        p01=quantile(ordered, 0.01),
        p05=quantile(ordered, 0.05),
        p25=quantile(ordered, 0.25),
        p75=quantile(ordered, 0.75),
        p95=quantile(ordered, 0.95),
        p99=quantile(ordered, 0.99),
        skew=skewness(ordered),
        zeros=sum(1 for v in ordered if v == 0.0),
        negatives=sum(1 for v in ordered if v < 0.0),
    )


def _downsample(sorted_values: list[float]) -> array:
    """Равномерная случайная подвыборка с фиксированным seed — воспроизводимо."""
    if len(sorted_values) <= MAX_NUMERIC_SAMPLE:
        return array("d", sorted_values)
    rng = random.Random(SAMPLE_SEED)
    picked = rng.sample(range(len(sorted_values)), MAX_NUMERIC_SAMPLE)
    picked.sort()
    return array("d", (sorted_values[i] for i in picked))


def _classify(
    *,
    present: int,
    unique: int,
    shares: dict[str, float],
    avg_length: float,
    space_share: float,
    id_uniqueness_ratio: float,
    max_categories: int,
) -> tuple[str, str]:
    """Возвращает (inferred_type, base_type).

    base_type — как значения выглядят технически, inferred_type — как их
    имеет смысл анализировать. Целочисленный client_id технически integer,
    но считать по нему PSI бессмысленно, поэтому он identifier.
    """
    if present == 0:
        return "empty", "empty"

    numeric_share = shares.get("integer", 0.0) + shares.get("float", 0.0)
    if shares.get("boolean", 0.0) >= 0.99:
        base = "boolean"
    elif shares.get("integer", 0.0) >= 0.99:
        base = "integer"
    elif numeric_share >= 0.99:
        base = "float"
    elif shares.get("datetime", 0.0) >= 0.95:
        base = "datetime"
    else:
        base = "string"

    if base == "boolean":
        return "boolean", base
    if base == "datetime":
        return "datetime", base

    # Идентификатор — почти уникальный, короткий и без пробелов. Уникальность
    # сама по себе ничего не доказывает: свободный текст тоже уникален, и
    # считать по нему пересечения или PSI бессмысленно.
    high_cardinality = unique >= max(50, int(present * id_uniqueness_ratio))
    looks_like_key = avg_length <= 64 and space_share <= 0.2
    if high_cardinality and base in {"integer", "string"} and looks_like_key:
        return "identifier", base
    if base in {"integer", "float"}:
        return "integer" if base == "integer" else "float", base

    # Строки: мало уникальных — категория, много — свободный текст.
    category_cap = min(max_categories, max(25, int(present * 0.2)))
    if unique <= category_cap:
        return "categorical", base
    return "text", base


def profile_column(
    name: str,
    values: list[str | None],
    *,
    max_categories: int,
    id_uniqueness_ratio: float,
) -> ColumnProfile:
    total = len(values)
    present_values = [v for v in values if v is not None]
    present = len(present_values)
    missing = total - present

    counter: Counter = Counter()
    numeric_values: list[float] = []
    datetimes: list[datetime] = []
    kinds: Counter = Counter()
    hashes: set[int] = set()
    hashes_capped = False
    length_min, length_max, length_sum = None, 0, 0
    with_spaces = 0

    for raw in present_values:
        if len(counter) < max_categories or raw in counter:
            counter[raw] += 1
        if len(hashes) < MAX_VALUE_HASHES:
            hashes.add(hash(raw))
        else:
            hashes_capped = True

        size = len(raw)
        if " " in raw:
            with_spaces += 1
        length_min = size if length_min is None else min(length_min, size)
        length_max = max(length_max, size)
        length_sum += size

        number = parse_number(raw)
        if number is not None:
            numeric_values.append(number)
            kinds["integer" if is_integer_text(raw) else "float"] += 1
            continue
        if parse_bool(raw) is not None:
            kinds["boolean"] += 1
            continue
        parsed_dt = parse_datetime(raw)
        if parsed_dt is not None:
            datetimes.append(parsed_dt)
            kinds["datetime"] += 1
            continue
        kinds["string"] += 1

    # 0/1 парсятся как целые, но если других значений нет — это флаг.
    if kinds and set(counter) <= {"0", "1"} and present:
        kinds = Counter({"boolean": present})

    shares = {kind: count / present for kind, count in kinds.items()} if present else {}
    unique = len(hashes)
    unique_capped = hashes_capped

    avg_length = length_sum / present if present else 0.0
    inferred, base = _classify(
        present=present,
        unique=unique,
        shares=shares,
        avg_length=avg_length,
        space_share=with_spaces / present if present else 0.0,
        id_uniqueness_ratio=id_uniqueness_ratio,
        max_categories=max_categories,
    )

    dominant = max(shares.values(), default=1.0)
    mixed = present > 0 and dominant < 0.95 and len(shares) > 1

    profile = ColumnProfile(
        name=name,
        inferred_type=inferred,
        base_type=base,
        total=total,
        present=present,
        missing=missing,
        unique=unique,
        unique_capped=unique_capped,
        type_shares=shares,
        mixed_types=mixed,
        samples=[value for value, _ in counter.most_common(3)],
        value_hashes=hashes,
        hashes_capped=hashes_capped,
    )

    if inferred in NUMERIC_TYPES and numeric_values:
        ordered = sorted(numeric_values)
        profile.numeric = _numeric_summary(ordered)
        profile.numeric_sample = _downsample(ordered)
    if inferred in DISCRETE_TYPES or inferred == "text":
        profile.categories = counter
    if inferred == "identifier":
        # Сами значения не нужны: пересечение считаем по множеству хешей.
        profile.categories = Counter()
    if inferred == "datetime" and datetimes:
        profile.datetime_range = (min(datetimes).isoformat(), max(datetimes).isoformat())
    if length_min is not None:
        profile.text_lengths = (length_min, length_max, length_sum / present)

    return profile


def profile_table(
    table: Table, *, max_categories: int, id_uniqueness_ratio: float
) -> TableProfile:
    columns = {
        name: profile_column(
            name,
            table.column(name),
            max_categories=max_categories,
            id_uniqueness_ratio=id_uniqueness_ratio,
        )
        for name in table.columns
    }
    return TableProfile(
        name=table.name,
        row_count=table.row_count,
        source_format=table.source_format,
        encoding=table.encoding,
        delimiter=table.delimiter,
        truncated=table.truncated,
        dropped_columns=table.dropped_columns,
        columns=columns,
    )
