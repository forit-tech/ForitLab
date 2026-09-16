"""Профилирование: типы, пропуски, кардинальность, чтение файлов."""

from __future__ import annotations

import pytest

from app.errors import UnprocessableDataError
from app.tools.drift.profiling import profile_column, profile_table
from app.tools.drift.tabular import load_table


def profile(values, **kwargs):
    return profile_column(
        "col",
        values,
        max_categories=kwargs.pop("max_categories", 2000),
        id_uniqueness_ratio=kwargs.pop("id_uniqueness_ratio", 0.95),
    )


def test_integers_are_integer() -> None:
    assert profile([str(v) for v in range(10, 40)] * 3).inferred_type == "integer"


def test_floats_are_float() -> None:
    assert profile([f"{v / 3:.3f}" for v in range(100)] * 2).inferred_type == "float"


def test_comma_decimal_is_numeric() -> None:
    result = profile(["1,5", "2,25", "3,75"] * 40)
    assert result.inferred_type == "float"
    assert result.numeric is not None


def test_low_cardinality_strings_are_categorical() -> None:
    assert profile(["MSK", "SPB", "NSK"] * 100).inferred_type == "categorical"


def test_unique_short_values_are_identifiers() -> None:
    assert profile([f"user-{i}" for i in range(500)]).inferred_type == "identifier"


def test_long_unique_strings_are_text_not_identifiers() -> None:
    values = [f"Комментарий оператора номер {i}, клиент просил перезвонить позже" for i in range(500)]
    assert profile(values).inferred_type == "text"


def test_booleans_detected() -> None:
    assert profile(["true", "false"] * 100).inferred_type == "boolean"
    assert profile(["0", "1"] * 100).inferred_type == "boolean"


def test_dates_detected() -> None:
    values = [f"2024-{month:02d}-15" for month in range(1, 13)] * 10
    result = profile(values)
    assert result.inferred_type == "datetime"
    assert result.datetime_range is not None


def test_missing_rate_counts_none() -> None:
    result = profile(["1", None, "3", None] * 25)
    assert result.missing == 50
    assert result.missing_rate == pytest.approx(0.5)


def test_mixed_types_flagged() -> None:
    result = profile((["100"] * 60) + (["не указано"] * 40))
    assert result.mixed_types is True


def test_unique_count_survives_category_cap() -> None:
    """Counter обрезан лимитом категорий — уникальные считаются отдельно."""
    result = profile([f"id-{i}" for i in range(3000)], max_categories=50)
    assert result.unique == 3000
    assert result.inferred_type == "identifier"


def test_csv_delimiter_sniffing() -> None:
    payload = "a;b;c\n1;2;3\n4;5;6\n".encode()
    table = load_table(payload, name="t", filename="t.csv", max_rows=100, max_columns=10)
    assert table.delimiter == ";"
    assert table.columns == ["a", "b", "c"]
    assert table.row_count == 2


def test_csv_missing_tokens_become_none() -> None:
    payload = "a,b\n1,NA\n2,\n3,null\n".encode()
    table = load_table(payload, name="t", filename="t.csv", max_rows=100, max_columns=10)
    assert table.column("b") == [None, None, None]


def test_json_array_of_objects() -> None:
    payload = b'[{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]'
    table = load_table(payload, name="t", filename="t.json", max_rows=100, max_columns=10)
    assert table.source_format == "json"
    assert table.columns == ["a", "b"]


def test_ndjson() -> None:
    payload = b'{"a": 1}\n{"a": 2}\n{"a": 3}\n'
    table = load_table(payload, name="t", filename="t.jsonl", max_rows=100, max_columns=10)
    assert table.row_count == 3


def test_row_limit_marks_truncated() -> None:
    payload = ("a\n" + "\n".join(str(i) for i in range(500))).encode()
    table = load_table(payload, name="t", filename="t.csv", max_rows=100, max_columns=10)
    assert table.row_count == 100
    assert table.truncated is True


def test_duplicate_headers_are_disambiguated() -> None:
    payload = b"a,a,b\n1,2,3\n"
    table = load_table(payload, name="t", filename="t.csv", max_rows=10, max_columns=10)
    assert table.columns == ["a", "a__1", "b"]


def test_empty_file_rejected() -> None:
    with pytest.raises(UnprocessableDataError):
        load_table(b"   ", name="t", filename="t.csv", max_rows=10, max_columns=10)


def test_profile_table_covers_all_columns() -> None:
    payload = b"id,region\n1,MSK\n2,SPB\n3,MSK\n"
    table = load_table(payload, name="t", filename="t.csv", max_rows=10, max_columns=10)
    result = profile_table(table, max_categories=100, id_uniqueness_ratio=0.95)
    assert set(result.column_names) == {"id", "region"}
    assert result.row_count == 3
