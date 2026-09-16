"""Генерация значений и сериализация выгрузки.

Порча накладывается поверх «чистого» значения, а не вместо него: так один и
тот же набор колонок можно выдать и идеально ровным, и изуродованным.
"""

from __future__ import annotations

import csv
import io
import json
import math
import random
from datetime import date, datetime, timedelta

from .spec import ColumnSpec, DatasetSpec

FIRST_NAMES = ["Анна", "Борис", "Вера", "Глеб", "Дарья", "Егор", "Жанна", "Игорь", "Ксения", "Лев"]
LAST_NAMES = ["Иванов", "Петров", "Сидорова", "Кузнецов", "Смирнова", "Попов", "Новикова"]
WORDS = [
    "заявка",
    "обращение",
    "перевод",
    "проверка",
    "документы",
    "клиент",
    "отдел",
    "срочно",
    "повторно",
    "отказ",
]
DOMAINS = ["example.com", "mail.ru", "corp.local", "test.org"]

#: Кириллические буквы, неотличимые от латинских. Главный источник «почему
#: JOIN не сходится» в реальных данных.
HOMOGLYPHS = {"a": "а", "e": "е", "o": "о", "p": "р", "c": "с", "x": "х", "y": "у", "B": "В"}
ZERO_WIDTH = "​"
NBSP = " "

BROKEN_DATES = [
    "2024-02-31",  # такого дня не существует
    "31/02/2024",
    "2024-13-01",
    "01.01.24",
    "1704067200",  # unix timestamp вместо даты
    "2024-01-01T00:00:00.000000+03:00",
    "вчера",
    "0000-00-00",  # привет от MySQL
]
BROKEN_NUMBERS = ["1 234,56", "1,234.56", "٣٤٥", "1e3", "12%", "—", "N/A", "(500)"]
#: Пропуски, записанные словами. Проверка `WHERE x IS NULL` их не увидит,
#: зато тип колонки тихо станет текстовым.
DISGUISED_MISSING = ["NULL", "N/A", "-", "нет данных", "None", "не указано", "—"]


def _clip(value: float, column: ColumnSpec) -> float:
    if column.minimum is not None:
        value = max(value, column.minimum)
    if column.maximum is not None:
        value = min(value, column.maximum)
    return value


def _draw_number(rng: random.Random, column: ColumnSpec) -> float:
    if column.distribution == "uniform":
        low = column.minimum if column.minimum is not None else column.mean - column.std * 2
        high = column.maximum if column.maximum is not None else column.mean + column.std * 2
        value = rng.uniform(low, high)
    elif column.distribution == "lognormal":
        # mean/std трактуем как параметры итогового масштаба, а не логарифма.
        sigma = 0.5 if column.mean <= 0 else min(1.5, max(0.1, column.std / max(column.mean, 1)))
        mu = math.log(max(column.mean, 1e-6)) - sigma**2 / 2
        value = rng.lognormvariate(mu, sigma)
    elif column.distribution == "exponential":
        value = rng.expovariate(1 / max(column.mean, 1e-6))
    else:
        value = rng.gauss(column.mean, column.std)
    return _clip(value, column)


def _weights_for(column: ColumnSpec, categories: list[str]) -> list[float]:
    if column.weights:
        return list(column.weights)
    if column.imbalance <= 0:
        return [1.0] * len(categories)
    # imbalance=1 — почти всё в первой категории, 0 — ровные доли.
    head = 1.0 + column.imbalance * 50
    tail = max(0.02, 1.0 - column.imbalance)
    return [head] + [tail] * (len(categories) - 1)


def _clean_value(rng: random.Random, column: ColumnSpec, index: int) -> object:
    kind = column.type

    if kind == "identifier":
        return f"{column.name[:3].upper()}-{100000 + index}"
    if kind == "integer":
        return int(round(_draw_number(rng, column)))
    if kind in {"float", "money"}:
        value = round(_draw_number(rng, column), column.decimals)
        return f"{value:.2f}" if kind == "money" else value
    if kind == "boolean":
        return rng.choice(["true", "false"])
    if kind == "categorical":
        categories = column.categories or ["alpha", "beta", "gamma", "delta"]
        return rng.choices(categories, weights=_weights_for(column, categories))[0]
    if kind == "datetime":
        start = date.fromisoformat(column.start)
        end = date.fromisoformat(column.end)
        span = max((end - start).days, 1)
        return (start + timedelta(days=rng.randint(0, span))).isoformat()
    if kind == "email":
        return f"{rng.choice(FIRST_NAMES).lower()}.{index}@{rng.choice(DOMAINS)}"
    if kind == "phone":
        return f"+7{rng.randint(9000000000, 9999999999)}"
    # text
    return " ".join(rng.choice(WORDS) for _ in range(rng.randint(2, 7)))


def _apply_defects(rng: random.Random, column: ColumnSpec, value: object) -> object:
    defects = column.defects

    if defects.null_rate and rng.random() < defects.null_rate:
        # Замаскированный пропуск — это отдельный дефект: пустая ячейка ломает
        # пайплайн честно, а «нет данных» молча превращает колонку в текст.
        if rng.random() < defects.disguised_null_rate:
            return rng.choice(DISGUISED_MISSING)
        return ""

    if defects.outlier_rate and rng.random() < defects.outlier_rate:
        if isinstance(value, (int, float)):
            factor = rng.choice([50, 100, -80, 1000])
            return type(value)(value * factor) if value else factor * 1000

    if defects.broken_format_rate and rng.random() < defects.broken_format_rate:
        if column.type == "datetime":
            return rng.choice(BROKEN_DATES)
        if column.type in {"integer", "float", "money"}:
            return rng.choice(BROKEN_NUMBERS)
        if column.type == "email":
            return rng.choice(["не почта", "user@@example.com", "user@", "@example.com"])
        if column.type == "phone":
            return rng.choice(["8(495)123-45-67", "+7 999 123 45 67", "телефона нет"])

    if defects.mixed_type_rate and rng.random() < defects.mixed_type_rate:
        return rng.choice(["не определено", "TBD", "см. комментарий", "0,00"])

    text = str(value)

    if defects.case_noise_rate and rng.random() < defects.case_noise_rate:
        text = rng.choice([text.upper(), text.lower(), text.title()])

    if defects.unicode_trap_rate and rng.random() < defects.unicode_trap_rate:
        trap = rng.random()
        if trap < 0.4:
            # Подменяем латиницу похожей кириллицей: глазами не видно, JOIN не сходится.
            text = "".join(HOMOGLYPHS.get(ch, ch) for ch in text)
        elif trap < 0.7:
            position = rng.randint(0, len(text)) if text else 0
            text = text[:position] + ZERO_WIDTH + text[position:]
        else:
            text = text.replace(" ", NBSP)

    if defects.whitespace_rate and rng.random() < defects.whitespace_rate:
        text = rng.choice([f" {text}", f"{text} ", f"  {text}  ", f"{NBSP}{text}"])

    return text


def generate_rows(spec: DatasetSpec, rng: random.Random) -> tuple[list[str], list[list[object]]]:
    columns = [column.name for column in spec.columns]
    rows: list[list[object]] = []

    for index in range(spec.rows):
        row = [
            _apply_defects(rng, column, _clean_value(rng, column, index))
            for column in spec.columns
        ]
        rows.append(row)

    defects = spec.defects

    if defects.duplicate_row_rate:
        count = int(spec.rows * defects.duplicate_row_rate)
        for _ in range(count):
            rows.append(list(rng.choice(rows)))
        rng.shuffle(rows)

    if defects.empty_row_rate:
        count = int(len(rows) * defects.empty_row_rate)
        for _ in range(count):
            rows.insert(rng.randint(0, len(rows)), ["" for _ in columns])

    if defects.shuffled_columns:
        order = list(range(len(columns)))
        rng.shuffle(order)
        columns = [columns[i] for i in order]
        rows = [[row[i] for i in order] for row in rows]

    if defects.ragged_rows:
        # Каждой десятой строке отрезаем хвост — csv.reader вернёт короткий ряд.
        for position in range(0, len(rows), 10):
            rows[position] = rows[position][: max(1, len(columns) - 1)]

    return columns, rows


def serialize(columns: list[str], rows: list[list[object]], spec: DatasetSpec) -> str:
    newline = "\r\n" if spec.defects.crlf else "\n"

    if spec.format in {"csv", "tsv"}:
        buffer = io.StringIO()
        writer = csv.writer(
            buffer,
            delimiter="\t" if spec.format == "tsv" else ",",
            lineterminator=newline,
        )
        writer.writerow(columns)
        writer.writerows(rows)
        body = buffer.getvalue()
    elif spec.format == "ndjson":
        body = newline.join(
            json.dumps(dict(zip(columns, row)), ensure_ascii=False) for row in rows
        )
        body += newline
    else:
        records = [dict(zip(columns, row)) for row in rows]
        body = json.dumps(records, ensure_ascii=False, indent=2)

    return ("﻿" + body) if spec.defects.bom else body


def generate(spec: DatasetSpec) -> tuple[str, dict[str, object]]:
    """Возвращает текст файла и краткую сводку о том, что в нём подложено."""
    rng = random.Random(spec.seed)
    columns, rows = generate_rows(spec, rng)
    body = serialize(columns, rows, spec)

    planted = {
        column.name: {
            key: value
            for key, value in column.defects.model_dump().items()
            if isinstance(value, (int, float)) and value > 0
        }
        for column in spec.columns
    }
    summary = {
        "name": spec.name,
        "format": spec.format,
        "rows": len(rows),
        "columns": columns,
        "bytes": len(body.encode("utf-8")),
        "seed": spec.seed,
        "column_defects": {name: defects for name, defects in planted.items() if defects},
        "dataset_defects": {
            key: value for key, value in spec.defects.model_dump().items() if value
        },
    }
    return body, summary


MEDIA_TYPES = {
    "csv": "text/csv; charset=utf-8",
    "tsv": "text/tab-separated-values; charset=utf-8",
    "json": "application/json; charset=utf-8",
    "ndjson": "application/x-ndjson; charset=utf-8",
}


def filename_for(spec: DatasetSpec) -> str:
    extension = "jsonl" if spec.format == "ndjson" else spec.format
    stamp = datetime.now().strftime("%Y%m%d")
    return f"{spec.name}-{stamp}.{extension}"
