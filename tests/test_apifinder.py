"""API Finder: free-only правило, поиск, статусы, мост из Harvester.

Сеть не трогаем: availability-проверка живого эндпоинта — отдельная история,
а логика каталога и поиска должна быть детерминированной.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.tools.apifinder.catalog import FREE_TYPES, get_registry
from app.tools.apifinder.service import match_candidate, search, surprise


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


def test_catalog_loads() -> None:
    records = get_registry().all()
    assert len(records) >= 25


def test_free_only_rule_enforced() -> None:
    """Ни одной записи вне разрешённых видов бесплатности."""
    for record in get_registry().all():
        assert record.no_key or record.free_type in FREE_TYPES


def test_free_is_not_the_same_as_no_key() -> None:
    """В каталоге есть free-tier API, которые ТРЕБУЮТ ключ — и это нормально."""
    with_key = [r for r in get_registry().all() if r.auth == "key"]
    assert with_key, "должны быть free-tier API с обязательным ключом"
    assert all(r.free_type in FREE_TYPES for r in with_key)


def test_every_card_has_source_and_date() -> None:
    for record in get_registry().all():
        card = record.as_card()
        assert card["source"]
        assert card["last_verified_at"]


def test_catalog_records_are_docs_verified_or_stale() -> None:
    today = date.today()
    for record in get_registry().all():
        assert record.effective_status(today) in {"docs_verified", "stale", "availability_checked"}


def test_stale_detection() -> None:
    record = get_registry().all()[0]
    record.last_verified_at = "2000-01-01"
    assert record.effective_status(date(2026, 1, 1)) == "stale"


def test_search_by_topic_russian(client: TestClient) -> None:
    results = client.get("/api/apifinder/search", params={"q": "погода"}).json()["results"]
    assert any(r["id"] == "open-meteo" for r in results)


def test_search_relevance_orders_results(client: TestClient) -> None:
    results = client.get("/api/apifinder/search", params={"q": "crypto"}).json()["results"]
    assert results
    assert all(r["free_type"] in FREE_TYPES or r["no_key"] for r in results)


def test_filter_no_key(client: TestClient) -> None:
    results = client.get("/api/apifinder/search", params={"no_key": "true"}).json()["results"]
    assert results
    assert all(r["no_key"] is True for r in results)


def test_filter_free_type(client: TestClient) -> None:
    results = client.get(
        "/api/apifinder/search", params={"free_type": "open_data"}
    ).json()["results"]
    assert all(r["free_type"] == "open_data" for r in results)


def test_categories_endpoint(client: TestClient) -> None:
    categories = client.get("/api/apifinder/categories").json()
    assert "Weather" in categories
    assert sum(categories.values()) >= 25


def test_explore_lists_topics(client: TestClient) -> None:
    body = client.get("/api/apifinder/explore").json()
    ids = {topic["id"] for topic in body["topics"]}
    assert {"ds_idea", "no_key", "open_data"} <= ids


def test_explore_topic_returns_results(client: TestClient) -> None:
    body = client.get("/api/apifinder/explore/ds_idea").json()
    assert body["count"] > 0


def test_explore_unknown_topic_404(client: TestClient) -> None:
    assert client.get("/api/apifinder/explore/не-тема").status_code == 404


def test_surprise_is_deterministic() -> None:
    first = surprise(seed=1)
    second = surprise(seed=1)
    assert [a["id"] for a in first["apis"]] == [a["id"] for a in second["apis"]]
    assert first["idea"]


def test_surprise_endpoint(client: TestClient) -> None:
    body = client.get("/api/apifinder/surprise", params={"seed": 5}).json()
    assert 1 <= len(body["apis"]) <= 3
    assert "workflow" in body


def test_card_details(client: TestClient) -> None:
    card = client.get("/api/apifinder/apis/open-meteo").json()
    assert card["name"] == "Open-Meteo"
    assert card["no_key"] is True
    assert card["actions"]["example_request"]


def test_unknown_api_404(client: TestClient) -> None:
    assert client.get("/api/apifinder/apis/не-существует").status_code == 404


def test_not_specified_is_preserved() -> None:
    """Не выдумываем лимиты: 'Not specified' должно оставаться как есть."""
    values = {record.request_limit for record in get_registry().all()}
    assert "Not specified" in values


def test_bridge_matches_catalog_by_host() -> None:
    result = match_candidate("https://api.open-meteo.com/v1/forecast?x=1")
    assert result["match"] == "catalog"
    assert result["id"] == "open-meteo"


def test_bridge_unknown_stays_discovered() -> None:
    result = match_candidate("https://totally-unknown.example/api/data")
    assert result["match"] == "unknown"
    assert result["status"] == "discovered"
    assert result["last_verified_at"] is None  # условия не выдумываем


def test_favorites_export_json(client: TestClient) -> None:
    body = client.get(
        "/api/apifinder/favorites/export", params={"ids": "open-meteo,frankfurter,нет"}
    ).json()
    assert body["count"] == 2
    assert "нет" in body["missing"]


def test_favorites_export_csv(client: TestClient) -> None:
    response = client.get(
        "/api/apifinder/favorites/export", params={"ids": "open-meteo", "format": "csv"}
    )
    assert response.headers["content-type"].startswith("text/csv")
    assert "open-meteo" in response.text
