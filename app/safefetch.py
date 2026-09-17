"""Обратная совместимость поверх нового сетевого ядра :mod:`app.net`.

Раньше здесь жила вся SSRF-логика и загрузка страниц. Теперь ядро переехало
в :mod:`app.net` (клиент с IP-pinning, защитой от DNS rebinding и сохранением
TLS hostname verification), а этот модуль оставлен как стабильный фасад: Web
Harvester и API Finder импортируют привычные имена и работают без изменений.

Публичный контракт (не менять без миграции потребителей):
    FetchResult, fetch(), validate_url(), robots_allows(),
    UnsafeUrlError, FetchError, RobotsDisallowedError,
    ALLOWED_SCHEMES, ALLOWED_PORTS
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import settings
from .net import HttpClient, SystemResolver
from .net.errors import FetchError, RobotsDisallowedError, UnsafeUrlError
from .net.ssrf import ALLOWED_PORTS, ALLOWED_SCHEMES, check_syntax, classify_ip

__all__ = [
    "FetchResult",
    "fetch",
    "validate_url",
    "robots_allows",
    "UnsafeUrlError",
    "FetchError",
    "RobotsDisallowedError",
    "ALLOWED_SCHEMES",
    "ALLOWED_PORTS",
]


@dataclass
class FetchResult:
    """Форма ответа старого Web Harvester. Поля не убираем — на них завязан scrape."""

    url: str
    final_url: str
    status: int
    content_type: str
    charset: str
    body: bytes
    text: str
    elapsed_ms: float
    redirects: list[str] = field(default_factory=list)
    truncated: bool = False
    headers: dict[str, str] = field(default_factory=dict)


def _client() -> HttpClient:
    # Настройки читаются на каждый вызов: тесты подменяют settings в рантайме.
    return HttpClient()


def validate_url(raw_url: str) -> str:
    """Проверяет схему, порт, адрес назначения. Возвращает нормализованный URL.

    Семантика сохранена: резолв + проверка каждого полученного адреса на
    принадлежность внутренним сетям. Ничего не загружает.
    """
    normalized, parsed = check_syntax(raw_url)
    if not settings.scrape_allow_private:
        try:
            addrs = SystemResolver().resolve(parsed.hostname, parsed.port)
        except LookupError as exc:
            raise UnsafeUrlError(f"Не удалось разрезолвить имя: {exc}", {"host": parsed.hostname}) from exc
        for addr in addrs:
            safe, reason = classify_ip(addr.ip)
            if not safe:
                raise UnsafeUrlError(
                    f"Адрес отклонён: {reason}",
                    {
                        "host": parsed.hostname,
                        "hint": "Защита от SSRF. Для локальных адресов есть FORIT_SCRAPE_ALLOW_PRIVATE.",
                    },
                )
    return normalized


def robots_allows(url: str) -> tuple[bool, str]:
    return _client().robots_allows(url)


def fetch(url: str, *, respect_robots: bool | None = None) -> FetchResult:
    response = _client().request("GET", url, respect_robots=respect_robots)
    return FetchResult(
        url=response.url,
        final_url=response.final_url,
        status=response.status,
        content_type=response.content_type,
        charset=response.charset,
        body=response.body,
        text=response.text,
        elapsed_ms=response.elapsed_ms,
        redirects=[hop.url for hop in response.redirect_chain],
        truncated=response.truncated,
        headers=response.headers,
    )
