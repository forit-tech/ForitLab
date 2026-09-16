"""Поиск открытых API на странице.

Ничего магического: мы читаем то, что сайт сам о себе рассказывает —
заголовки, ссылки, инлайновые скрипты — и предлагаем кандидатов. Проверять
их или нет, решает пользователь: каждая проверка это лишний запрос к чужому
серверу.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from .parser import PageParser

#: Пути, по которым принято публиковать схему API.
WELL_KNOWN_PATHS = (
    "/openapi.json",
    "/swagger.json",
    "/swagger/v1/swagger.json",
    "/api/openapi.json",
    "/api/schema",
    "/api/docs",
    "/docs/openapi.json",
    "/.well-known/openapi.json",
    "/graphql",
    "/api",
    "/api/v1",
    "/rest/api",
    "/sitemap.xml",
    "/feed",
    "/rss",
)

#: URL внутри скриптов: именно так фронтенд выдаёт эндпоинты своего бэкенда.
URL_IN_SCRIPT = re.compile(
    r"""["'`](?P<url>(?:https?://[^\s"'`]+|/[A-Za-z0-9_\-./]*))["'`]""",
)
API_HINTS = ("/api/", "/rest/", "/graphql", "/v1/", "/v2/", ".json", "/rpc/", "/query")
IGNORED_SUFFIXES = (".js", ".css", ".png", ".jpg", ".jpeg", ".svg", ".webp", ".woff", ".woff2", ".ico")


def _confidence(url: str, source: str) -> str:
    if source in {"link_alternate_json", "json_ld"}:
        return "high"
    if "/api/" in url or "/graphql" in url or url.endswith(".json"):
        return "high" if source == "html" else "medium"
    return "low"


def candidates_from_page(page: PageParser, base_url: str) -> list[dict[str, str]]:
    found: dict[str, dict[str, str]] = {}

    def add(url: str, source: str, note: str) -> None:
        absolute = urljoin(base_url, url)
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"}:
            return
        if absolute.lower().endswith(IGNORED_SUFFIXES):
            return
        if absolute in found:
            return
        found[absolute] = {
            "url": absolute,
            "source": source,
            "note": note,
            "confidence": _confidence(absolute, source),
            "same_host": parsed.netloc == urlparse(base_url).netloc,
        }

    for item in page.alternate_json:
        add(item["url"], "link_alternate_json", "Сайт сам объявил JSON-версию страницы")

    for feed in page.feeds:
        add(feed["url"], "feed", f"Лента {feed.get('type') or 'rss/atom'} — готовый структурированный источник")

    for block in page.jsonld:
        # В JSON-LD часто лежат ссылки на действия и эндпоинты поиска.
        for match in re.finditer(r'"(?:target|urlTemplate|url)"\s*:\s*"([^"]+)"', str(block)):
            url = match.group(1).split("{")[0]
            if any(hint in url for hint in API_HINTS):
                add(url, "json_ld", "Ссылка из структурированных данных schema.org")

    for link in page.links:
        if any(hint in link.href for hint in API_HINTS):
            add(link.href, "html", f"Ссылка на странице: {link.text[:60] or 'без текста'}")

    for script in page.scripts:
        for match in URL_IN_SCRIPT.finditer(script):
            url = match.group("url")
            if len(url) < 4 or len(url) > 300:
                continue
            if any(hint in url for hint in API_HINTS):
                add(url, "inline_script", "Адрес найден в инлайновом скрипте страницы")

    ordered = sorted(
        found.values(),
        key=lambda item: ({"high": 0, "medium": 1, "low": 2}[item["confidence"]], item["url"]),
    )
    return ordered[:100]


def well_known_candidates(base_url: str) -> list[dict[str, str]]:
    parsed = urlparse(base_url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    return [
        {
            "url": root + path,
            "source": "well_known",
            "note": "Стандартный путь — существование не проверялось",
            "confidence": "low",
            "same_host": True,
        }
        for path in WELL_KNOWN_PATHS
    ]
