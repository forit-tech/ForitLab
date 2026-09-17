"""Анализ доступных источников данных + рекомендация.

Не «магический best_source», а модель с доказательствами: сколько записей,
какие поля, структурировано ли, есть ли стабильные ID, и чего мы НЕ знаем
(limitations). В 1b рекомендуем то, что реально можем посчитать сейчас
(repeated_dom / json_ld / embedded_json). API попадает в альтернативы с
ограничением «нужен запрос для проверки» — без фейкового record_count.
"""

from __future__ import annotations

import json

from .dom import parse as dom_parse
from .fields import propose_fields
from .models import (
    Confidence,
    ExtractionSchema,
    SourceCandidate,
    SourceKind,
    SourceRecommendation,
)

_CONF_WEIGHT = {Confidence.HIGH: 3, Confidence.MEDIUM: 2, Confidence.LOW: 1}


def _signature(el) -> str:
    cls = ".".join(el.classes)
    return f"{el.tag}.{cls}" if cls else el.tag


def _selector_for(el) -> str:
    return el.tag + "".join(f".{c}" for c in el.classes) if el.classes else el.tag


def detect_repeated(doc, *, max_groups: int = 5) -> list[tuple[float, list, str]]:
    """Группы повторяющихся соседей поверх ParserDOM (не stdlib-дерева)."""
    found: list[tuple[float, list, str]] = []

    def visit(el, depth: int = 0) -> None:
        if depth > 40:
            return
        groups: dict[str, list] = {}
        for child in el.children():
            groups.setdefault(_signature(child), []).append(child)
        for members in groups.values():
            if len(members) >= 3:
                texts = [len(m.text()) for m in members]
                avg = sum(texts) / len(texts) if texts else 0
                if avg < 1:
                    continue
                score = len(members) * min(avg, 200) / 200
                found.append((score, members, _selector_for(members[0])))
        for child in el.children():
            visit(child, depth + 1)

    visit(doc.root)
    found.sort(key=lambda x: x[0], reverse=True)
    seen: set[str] = set()
    out: list[tuple[float, list, str]] = []
    for score, members, sel in found:
        if sel in seen:
            continue
        seen.add(sel)
        out.append((score, members, sel))
        if len(out) >= max_groups:
            break
    return out


def _stable_ids(members) -> bool:
    for m in members[:6]:
        attrs = m.attrs
        if "id" in attrs:
            return True
        if any(k.startswith("data-") and "id" in k for k in attrs):
            return True
    return False


def _largest_record_array(obj) -> list:
    best: list = []

    def walk(o) -> None:
        nonlocal best
        if isinstance(o, list):
            dicts = [x for x in o if isinstance(x, dict)]
            if len(dicts) > len(best):
                best = dicts
            for x in o:
                walk(x)
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)

    walk(obj)
    return best


def _keys(records: list) -> list[str]:
    seen: list[str] = []
    for r in records[:200]:
        if isinstance(r, dict):
            for k in r:
                if k not in seen:
                    seen.append(k)
    return seen


def analyze(html: str, base_url: str = "") -> SourceRecommendation:
    doc = dom_parse(html, base_url)
    candidates: list[SourceCandidate] = []

    # --- repeated DOM (можем посчитать прямо сейчас) ---
    groups = detect_repeated(doc)
    if groups:
        _, members, sel = groups[0]
        fields = propose_fields(members[0])
        stable = _stable_ids(members)
        candidates.append(
            SourceCandidate(
                kind=SourceKind.REPEATED_DOM,
                location=sel,
                record_count=len(members),
                fields=[f.name for f in fields],
                structured=True,
                pagination_detected=False,
                stable_ids=stable,
                evidence=[
                    f"{len(members)} повторяющихся элементов «{sel}»",
                    f"предложенные поля: {', '.join(f.name for f in fields)}",
                    "стабильные id у карточек" if stable else "явных id у карточек не видно",
                ],
                confidence=Confidence.HIGH if len(members) >= 6 else Confidence.MEDIUM,
                limitations=[],
                schema=ExtractionSchema(source_kind=SourceKind.REPEATED_DOM, container_selector=sel, fields=fields),
            )
        )

    # --- json-ld и embedded json (через существующий разбор скриптов) ---
    from ..tools.scrape.parser import parse as parse_page

    page = parse_page(html, base_url)

    ld_records: list = []
    for block in page.jsonld:
        ld_records.extend(_largest_record_array(block) or ([block] if isinstance(block, dict) else []))
    if len(ld_records) >= 1:
        keys = _keys(ld_records)
        candidates.append(
            SourceCandidate(
                kind=SourceKind.JSON_LD,
                location="script[type=application/ld+json]",
                record_count=len(ld_records),
                fields=keys[:20],
                structured=True,
                pagination_detected=False,
                stable_ids=any(k.lower() in ("@id", "id", "sku") for k in keys),
                evidence=[f"{len(ld_records)} объектов в JSON-LD", f"ключи: {', '.join(keys[:8])}"],
                confidence=Confidence.HIGH if len(ld_records) >= 3 else Confidence.MEDIUM,
                limitations=[],
                schema=ExtractionSchema(source_kind=SourceKind.JSON_LD, fields=[]),
            )
        )

    best_embedded: list = []
    for script in page.scripts:
        text = script.strip()
        if not text or text[0] not in "{[":
            continue
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            continue
        arr = _largest_record_array(data)
        if len(arr) > len(best_embedded):
            best_embedded = arr
    if len(best_embedded) >= 3:
        keys = _keys(best_embedded)
        candidates.append(
            SourceCandidate(
                kind=SourceKind.EMBEDDED_JSON,
                location="inline <script> (hydration/state)",
                record_count=len(best_embedded),
                fields=keys[:20],
                structured=True,
                pagination_detected=False,
                stable_ids=any("id" in k.lower() for k in keys),
                evidence=[f"{len(best_embedded)} объектов во встроенном JSON", f"ключи: {', '.join(keys[:8])}"],
                confidence=Confidence.HIGH,
                limitations=["Источник данных страницы; для постраничного сбора нужен API/пагинация (позже)"],
                schema=ExtractionSchema(source_kind=SourceKind.EMBEDDED_JSON, fields=[]),
            )
        )

    # --- API-кандидаты (посчитать сейчас нельзя — только как альтернатива) ---
    from ..tools.scrape.discovery import candidates_from_page

    for c in candidates_from_page(page, base_url)[:3]:
        candidates.append(
            SourceCandidate(
                kind=SourceKind.API,
                location=c["url"],
                record_count=None,
                fields=[],
                structured=True,
                pagination_detected=False,
                stable_ids=False,
                evidence=[f"кандидат в API ({c['confidence']}), источник: {c['source']}"],
                confidence=Confidence(c["confidence"]) if c["confidence"] in ("low", "medium", "high") else Confidence.LOW,
                limitations=["Число записей и пагинация не проверены — нужен запрос (Explore/Collect, позже)"],
                schema=None,
            )
        )

    return _recommend(candidates)


def _recommend(candidates: list[SourceCandidate]) -> SourceRecommendation:
    if not candidates:
        return SourceRecommendation(selected=None, reason="Источников данных не обнаружено", confidence=Confidence.LOW)

    # выбираем среди тех, что реально можем извлечь сейчас (есть record_count)
    countable = [c for c in candidates if c.record_count is not None]
    if not countable:
        return SourceRecommendation(
            selected=None,
            reason="Найдены только кандидаты в API — их нужно проверить запросом (позже). Извлекаемых прямо сейчас источников нет.",
            confidence=Confidence.LOW,
            alternatives=candidates,
        )

    def key(c: SourceCandidate):
        return (_CONF_WEIGHT[c.confidence], c.record_count or 0, 1 if c.structured else 0)

    countable.sort(key=key, reverse=True)
    best = countable[0]
    alternatives = [c for c in candidates if c is not best]
    reason = (
        f"{best.kind.value}: {best.record_count} записей, "
        f"{'структурировано' if best.structured else 'слабо структурировано'}"
        + (", стабильные id" if best.stable_ids else "")
        + (", пагинация" if best.pagination_detected else "")
    )
    return SourceRecommendation(selected=best, reason=reason, confidence=best.confidence, alternatives=alternatives)


def json_records(html: str, base_url: str, kind: SourceKind) -> list:
    """Записи для json-источника (для preview/export проекции)."""
    from ..tools.scrape.parser import parse as parse_page

    page = parse_page(html, base_url)
    if kind == SourceKind.JSON_LD:
        out: list = []
        for block in page.jsonld:
            out.extend(_largest_record_array(block) or ([block] if isinstance(block, dict) else []))
        return out
    if kind == SourceKind.EMBEDDED_JSON:
        best: list = []
        for script in page.scripts:
            text = script.strip()
            if not text or text[0] not in "{[":
                continue
            try:
                data = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                continue
            arr = _largest_record_array(data)
            if len(arr) > len(best):
                best = arr
        return best
    return []
