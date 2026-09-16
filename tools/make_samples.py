"""Генератор демо-данных для /api/drift/demo.

Дрейф здесь подложен намеренно, чтобы отчёт показывал все виды находок:
смена типа, новая колонка, всплеск пропусков, сдвиг распределения, новые
категории, схлопывание в константу и пересечение идентификаторов.

Запуск:  python tools/make_samples.py
"""

from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "samples"

REGIONS_REF = ["MSK", "SPB", "NSK", "EKB", "KZN", "ROV"]
REGIONS_CUR = ["MSK", "SPB", "NSK", "EKB", "KZN", "UNKNOWN", "OTHER_17"]
CHANNELS = ["web", "mobile", "partner", "offline"]
DEPARTMENTS_REF = ["sales", "support", "risk", "ops"]
DEPARTMENTS_CUR = ["sales", "support", "risk", "ops", "ml", "growth", "legal"]
COMMENTS = [
    "заявка принята",
    "повторное обращение",
    "перевод в другой отдел",
    "клиент не отвечает",
    "документы на проверке",
    "",
]

COLUMNS_REF = [
    "client_id",
    "age",
    "region",
    "income",
    "transaction_amount",
    "channel",
    "department",
    "signup_date",
    "is_active",
    "score",
    "legacy_flag",
    "comment",
]
COLUMNS_CUR = COLUMNS_REF + ["client_type"]


def _row(rng: random.Random, index: int, *, current: bool) -> dict[str, object]:
    start = date(2024, 1, 1)

    if current:
        # Часть идентификаторов намеренно пересекается с reference —
        # инструмент должен это заметить.
        client_id = rng.randint(1, 3200) if index % 7 == 0 else 100_000 + index
        age = round(rng.gauss(41, 13), 1)  # int -> float
        region = rng.choices(REGIONS_CUR, weights=[26, 18, 12, 10, 9, 15, 10])[0]
        income = None if rng.random() < 0.147 else round(rng.lognormvariate(11.1, 0.55), 2)
        amount = round(rng.lognormvariate(8.9, 0.85), 2)  # сдвиг вправо
        department = rng.choice(DEPARTMENTS_CUR)
        score = round(rng.gauss(0.54, 0.19), 4)
        legacy_flag = "0"  # схлопнулась в константу
        signup = start + timedelta(days=rng.randint(200, 900))
        extra = {"client_type": rng.choice(["retail", "sme", "corporate"])}
    else:
        client_id = index + 1
        age = int(max(18, min(95, rng.gauss(38, 12))))
        region = rng.choices(REGIONS_REF, weights=[30, 22, 14, 12, 12, 10])[0]
        income = None if rng.random() < 0.021 else round(rng.lognormvariate(11.0, 0.5), 2)
        amount = round(rng.lognormvariate(8.4, 0.8), 2)
        department = rng.choice(DEPARTMENTS_REF)
        score = round(rng.gauss(0.51, 0.18), 4)
        legacy_flag = rng.choice(["0", "1"])
        signup = start + timedelta(days=rng.randint(0, 700))
        extra = {}

    row: dict[str, object] = {
        "client_id": client_id,
        "age": age,
        "region": region,
        "income": "" if income is None else income,
        "transaction_amount": amount,
        "channel": rng.choices(CHANNELS, weights=[40, 35, 15, 10])[0],
        "department": department,
        "signup_date": signup.isoformat(),
        "is_active": rng.choice(["true", "false"]),
        "score": score,
        "legacy_flag": legacy_flag,
        "comment": rng.choice(COMMENTS),
    }
    row.update(extra)
    return row


def write(path: Path, columns: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    print(f"{path.name}: {len(rows)} строк, {len(columns)} колонок, {path.stat().st_size / 1024:.0f} КБ")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    rng = random.Random(42)
    reference = [_row(rng, i, current=False) for i in range(3200)]

    rng = random.Random(4242)
    current = [_row(rng, i, current=True) for i in range(3680)]

    write(OUT_DIR / "reference.csv", COLUMNS_REF, reference)
    write(OUT_DIR / "current.csv", COLUMNS_CUR, current)


if __name__ == "__main__":
    main()
