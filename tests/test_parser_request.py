"""Web Parser 1c: Explore / Request Builder. URL/curl → RequestSpec → выполнить."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
import app.tools.parser.router as pr


class FakeResp:
    def __init__(self, *, status=200, ctype="application/json", text='{"items":[{"id":1},{"id":2}]}',
                 headers=None, cookies=None, method="GET"):
        self.url = "https://api.ex/u"
        self.final_url = "https://api.ex/u"
        self.status = status
        self.method = method
        self.content_type = ctype
        self.charset = "utf-8"
        self.text = text
        self.body = text.encode()
        self.elapsed_ms = 4.2
        self.resolved_ip = "93.184.216.34"
        self.truncated = False
        self.headers = headers or {"content-type": ctype, "set-cookie": "sid=abc"}
        self.cookies = cookies or ["sid=abc"]
        self.redirect_chain = []


@pytest.fixture()
def client(monkeypatch):
    captured = {}

    class FakeClient:
        def request(self, method, url, **kw):
            captured["method"] = method
            captured["headers"] = kw.get("headers", {})
            captured["respect_robots"] = kw.get("respect_robots")
            captured["body"] = kw.get("body")
            return FakeResp(method=method)

    monkeypatch.setattr(pr, "HttpClient", lambda *a, **k: FakeClient())
    c = TestClient(create_app())
    c._captured = captured
    return c


def test_build_request_from_curl(client):
    r = client.post("/api/parser/build-request", json={
        "input": 'curl -X POST "https://api.example.com/u?limit=5" -H "Authorization: Bearer S" -d "{}"'
    }).json()
    assert r["request"]["method"] == "POST"
    assert r["request"]["url"].startswith("https://api.example.com/u")
    assert "Authorization" in r["request"]["headers"]


def test_build_request_from_url(client):
    r = client.post("/api/parser/build-request", json={"input": "https://api.example.com/data"}).json()
    assert r["request"]["method"] == "GET"
    assert r["request"]["url"] == "https://api.example.com/data"


def test_build_request_rejects_plain_text(client):
    r = client.post("/api/parser/build-request", json={"input": "просто текст"}).json()
    assert "error" in r


def test_request_executes_without_robots_but_with_ssrf(client):
    client.post("/api/parser/request", json={"method": "GET", "url": "https://api.ex/u", "headers": {"Accept": "application/json"}})
    assert client._captured["respect_robots"] is False  # явный запрос, robots не применяем
    assert client._captured["method"] == "GET"


def test_request_masks_secrets_in_echo(client):
    r = client.post("/api/parser/request", json={
        "method": "GET", "url": "https://api.ex/u", "headers": {"Authorization": "Bearer SUPERSECRET"},
    }).json()
    assert r["request"]["headers"]["Authorization"] == "***"
    assert "SUPERSECRET" not in json.dumps(r)
    # но реально в сеть секрет ушёл (это одиночный авторизованный запрос)
    assert client._captured["headers"]["Authorization"] == "Bearer SUPERSECRET"


def test_response_masks_set_cookie(client):
    r = client.post("/api/parser/request", json={"method": "GET", "url": "https://api.ex/u"}).json()
    assert r["response"]["headers"]["set-cookie"] == "***"
    assert r["response"]["cookie_count"] == 1


def test_request_parses_json_structure(client):
    r = client.post("/api/parser/request", json={"method": "GET", "url": "https://api.ex/u"}).json()
    assert r["response"]["source_type"] == "json"
    assert len(r["json"]["items"]) == 2


def test_request_body_and_cookies_folded(client):
    client.post("/api/parser/request", json={
        "method": "POST", "url": "https://api.ex/u", "body": '{"a":1}',
        "cookies": {"sid": "x"}, "content_type": "application/json",
    })
    assert client._captured["body"] == b'{"a":1}'
    assert client._captured["headers"]["Cookie"] == "sid=x"
    assert client._captured["headers"]["Content-Type"] == "application/json"


def test_request_ssrf_error_path(client, monkeypatch):
    from app.net.errors import UnsafeUrlError

    class Bad:
        def request(self, *a, **k):
            raise UnsafeUrlError("Адрес отклонён", {"host": "x"})

    monkeypatch.setattr(pr, "HttpClient", lambda *a, **k: Bad())
    r = client.post("/api/parser/request", json={"method": "GET", "url": "http://10.0.0.1/"}).json()
    assert "error" in r
    assert "request" in r  # эхо запроса (маскированное) есть даже при ошибке
