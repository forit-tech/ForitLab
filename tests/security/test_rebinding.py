"""DNS rebinding / TOCTOU и IP-pinning.

Ключевые инварианты:
1. если имя резолвится во внутренний адрес (rebinding-пейлоуд), запрос режется,
   каким бы «публичным» ни выглядел хост;
2. клиент коннектится ИМЕННО к проверенному IP (пиннинг), а не резолвит заново.
"""

from __future__ import annotations

import socket

import pytest

from app.net import client as client_mod
from app.net.client import HttpClient
from app.net.errors import FetchError, UnsafeUrlError
from app.net.resolver import ResolvedAddr


class FakeResolver:
    def __init__(self, addrs: list[ResolvedAddr]) -> None:
        self.addrs = addrs
        self.calls = 0

    def resolve(self, host: str, port: int | None = None) -> list[ResolvedAddr]:
        self.calls += 1
        return self.addrs


def test_rebinding_to_internal_is_blocked() -> None:
    # хост выглядит публичным, но резолвится в loopback → блок
    resolver = FakeResolver([ResolvedAddr(socket.AF_INET, "127.0.0.1")])
    http = HttpClient(resolver=resolver, respect_robots=False)
    with pytest.raises(UnsafeUrlError):
        http.request("GET", "http://totally-public.example/")


def test_any_internal_address_in_set_blocks() -> None:
    # один публичный + один внутренний адрес: всё равно блок
    resolver = FakeResolver(
        [ResolvedAddr(socket.AF_INET, "93.184.216.34"), ResolvedAddr(socket.AF_INET, "10.0.0.5")]
    )
    http = HttpClient(resolver=resolver, respect_robots=False)
    with pytest.raises(UnsafeUrlError):
        http.request("GET", "http://public-with-internal.example/")


def test_client_connects_to_pinned_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    """Коннект идёт к проверенному IP, резолв — один раз (нет второго независимого)."""
    resolver = FakeResolver([ResolvedAddr(socket.AF_INET, "93.184.216.34")])
    captured: dict[str, object] = {}

    def fake_create_connection(address, timeout=None, *args, **kwargs):
        captured["address"] = address
        raise OSError("stop here — коннект перехвачен тестом")

    monkeypatch.setattr(client_mod.socket, "create_connection", fake_create_connection)
    http = HttpClient(resolver=resolver, respect_robots=False)
    with pytest.raises(FetchError):
        http.request("GET", "http://public-host.example/path")

    assert captured["address"] == ("93.184.216.34", 80), "коннект не к запиненному IP"
    assert resolver.calls == 1, "должен быть ровно один резолв (нет повторного)"
