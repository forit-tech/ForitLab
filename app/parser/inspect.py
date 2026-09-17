"""INSPECT: единственный рабочий поток 1a — INPUT → INSPECT.

Определяет вид ввода, при URL — фетчит через общий HttpClient (SSRF/pinning),
определяет тип источника и отдаёт сводку. Полноценные извлечение/рекомендация
источника/выбор полей — это 1b (Extraction Engine), здесь их НЕТ (без фейка).
"""

from __future__ import annotations

import json

from ..net import HttpClient
from ..net.errors import FetchError, UnsafeUrlError
from .detect import source_type_from
from .dom import backend_info
from .inputs import detect_input
from .models import InputKind, ResponseView, SourceType, RedirectHopView

_PREVIEW = 2000


def _response_view(resp, source_type: SourceType) -> ResponseView:
    from ..findings import mask_headers

    return ResponseView(
        url=resp.url,
        final_url=resp.final_url,
        method=resp.method,
        status=resp.status,
        content_type=resp.content_type,
        charset=resp.charset,
        source_type=source_type,
        size=len(resp.body),
        elapsed_ms=resp.elapsed_ms,
        resolved_ip=resp.resolved_ip,
        truncated=resp.truncated,
        headers=mask_headers(resp.headers),
        cookie_count=len(resp.cookies),
        redirect_chain=[RedirectHopView(url=h.url, status=h.status, location=h.location) for h in resp.redirect_chain],
        body_preview=resp.text[:_PREVIEW],
    )


def _html_summary(text: str, base_url: str) -> dict:
    """Лёгкая сводка + подсказки об источниках данных (фундамент для 1b)."""
    from ..tools.scrape.discovery import candidates_from_page
    from ..tools.scrape.entities import detect_entities
    from ..tools.scrape.parser import parse as parse_html

    page = parse_html(text, base_url)
    entities = detect_entities(text, base_url)
    candidates = candidates_from_page(page, base_url)[:15]
    return {
        "title": page.title,
        "counts": {
            "tables": len(page.tables),
            "links": len(page.links),
            "images": len(page.images),
            "headings": len(page.headings),
            "forms": len(page.forms),
            "json_ld": len(page.jsonld),
            "repeated_entities": len(entities),
        },
        # предварительные подсказки об источниках; полноценные SourceCandidate — в 1b
        "source_hints": [
            {"kind": "repeated_dom", "records": g.get("count"), "fields": g.get("fields", [])}
            for g in entities[:5]
        ]
        + [{"kind": "api", "location": c["url"], "confidence": c["confidence"]} for c in candidates[:5]]
        + ([{"kind": "json_ld", "records": len(page.jsonld)}] if page.jsonld else []),
        "next_step": "Извлечение полей и рекомендация источника — режим Extract (1b).",
    }


def _json_summary(text: str) -> dict:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return {"valid": False, "error": str(exc)}
    if isinstance(data, list):
        first = data[0] if data else None
        return {
            "valid": True,
            "shape": "array",
            "items": len(data),
            "item_keys": list(first)[:30] if isinstance(first, dict) else None,
            "next_step": "Дерево, вывод схемы и проекция массива в таблицу — режимы Explore/Extract (1b/1c).",
        }
    if isinstance(data, dict):
        return {
            "valid": True,
            "shape": "object",
            "top_level_keys": list(data)[:30],
            "next_step": "Дерево и вывод схемы — режим Explore (1c).",
        }
    return {"valid": True, "shape": type(data).__name__}


def inspect(raw: str) -> dict:
    spec = detect_input(raw)
    result: dict = {"input": spec.to_dict(), "backend": backend_info(), "notes": []}

    if spec.kind == InputKind.UNKNOWN:
        result["error"] = "Не похоже на URL, HTML, JSON или cURL. Вставьте ссылку, разметку, JSON или строку curl."
        return result

    if spec.kind == InputKind.URL:
        try:
            resp = HttpClient().request("GET", spec.url)
        except (UnsafeUrlError, FetchError) as exc:
            result["error"] = exc.message
            result["detail"] = exc.detail
            return result
        stype = source_type_from(resp.content_type, resp.body)
        result["response"] = _response_view(resp, stype).to_dict()
        result["source_type"] = stype.value
        if stype == SourceType.HTML:
            result["summary"] = _html_summary(resp.text, resp.final_url)
        elif stype in (SourceType.JSON, SourceType.JSONL):
            result["summary"] = _json_summary(resp.text if stype == SourceType.JSON else "[" + ",".join(resp.text.splitlines()[:200]) + "]")
        else:
            result["summary"] = {"note": f"Тип источника: {stype.value}. Разбор этого типа — в следующих субфазах."}
        return result

    if spec.kind == InputKind.HTML:
        result["source_type"] = SourceType.HTML.value
        result["summary"] = _html_summary(spec.body or "", "")
        return result

    if spec.kind == InputKind.JSON:
        result["source_type"] = SourceType.JSON.value
        result["summary"] = _json_summary(spec.body or "")
        return result

    if spec.kind == InputKind.CURL:
        # 1a: cURL только разбираем. Выполнение запроса — Request Builder (1c).
        result["source_type"] = SourceType.UNKNOWN.value
        result["request"] = spec.request.to_masked() if spec.request else None
        result["notes"].append("Разобран запрос из cURL. Выполнение — в режиме Explore / Request Builder (1c).")
        return result

    result["error"] = "Неизвестный вид ввода"
    return result
