"""Сетевое ядро Forit Lab: единственная дверь наружу.

Всё, что ходит в интернет от имени сервера (Web Parser, будущий Chaos,
URL-режимы других инструментов), обязано идти через :class:`HttpClient`.
Здесь же — SSRF-правила и резолвер за интерфейсом.

`app.safefetch` — тонкая обёртка над этим ядром для обратной совместимости
со старым Web Harvester и API Finder.
"""

from __future__ import annotations

from .client import Hop, HttpClient, HttpResponse
from .errors import FetchError, RobotsDisallowedError, UnsafeUrlError
from .resolver import ResolvedAddr, Resolver, SystemResolver
from .ssrf import ALLOWED_PORTS, ALLOWED_SCHEMES, check_syntax, classify_ip

__all__ = [
    "HttpClient",
    "HttpResponse",
    "Hop",
    "UnsafeUrlError",
    "FetchError",
    "RobotsDisallowedError",
    "Resolver",
    "SystemResolver",
    "ResolvedAddr",
    "classify_ip",
    "check_syntax",
    "ALLOWED_SCHEMES",
    "ALLOWED_PORTS",
]
