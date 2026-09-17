"""TLS-инварианты: IP-pinning не отключает проверку сертификата по имени."""

from __future__ import annotations

import socket
import ssl

import pytest

from app.net import client as client_mod
from app.net.client import HttpClient, _PinnedHTTPSConnection


def test_default_context_verifies_hostname() -> None:
    ctx = ssl.create_default_context()
    assert ctx.check_hostname is True
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    # именно такой контекст использует клиент по умолчанию
    http = HttpClient(respect_robots=False)
    assert http._ssl_context.check_hostname is True
    assert http._ssl_context.verify_mode == ssl.CERT_REQUIRED


def test_pinned_https_uses_domain_for_sni_not_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    """connect() коннектится к IP, но server_hostname = домен (SNI + проверка cert)."""
    recorded: dict[str, object] = {}

    class FakeSock:
        def settimeout(self, *_a):  # pragma: no cover - заглушка
            pass

    def fake_create_connection(address, timeout=None, *args, **kwargs):
        recorded["address"] = address
        return FakeSock()

    class FakeCtx:
        check_hostname = True
        verify_mode = ssl.CERT_REQUIRED

        def wrap_socket(self, sock, server_hostname=None):
            recorded["server_hostname"] = server_hostname
            return sock

    monkeypatch.setattr(client_mod.socket, "create_connection", fake_create_connection)
    conn = _PinnedHTTPSConnection("example.com", "93.184.216.34", 443, 5.0, FakeCtx())
    conn.connect()

    assert recorded["address"] == ("93.184.216.34", 443), "коннект должен идти к запиненному IP"
    assert recorded["server_hostname"] == "example.com", "SNI/cert-hostname должен быть доменом, не IP"
