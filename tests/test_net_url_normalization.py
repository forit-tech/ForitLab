"""Регрессия на UnicodeEncodeError в серверных запросах (Parser + Chaos).

Ручная приёмка нашла краш на реальных URL: кириллица в path/query и IDN-домен
попадали в http.client без percent-encoding/IDNA и падали при ASCII-кодировании
строки запроса. Нормализация теперь централизована в check_syntax; здесь
проверяем именно те классы URL, что встречаются в жизни.
"""

from __future__ import annotations

import socket

import pytest

from app.net.client import HttpClient
from app.net.resolver import ResolvedAddr
from app.net.ssrf import check_syntax


class _PublicResolver:
    def resolve(self, host: str, port: int | None = None) -> list[ResolvedAddr]:
        return [ResolvedAddr(socket.AF_INET, "93.184.216.34")]


class _AsciiOnlyConn:
    """Имитирует http.client: строку запроса кодирует в ASCII, как реальный сокет.

    Так тест ловит именно исходный баг — сырой Unicode в path падал бы здесь.
    """

    def __init__(self, script: dict) -> None:
        self._script = script
        self.request_calls: list[dict] = []

    def request(self, method, path, body=None, headers=None):
        path.encode("ascii")  # <-- до фикса кириллический path здесь падал
        for key, value in (headers or {}).items():
            str(key).encode("ascii")
            str(value).encode("latin-1")  # http.client кодирует заголовки в latin-1
        self.request_calls.append({"method": method, "path": path, "headers": headers})

    def getresponse(self):
        class _R:
            status = 200
            _h = [("Content-Type", "text/html")]
            _b = b"<html>ok</html>"

            def getheaders(self):
                return self._h

            def getheader(self, n, d=None):
                return next((v for k, v in self._h if k.lower() == n.lower()), d)

            def read(self, amt=None):
                return self._b if amt is None else self._b[:amt]

        return _R()

    def close(self):
        pass


def _client(monkeypatch):
    http = HttpClient(resolver=_PublicResolver(), respect_robots=False)
    monkeypatch.setattr(http, "_open", lambda scheme, host, port, ip: _AsciiOnlyConn({}))
    return http


# ---- нормализация (check_syntax) -------------------------------------------

def test_cyrillic_path_is_percent_encoded_utf8():
    n, p = check_syntax("https://ru.wikipedia.org/wiki/Искусственный_интеллект")
    n.encode("ascii")  # не должно падать
    assert "%D0%98" in p.path  # «И» в UTF-8
    assert p.hostname == "ru.wikipedia.org"


def test_cyrillic_query_is_percent_encoded():
    n, p = check_syntax("https://ex.com/s?q=тест&utm=автотаргетинг")
    n.encode("ascii")
    assert "q=%D1%82%D0%B5%D1%81%D1%82" in p.query
    assert "utm=%D0%B0" in p.query


def test_idn_host_becomes_punycode():
    n, p = check_syntax("https://мойсайт.рф/путь")
    assert p.hostname == "xn--80arbjktj.xn--p1ai"
    assert p.hostname.encode("ascii")  # A-label годен для SNI/Host


def test_already_encoded_url_is_not_double_encoded():
    n, p = check_syntax("https://ex.com/wiki/%D0%98%D0%B7?a=1")
    assert p.path == "/wiki/%D0%98%D0%B7"  # %D0 не превратилось в %25D0


def test_mixed_encoded_and_raw():
    n, p = check_syntax("https://ex.com/%D0%98/тест")
    assert p.path == "/%D0%98/%D1%82%D0%B5%D1%81%D1%82"


def test_spaces_become_percent20():
    n, p = check_syntax("https://ex.com/a b?q=hello world")
    assert p.path == "/a%20b"
    assert p.query == "q=hello%20world"


def test_long_query_string_ok():
    long_q = "&".join(f"k{i}=знач{i}" for i in range(60))
    n, p = check_syntax(f"https://ex.com/x?{long_q}")
    n.encode("ascii")
    assert p.query.count("&") == 59


def test_fragment_is_dropped():
    n, _ = check_syntax("https://ex.com/p?a=1#section-два")
    assert "#" not in n


def test_ipv6_literal_and_port_preserved():
    n, p = check_syntax("http://[2606:2800:220:1:248:1893:25c8:1946]:80/x")
    assert p.hostname == "2606:2800:220:1:248:1893:25c8:1946"
    assert p.port == 80
    assert n.startswith("http://[2606:")


# ---- сквозной путь через HttpClient (ловит исходный краш) --------------------

def test_request_cyrillic_url_does_not_crash(monkeypatch):
    http = _client(monkeypatch)
    r = http.request("GET", "https://ru.wikipedia.org/wiki/Искусственный_интеллект?x=тест")
    assert r.status == 200


def test_request_idn_url_does_not_crash(monkeypatch):
    http = _client(monkeypatch)
    r = http.request("GET", "https://мойсайт.рф/путь")
    assert r.status == 200


def test_request_long_cyrillic_query_does_not_crash(monkeypatch):
    http = _client(monkeypatch)
    url = (
        "https://practicum.yandex.ru/machine-learning/?utm_source=yandex"
        "&utm_campaign=Yan_Perfmax_RF_Data&utm_term=автотаргетинг&rn=Москва"
    )
    r = http.request("GET", url)
    assert r.status == 200


def test_redirect_to_cyrillic_url_is_normalized(monkeypatch):
    """Location на Unicode-URL проходит ту же нормализацию + SSRF на новом hop."""
    http = HttpClient(resolver=_PublicResolver(), respect_robots=False)
    scripts = [
        {"status": 302, "location": "https://ru.wikipedia.org/wiki/Тест"},
        {"status": 200},
    ]
    state = {"i": 0}

    class _RedirConn(_AsciiOnlyConn):
        def __init__(self, script):
            super().__init__(script)

        def getresponse(self):
            i = state["i"]
            state["i"] += 1
            s = scripts[i]
            loc = s.get("location")

            class _R:
                status = s["status"]
                _h = [("Location", loc)] if loc else [("Content-Type", "text/html")]
                _b = b""

                def getheaders(self):
                    return self._h

                def getheader(self, n, d=None):
                    return next((v for k, v in self._h if k.lower() == n.lower()), d)

                def read(self, amt=None):
                    return self._b

            return _R()

    monkeypatch.setattr(http, "_open", lambda scheme, host, port, ip: _RedirConn({}))
    r = http.request("GET", "https://ru.wikipedia.org/start")
    assert r.status == 200
    assert "%D0%A2" in r.final_url  # «Т» в редиректном URL закодирован


def test_ssrf_still_blocks_private_after_normalization():
    """Нормализация не ослабляет SSRF: приватный IDN-хост всё равно режется на резолве."""
    from app.net.errors import UnsafeUrlError

    class _PrivateResolver:
        def resolve(self, host, port=None):
            return [ResolvedAddr(socket.AF_INET, "127.0.0.1")]

    http = HttpClient(resolver=_PrivateResolver(), respect_robots=False, allow_private=False)
    with pytest.raises(UnsafeUrlError):
        http.request("GET", "https://мойсайт.рф/путь")
