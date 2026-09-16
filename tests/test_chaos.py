"""Chaos API: ломается ровно так, как обещал, и не ломает сервер."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import create_app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


def test_scenarios_listed(client: TestClient) -> None:
    body = client.get("/api/chaos/scenarios").json()
    assert {scenario["id"] for scenario in body["scenarios"]} >= {
        "respond",
        "malformed",
        "pagination",
        "huge",
    }
    assert body["limits"]["max_delay_ms"] == settings.chaos_max_delay_ms


@pytest.mark.parametrize("code", [200, 201, 400, 404, 418, 500, 503])
def test_arbitrary_status(client: TestClient, code: int) -> None:
    assert client.get(f"/api/chaos/status/{code}").status_code == code


def test_no_content_statuses_have_empty_body(client: TestClient) -> None:
    response = client.get("/api/chaos/status/204")
    assert response.status_code == 204
    assert response.content == b""


def test_delay_is_capped(client: TestClient) -> None:
    """Просим час — получаем потолок, а не повисший воркер."""
    body = client.get("/api/chaos/delay/3600000").json()
    assert body["capped"] is True
    assert body["slept_ms"] == settings.chaos_max_delay_ms


def test_malformed_json_is_actually_malformed(client: TestClient) -> None:
    response = client.get("/api/chaos/malformed/truncated")
    assert response.headers["content-type"].startswith("application/json")
    with pytest.raises(json.JSONDecodeError):
        json.loads(response.text)


def test_malformed_unknown_kind_is_rejected(client: TestClient) -> None:
    response = client.get("/api/chaos/malformed/не-существует")
    assert response.status_code == 400
    assert "available" in response.json()["error"]["detail"]


def test_bom_variant_parses_only_after_stripping(client: TestClient) -> None:
    text = client.get("/api/chaos/malformed/bom").text
    assert text.startswith("﻿")
    assert json.loads(text.lstrip("﻿"))["ok"] is True


def test_huge_respects_cap(client: TestClient) -> None:
    response = client.get("/api/chaos/huge?size_kb=999999&stream=false")
    assert response.headers["x-chaos-capped"] == "true"
    assert len(response.content) <= settings.chaos_max_size_kb * 1024 + 1024


def test_pagination_duplicates_overlap(client: TestClient) -> None:
    first = client.get("/api/chaos/pagination?page=1&per_page=10&bug=duplicates").json()
    second = client.get("/api/chaos/pagination?page=2&per_page=10&bug=duplicates").json()
    ids_first = {item["id"] for item in first["items"]}
    ids_second = {item["id"] for item in second["items"]}
    assert ids_first & ids_second, "страницы должны перекрываться — в этом и баг"


def test_pagination_infinite_never_ends(client: TestClient) -> None:
    body = client.get("/api/chaos/pagination?page=999&bug=infinite").json()
    assert body["has_next"] is True


def test_pagination_wrong_total_lies(client: TestClient) -> None:
    body = client.get("/api/chaos/pagination?page=1&total=95&bug=wrong_total").json()
    assert body["total"] != body["_chaos"]["real_total"]


def test_flaky_is_deterministic_with_seed(client: TestClient) -> None:
    first = client.get("/api/chaos/flaky?fail_rate=0.99&seed=1").status_code
    second = client.get("/api/chaos/flaky?fail_rate=0.99&seed=1").status_code
    assert first == second


def test_flaky_never_fails_at_zero_rate(client: TestClient) -> None:
    for _ in range(5):
        assert client.get("/api/chaos/flaky?fail_rate=0").status_code == 200


def test_redirect_chain_shortens(client: TestClient) -> None:
    response = client.get("/api/chaos/redirect?times=3", follow_redirects=False)
    assert response.status_code == 302
    assert "times=2" in response.headers["location"]


def test_hostile_headers_present(client: TestClient) -> None:
    response = client.get("/api/chaos/headers")
    assert response.headers["retry-after"] == "soon-ish"  # обязано быть числом секунд


def test_respond_combines_options(client: TestClient) -> None:
    response = client.get("/api/chaos/respond?status=503&body=malformed_json&delay_ms=1")
    assert response.status_code == 503
    with pytest.raises(json.JSONDecodeError):
        json.loads(response.text)


def test_echo_truncates_on_purpose(client: TestClient) -> None:
    response = client.post("/api/chaos/echo", json={"hello": "world"})
    with pytest.raises(json.JSONDecodeError):
        json.loads(response.text)
    assert response.headers["x-chaos-echo"] == "truncated-on-purpose"


def test_echo_without_corruption_is_valid(client: TestClient) -> None:
    response = client.post("/api/chaos/echo?corrupt=false", json={"hello": "world"})
    assert response.json() == {"received": {"hello": "world"}}
