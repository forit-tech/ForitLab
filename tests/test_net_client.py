"""Поведение HttpClient: методы/тело, редиректы с ревалидацией, лимит размера.

Реальная сеть не нужна: подменяем резолвер (публичный IP) и соединение
(скриптованные ответы). Так тест детерминирован и не упирается в порт 80/443.
"""

from __future__ import annotations

import socket

import pytest

from app.net.client import HttpClient, _REDIRECT_CODES
from app.net.resolver import ResolvedAddr


class FakeResolver:
    def resolve(self, host: str, port: int | None = None) -> list[ResolvedAddr]:
        return [ResolvedAddr(socket.AF_INET, "93.184.216.34")]


class FakeResponse:
    def __init__(self, status: int, headers: list[tuple[str, str]], body: bytes) -> None:
        self.status = status
        self._headers = headers
        self._body = body

    def getheaders(self) -> list[tuple[str, str]]:
        return self._headers

    def getheader(self, name: str, default=None):
        for key, value in self._headers:
            if key.lower() == name.lower():
                return value
        return default

    def read(self, amt: int | None = None) -> bytes:
        if amt is None or amt < 0:
            return self._body
        return self._body[:amt]


class FakeConn:
    def __init__(self, script: dict) -> None:
        self._script = script
        self.request_calls: list[dict] = []

    def request(self, method, path, body=None, headers=None):
        self.request_calls.append({"method": method, "path": path, "body": body, "headers": headers})

    def getresponse(self) -> FakeResponse:
        return FakeResponse(self._script["status"], self._script.get("headers", []), self._script.get("body", b""))

    def close(self) -> None:  # pragma: no cover - заглушка
        pass


def scripted(monkeypatch, responses: list[dict]):
    """Подменяет _open так, чтобы каждый hop получал следующий скрипт из списка."""
    http = HttpClient(resolver=FakeResolver(), respect_robots=False)
    conns: list[FakeConn] = []

    def fake_open(scheme, host, port, ip):
        conn = FakeConn(responses[len(conns)])
        conns.append(conn)
        return conn

    monkeypatch.setattr(http, "_open", fake_open)
    return http, conns


def test_get_returns_body_and_metadata(monkeypatch):
    http, conns = scripted(monkeypatch, [
        {"status": 200, "headers": [("Content-Type", "application/json; charset=utf-8")], "body": b'{"ok":true}'},
    ])
    r = http.request("GET", "http://api.example/data")
    assert r.status == 200
    assert r.content_type == "application/json"
    assert r.text == '{"ok":true}'
    assert r.resolved_ip == "93.184.216.34"
    assert r.method == "GET"
    assert not r.truncated


def test_post_passes_method_and_body(monkeypatch):
    http, conns = scripted(monkeypatch, [{"status": 201, "headers": [], "body": b"created"}])
    r = http.request("POST", "http://api.example/items", body=b'{"name":"x"}', headers={"X-Test": "1"})
    assert r.status == 201
    call = conns[0].request_calls[0]
    assert call["method"] == "POST"
    assert call["body"] == b'{"name":"x"}'
    assert call["headers"]["X-Test"] == "1"
    assert "User-Agent" in call["headers"]


def test_redirect_is_followed_and_revalidated(monkeypatch):
    http, conns = scripted(monkeypatch, [
        {"status": 302, "headers": [("Location", "http://b.example/final")], "body": b""},
        {"status": 200, "headers": [("Content-Type", "text/plain")], "body": b"done"},
    ])
    r = http.request("GET", "http://a.example/start")
    assert r.status == 200
    assert r.text == "done"
    assert r.final_url == "http://b.example/final"
    assert len(r.redirect_chain) == 1
    assert r.redirect_chain[0].status == 302
    assert len(conns) == 2  # второй hop открыл новое соединение (ревалидация)


def test_size_limit_truncates(monkeypatch):
    big = b"x" * 5000
    http, conns = scripted(monkeypatch, [{"status": 200, "headers": [], "body": big}])
    r = http.request("GET", "http://a.example/big", max_bytes=1000)
    assert r.truncated is True
    assert len(r.body) == 1000


def test_head_reads_no_body(monkeypatch):
    http, conns = scripted(monkeypatch, [{"status": 200, "headers": [("Content-Length", "9999")], "body": b"IGNORED"}])
    r = http.request("HEAD", "http://a.example/x")
    assert r.status == 200
    assert r.body == b""


def test_redirect_codes_constant():
    assert 301 in _REDIRECT_CODES and 308 in _REDIRECT_CODES


def test_charset_from_meta_stops_at_delimiter():
    """Регрессия: страница без charset в заголовке не должна ломать decode.

    Раньше значение charset собиралось из всего буфера (фильтрацией), и на
    <meta charset="utf-8"> в имя кодировки попадал весь текст → LookupError.
    """
    from app.net.client import _charset_from

    body = b'<html><head><meta charset="utf-8"><title>Cats</title></head><body>hi</body></html>'
    assert _charset_from("text/html", body) == "utf-8"


def test_charset_from_invalid_falls_back_to_utf8():
    from app.net.client import _charset_from

    assert _charset_from("text/html; charset=definitely-not-a-codec", b"") == "utf-8"
    assert _charset_from("text/html", b'<meta charset="bogus-enc">') == "utf-8"


def test_response_decodes_when_header_has_no_charset(monkeypatch):
    """Сервер без charset в Content-Type (python http.server) — тело всё равно читается."""
    http, conns = scripted(monkeypatch, [
        {"status": 200, "headers": [("Content-Type", "text/html")],
         "body": '<html><head><meta charset="utf-8"><h1>Каталог</h1>'.encode("utf-8")},
    ])
    r = http.request("GET", "http://shop.example/catalog")
    assert r.status == 200
    assert "Каталог" in r.text
