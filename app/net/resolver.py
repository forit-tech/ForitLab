"""Резолвер DNS за интерфейсом.

Вынесен отдельно ради одной вещи: возможности подменить его в тестах и
воспроизвести DNS rebinding (первый ответ публичный, второй — внутренний).
Продакшн-резолвер — :class:`SystemResolver`.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ResolvedAddr:
    family: int
    ip: str


class Resolver(Protocol):
    def resolve(self, host: str, port: int | None = None) -> list[ResolvedAddr]:  # pragma: no cover - протокол
        ...


class SystemResolver:
    """getaddrinfo с дедупликацией адресов."""

    def resolve(self, host: str, port: int | None = None) -> list[ResolvedAddr]:
        try:
            infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
        except socket.gaierror as exc:
            raise LookupError(exc.strerror or str(exc)) from exc
        seen: set[str] = set()
        out: list[ResolvedAddr] = []
        for family, _type, _proto, _canon, sockaddr in infos:
            ip = sockaddr[0]
            if ip not in seen:
                seen.add(ip)
                out.append(ResolvedAddr(family=family, ip=ip))
        return out
