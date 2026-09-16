"""Чтение табличных данных в колоночную структуру.

Поддерживаем CSV/TSV, JSON (массив объектов или {"data": [...]}) и NDJSON.
Значения храним строками: приведение типов — уже задача профилировщика,
и ему важно видеть исходный текст (например, что 007 пришёл с нулями).
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field

from ...errors import UnprocessableDataError

#: Что считаем пропуском, независимо от того, кто выгружал данные.
MISSING_TOKENS = frozenset(
    {
        "",
        "-",
        "na",
        "n/a",
        "#n/a",
        "nan",
        "none",
        "null",
        "nil",
        "\\n",
        "undefined",
    }
)

CANDIDATE_DELIMITERS = (",", ";", "\t", "|")
ENCODINGS = ("utf-8-sig", "utf-8", "cp1251", "latin-1")

# csv по умолчанию отказывается читать очень длинные поля; на реальных
# выгрузках (склеенные JSON-строки в ячейке) это встречается регулярно.
csv.field_size_limit(10 * 1024 * 1024)


@dataclass
class Table:
    """Колоночное представление выгрузки."""

    name: str
    columns: list[str]
    data: dict[str, list[str | None]]
    row_count: int
    source_format: str
    encoding: str = "utf-8"
    delimiter: str | None = None
    truncated: bool = False
    dropped_columns: list[str] = field(default_factory=list)

    def column(self, name: str) -> list[str | None]:
        return self.data[name]


def normalize_cell(value: object) -> str | None:
    """Приводит ячейку к строке или None, если это пропуск."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value) if isinstance(value, float) else str(value)
    if isinstance(value, (dict, list)):
        # Вложенные структуры — отдельная история; сериализуем, чтобы хотя бы
        # увидеть смену формы в отчёте по схеме.
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    text = str(value).strip()
    if text.lower() in MISSING_TOKENS:
        return None
    return text


def _decode(payload: bytes) -> tuple[str, str]:
    for encoding in ENCODINGS:
        try:
            return payload.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise UnprocessableDataError(
        "Не удалось определить кодировку файла",
        {"tried": list(ENCODINGS)},
    )


def _sniff_delimiter(sample: str) -> str:
    """csv.Sniffer часто ошибается на данных с запятыми в тексте.

    Считаем сами: побеждает разделитель с максимальным и самым стабильным
    числом колонок по первым строкам.
    """
    lines = [line for line in sample.splitlines()[:20] if line.strip()]
    if not lines:
        return ","

    best, best_score = ",", (0, 0)
    for delimiter in CANDIDATE_DELIMITERS:
        try:
            rows = list(csv.reader(lines, delimiter=delimiter))
        except csv.Error:
            continue
        widths = [len(row) for row in rows if row]
        if not widths:
            continue
        width = widths[0]
        if width < 2:
            continue
        consistent = sum(1 for w in widths if w == width)
        score = (consistent, width)
        if score > best_score:
            best, best_score = delimiter, score
    return best


def _dedupe_headers(raw_headers: list[str]) -> list[str]:
    """Пустые и повторяющиеся заголовки — норма для ручных выгрузок."""
    seen: dict[str, int] = {}
    headers: list[str] = []
    for index, raw in enumerate(raw_headers):
        name = (raw or "").strip() or f"column_{index + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name}__{seen[name]}"
        else:
            seen[name] = 0
        headers.append(name)
    return headers


def _from_rows(
    name: str,
    headers: list[str],
    rows: list[list[str | None]],
    *,
    max_rows: int,
    max_columns: int,
    source_format: str,
    encoding: str,
    delimiter: str | None,
) -> Table:
    dropped = headers[max_columns:]
    kept = headers[:max_columns]
    truncated = len(rows) > max_rows
    rows = rows[:max_rows]

    data: dict[str, list[str | None]] = {column: [] for column in kept}
    for row in rows:
        for position, column in enumerate(kept):
            data[column].append(row[position] if position < len(row) else None)

    return Table(
        name=name,
        columns=kept,
        data=data,
        row_count=len(rows),
        source_format=source_format,
        encoding=encoding,
        delimiter=delimiter,
        truncated=truncated,
        dropped_columns=dropped,
    )


def _load_csv(
    name: str, text: str, encoding: str, *, max_rows: int, max_columns: int
) -> Table:
    delimiter = _sniff_delimiter(text[:65536])
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    try:
        raw_headers = next(reader)
    except StopIteration:
        raise UnprocessableDataError("Файл пустой") from None

    headers = _dedupe_headers(raw_headers)
    rows: list[list[str | None]] = []
    # Читаем на одну строку больше лимита, чтобы честно выставить truncated.
    for row in reader:
        rows.append([normalize_cell(cell) for cell in row])
        if len(rows) > max_rows:
            break

    return _from_rows(
        name,
        headers,
        rows,
        max_rows=max_rows,
        max_columns=max_columns,
        source_format="csv",
        encoding=encoding,
        delimiter=delimiter,
    )


def _extract_records(parsed: object) -> list[dict]:
    if isinstance(parsed, list):
        records = parsed
    elif isinstance(parsed, dict):
        for key in ("data", "items", "records", "rows", "results"):
            value = parsed.get(key)
            if isinstance(value, list):
                records = value
                break
        else:
            records = [parsed]
    else:
        raise UnprocessableDataError("JSON должен быть массивом объектов или объектом с массивом")

    if not records:
        raise UnprocessableDataError("В JSON нет записей")
    if not all(isinstance(item, dict) for item in records):
        raise UnprocessableDataError("Ожидался массив объектов — найдены скалярные элементы")
    return records


def _load_json(
    name: str, text: str, encoding: str, *, max_rows: int, max_columns: int
) -> Table:
    stripped = text.lstrip()
    if stripped.startswith(("[", "{")):
        try:
            records = _extract_records(json.loads(text))
            source_format = "json"
        except json.JSONDecodeError:
            records = _load_ndjson_records(text)
            source_format = "ndjson"
    else:
        records = _load_ndjson_records(text)
        source_format = "ndjson"

    # Порядок колонок — порядок первого появления ключа.
    headers: list[str] = []
    seen: set[str] = set()
    for record in records[: max_rows + 1]:
        for key in record:
            if key not in seen:
                seen.add(key)
                headers.append(str(key))

    rows = [
        [normalize_cell(record.get(header)) for header in headers]
        for record in records[: max_rows + 1]
    ]

    return _from_rows(
        name,
        _dedupe_headers(headers),
        rows,
        max_rows=max_rows,
        max_columns=max_columns,
        source_format=source_format,
        encoding=encoding,
        delimiter=None,
    )


def _load_ndjson_records(text: str) -> list[dict]:
    records: list[dict] = []
    for number, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as exc:
            raise UnprocessableDataError(
                "Не похоже ни на JSON, ни на NDJSON",
                {"line": number, "reason": exc.msg},
            ) from exc
        if not isinstance(parsed, dict):
            raise UnprocessableDataError("В NDJSON каждая строка должна быть объектом", {"line": number})
        records.append(parsed)
    if not records:
        raise UnprocessableDataError("В файле нет записей")
    return records


def load_table(
    payload: bytes,
    *,
    name: str,
    filename: str | None = None,
    max_rows: int,
    max_columns: int,
) -> Table:
    """Разбирает загруженный файл. Формат определяем по расширению и содержимому."""
    if not payload.strip():
        raise UnprocessableDataError(f"Файл {name} пустой")

    text, encoding = _decode(payload)
    suffix = (filename or "").lower().rsplit(".", 1)[-1] if filename and "." in filename else ""

    if suffix in {"json", "ndjson", "jsonl"} or text.lstrip().startswith(("[", "{")):
        return _load_json(name, text, encoding, max_rows=max_rows, max_columns=max_columns)
    return _load_csv(name, text, encoding, max_rows=max_rows, max_columns=max_columns)
