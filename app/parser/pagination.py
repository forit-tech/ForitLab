"""Определение следующей страницы. Несколько стратегий, приоритет сверху вниз.

Поддержано: Link-заголовок rel=next, HTML <link/<a rel=next>, JSON next-URL
(next/next_url/links.next/meta.next), инкремент ?page/?p, инкремент offset+limit.
Курсор без готового URL (только next_cursor) в 1d не строим — это ограничение.
"""

from __future__ import annotations

import json
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from .dom import parse as dom_parse

_PAGE_PARAMS = ("page", "p", "pagenum", "pageindex")


def _with_param(url: str, key: str, value: int) -> str:
    p = urlparse(url)
    q = dict(parse_qsl(p.query, keep_blank_values=True))
    q[key] = str(value)
    return urlunparse((p.scheme, p.netloc, p.path, p.params, urlencode(q), p.fragment))


def _link_header_next(headers: dict[str, str] | None) -> str | None:
    if not headers:
        return None
    link = headers.get("link") or headers.get("Link")
    if not link:
        return None
    for part in link.split(","):
        if 'rel="next"' in part or "rel=next" in part:
            m = re.search(r"<([^>]+)>", part)
            if m:
                return m.group(1)
    return None


def _html_next(text: str, base_url: str) -> str | None:
    try:
        doc = dom_parse(text, base_url)
    except Exception:  # noqa: BLE001
        return None
    for el in doc.root.xpath("//*[@rel='next']"):
        href = el.get("href")
        if href:
            return urljoin(base_url, href)
    return None


def _json_next(data, base_url: str) -> str | None:
    if isinstance(data, dict):
        for key in ("next", "next_url", "nextUrl", "next_page", "nextPage"):
            v = data.get(key)
            if isinstance(v, str) and v.strip():
                return urljoin(base_url, v)
        links = data.get("links")
        if isinstance(links, dict) and isinstance(links.get("next"), str):
            return urljoin(base_url, links["next"])
        meta = data.get("meta")
        if isinstance(meta, dict) and isinstance(meta.get("next"), str):
            return urljoin(base_url, meta["next"])
    return None


def _query_increment(url: str) -> tuple[str, str] | None:
    p = urlparse(url)
    q = dict(parse_qsl(p.query, keep_blank_values=True))
    for key in _PAGE_PARAMS:
        if key in q and q[key].isdigit():
            return "query_page", _with_param(url, key, int(q[key]) + 1)
    if "offset" in q and "limit" in q and q["offset"].isdigit() and q["limit"].isdigit():
        return "offset_limit", _with_param(url, "offset", int(q["offset"]) + int(q["limit"]))
    return None


def detect_next(
    *,
    source_type: str,
    text: str,
    current_url: str,
    headers: dict[str, str] | None = None,
) -> tuple[str | None, str | None]:
    """Возвращает (kind, next_url) или (None, None)."""
    link = _link_header_next(headers)
    if link:
        return "link_header", urljoin(current_url, link)

    if source_type in ("json", "jsonl"):
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            data = None
        nxt = _json_next(data, current_url) if data is not None else None
        if nxt:
            return "json_next", nxt
    else:
        nxt = _html_next(text, current_url)
        if nxt:
            return "rel_next", nxt

    inc = _query_increment(current_url)
    if inc:
        return inc
    return None, None
