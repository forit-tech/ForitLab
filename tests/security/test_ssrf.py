"""SSRF: классификация адресов и синтаксическая проверка URL."""

from __future__ import annotations

import pytest

from app.net.ssrf import ALLOWED_PORTS, ALLOWED_SCHEMES, check_syntax, classify_ip


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",          # loopback
        "10.0.0.1",           # private
        "192.168.1.1",        # private
        "172.16.0.1",         # private
        "169.254.169.254",    # link-local / cloud metadata
        "::1",                # loopback v6
        "fe80::1",            # link-local v6
        "::ffff:127.0.0.1",   # IPv4-mapped loopback
        "::ffff:10.0.0.1",    # IPv4-mapped private
        "0.0.0.0",            # unspecified
        "224.0.0.1",          # multicast
        "100.64.0.1",         # CGNAT (не глобальный)
        "203.0.113.7",        # TEST-NET (не глобальный)
    ],
)
def test_internal_and_nonglobal_addresses_blocked(ip: str) -> None:
    safe, reason = classify_ip(ip)
    assert not safe, f"{ip} должен блокироваться"
    assert reason


@pytest.mark.parametrize("ip", ["93.184.216.34", "8.8.8.8", "1.1.1.1", "2606:2800:220:1:248:1893:25c8:1946"])
def test_public_addresses_allowed(ip: str) -> None:
    safe, _ = classify_ip(ip)
    assert safe, f"{ip} должен проходить"


def test_garbage_ip_blocked() -> None:
    safe, reason = classify_ip("not-an-ip")
    assert not safe and reason


def test_syntax_rejects_non_http_schemes() -> None:
    from app.net.errors import UnsafeUrlError

    for url in ("file:///etc/passwd", "ftp://example.com/x", "gopher://example.com"):
        with pytest.raises(UnsafeUrlError):
            check_syntax(url)


def test_syntax_rejects_bad_port_and_userinfo() -> None:
    from app.net.errors import UnsafeUrlError

    with pytest.raises(UnsafeUrlError):
        check_syntax("http://example.com:8080/")  # порт вне 80/443
    with pytest.raises(UnsafeUrlError):
        check_syntax("http://user:pass@example.com/")  # user:pass
    with pytest.raises(UnsafeUrlError):
        check_syntax("http:///nopath")  # нет хоста


def test_syntax_accepts_standard() -> None:
    normalized, parsed = check_syntax("https://example.com/path?q=1")
    assert parsed.hostname == "example.com"
    assert normalized.startswith("https://example.com/path")
    assert 443 in ALLOWED_PORTS or None in ALLOWED_PORTS
    assert "https" in ALLOWED_SCHEMES


# ==========================================================================
# Dev-оверрайды не должны становиться production-дефолтами (acceptance-gate).
# Локально для fixture мы поднимали FORIT_SCRAPE_ALLOW_PRIVATE=1 и
# FORIT_SCRAPE_EXTRA_PORTS=8199 — но безопасные значения по умолчанию обязаны
# оставаться закрытыми, иначе Host-0 пропустит loopback/private/нестандартный порт.
# ==========================================================================
def test_production_defaults_are_locked_down() -> None:
    from app.config import settings

    assert settings.scrape_allow_private is False, "по умолчанию приватные адреса запрещены"
    assert settings.scrape_extra_ports == set(), "по умолчанию нет разрешённых доп. портов"
    assert 8199 not in ALLOWED_PORTS  # dev-порт fixture не зашит в дефолты


def test_extra_port_rejected_without_override() -> None:
    """Без FORIT_SCRAPE_EXTRA_PORTS адрес на 8199 (fixture-порт) отклоняется синтаксисом."""
    from app.net.errors import UnsafeUrlError

    with pytest.raises(UnsafeUrlError):
        check_syntax("http://127.0.0.1:8199/page1.html")


def test_loopback_blocked_by_default_even_via_client(monkeypatch):
    """Host-0: с дефолтными настройками HttpClient не ходит на loopback/private."""
    import socket

    from app.net.client import HttpClient
    from app.net.errors import UnsafeUrlError
    from app.net.resolver import ResolvedAddr

    class _LoopbackResolver:
        def resolve(self, host, port=None):
            return [ResolvedAddr(socket.AF_INET, "127.0.0.1")]

    # allow_private не задаём → берётся дефолт settings (False)
    http = HttpClient(resolver=_LoopbackResolver(), respect_robots=False)
    with pytest.raises(UnsafeUrlError):
        http.request("GET", "http://internal.example/secret")
