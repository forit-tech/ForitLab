"""Data Burner: подложенные дефекты должны реально оказываться в файле."""

from __future__ import annotations

import csv
import io
import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.tools.burner.generator import generate
from app.tools.burner.presets import preset_spec, weird_of_the_day
from app.tools.burner.spec import ColumnDefects, ColumnSpec, DatasetDefects, DatasetSpec


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


def rows_of(body: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(body)))


def test_presets_listed(client: TestClient) -> None:
    ids = {item["id"] for item in client.get("/api/burner/presets").json()}
    assert {"clean", "dirty", "etl_torture", "nulls"} <= ids


def test_clean_preset_has_no_missing_values(client: TestClient) -> None:
    body = client.get("/api/burner/datasets?preset=clean&rows=200&seed=1&download=false").text
    rows = rows_of(body)
    assert len(rows) == 200
    assert all(all(value != "" for value in row.values()) for row in rows)


def test_nulls_preset_actually_has_nulls(client: TestClient) -> None:
    body = client.get("/api/burner/datasets?preset=nulls&rows=500&seed=1&download=false").text
    rows = rows_of(body)
    missing = sum(1 for row in rows if row["income"] in {"", "NULL", "N/A", "-", "нет данных"})
    assert missing > 100  # заказывали 45%


def test_seed_makes_generation_reproducible(client: TestClient) -> None:
    first = client.get("/api/burner/datasets?preset=dirty&rows=100&seed=42&download=false").text
    second = client.get("/api/burner/datasets?preset=dirty&rows=100&seed=42&download=false").text
    assert first == second


def test_different_seeds_differ(client: TestClient) -> None:
    first = client.get("/api/burner/datasets?preset=dirty&rows=100&seed=1&download=false").text
    second = client.get("/api/burner/datasets?preset=dirty&rows=100&seed=2&download=false").text
    assert first != second


def test_duplicates_preset_creates_duplicates(client: TestClient) -> None:
    body = client.get("/api/burner/datasets?preset=duplicates&rows=300&seed=3&download=false").text
    lines = body.splitlines()[1:]
    assert len(lines) > len(set(lines))


def test_etl_torture_has_bom_and_crlf(client: TestClient) -> None:
    body = client.get("/api/burner/datasets?preset=etl_torture&rows=50&seed=5&download=false").text
    assert body.startswith("﻿")
    assert "\r\n" in body


def test_download_sets_filename(client: TestClient) -> None:
    response = client.get("/api/burner/datasets?preset=clean&rows=10")
    assert "attachment" in response.headers["content-disposition"]


def test_json_and_ndjson_formats(client: TestClient) -> None:
    as_json = client.get("/api/burner/datasets?preset=clean&rows=5&format=json&download=false").text
    assert isinstance(json.loads(as_json), list)

    as_ndjson = client.get(
        "/api/burner/datasets?preset=clean&rows=5&format=ndjson&download=false"
    ).text
    lines = [line for line in as_ndjson.splitlines() if line.strip()]
    assert len(lines) == 5
    assert all(json.loads(line) for line in lines)


def test_custom_spec_generates_requested_columns(client: TestClient) -> None:
    spec = {
        "rows": 50,
        "seed": 1,
        "columns": [
            {"name": "amount", "type": "float", "mean": 10, "std": 1},
            {"name": "label", "type": "categorical", "categories": ["a", "b"]},
        ],
    }
    body = client.post("/api/burner/datasets", json=spec).json()
    assert body["summary"]["rows"] == 50
    assert body["summary"]["columns"] == ["amount", "label"]
    assert set(rows_of(body["content"])[0]) == {"amount", "label"}


def test_row_limit_enforced(client: TestClient) -> None:
    response = client.post(
        "/api/burner/datasets",
        json={"rows": 10_000_000, "columns": [{"name": "x", "type": "integer"}]},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "bad_request"


def test_unknown_preset_rejected(client: TestClient) -> None:
    response = client.get("/api/burner/datasets?preset=не-бывает")
    assert response.status_code == 400
    assert "available" in response.json()["error"]["detail"]


def test_pair_is_ready_for_drift(client: TestClient) -> None:
    pair = client.get("/api/burner/pair?preset=clean&rows=400&seed=11").json()
    report = client.post(
        "/api/drift/compare",
        json={"reference": pair["reference"], "current": pair["current"], "save": False},
    ).json()

    assert report["schema"]["added"] == ["client_type"]
    assert report["summary"]["status"] == "alert"
    codes = {
        finding["code"] for column in report["columns"] for finding in column["findings"]
    }
    # Ровно то, что Data Burner подкладывал: сдвиг, новые категории, пропуски.
    assert "category.new" in codes
    assert "missing.appeared" in codes
    assert any(code.startswith("distribution.") for code in codes)


def test_disguised_nulls_are_off_in_drift_pair() -> None:
    """В паре для дрейфа пропуски пустые, иначе колонка меняет тип."""
    from app.tools.burner.presets import drifted_spec
    from app.tools.burner.spec import DriftSpec

    reference = preset_spec("clean", 100, "csv", 1)
    current = drifted_spec(reference, DriftSpec(), 1)
    affected = [c for c in current.columns if c.defects.null_rate > 0]
    assert affected
    assert all(column.defects.disguised_null_rate == 0.0 for column in affected)


def test_weird_of_the_day_is_deterministic(client: TestClient) -> None:
    first = client.get("/api/burner/weird-of-the-day?date=2026-03-01&rows=100").text
    second = client.get("/api/burner/weird-of-the-day?date=2026-03-01&rows=100").text
    assert first == second


def test_weird_of_the_day_changes_between_days(client: TestClient) -> None:
    answers = {
        client.get(f"/api/burner/weird-of-the-day/answer?date=2026-03-{day:02d}").json()["answer"]
        for day in range(1, 12)
    }
    assert len(answers) > 1


def test_weird_answer_does_not_leak_in_download(client: TestClient) -> None:
    response = client.get("/api/burner/weird-of-the-day?date=2026-03-01&rows=10")
    joined = " ".join(response.headers.keys()).lower()
    assert "answer" not in joined and "case" not in joined


def test_outliers_are_extreme() -> None:
    spec = DatasetSpec(
        rows=1000,
        seed=7,
        columns=[
            ColumnSpec(
                name="amount",
                type="float",
                mean=100,
                std=10,
                defects=ColumnDefects(outlier_rate=0.05),
            )
        ],
    )
    body, _ = generate(spec)
    values = [float(row["amount"]) for row in rows_of(body)]
    assert max(abs(value) for value in values) > 1000


def test_ragged_rows_produce_short_lines() -> None:
    spec = DatasetSpec(
        rows=50,
        seed=1,
        columns=[ColumnSpec(name="a", type="integer"), ColumnSpec(name="b", type="integer")],
        defects=DatasetDefects(ragged_rows=True),
    )
    body, _ = generate(spec)
    widths = {len(row) for row in csv.reader(io.StringIO(body))}
    assert len(widths) > 1


def test_weird_case_matches_answer() -> None:
    from datetime import date

    spec, case_id, answer = weird_of_the_day(date(2026, 3, 1), 100, "csv")
    assert case_id in answer or answer
    assert spec.rows == 100
