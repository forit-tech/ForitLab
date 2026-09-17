"""Определение типа содержимого. Content-Type — подсказка, тело — истина.

При рассогласовании (сервер отдал `application/json`, а прислал HTML) доверяем
телу, а не заголовку — как и остальной парсинг Forit Lab.
"""

from __future__ import annotations

import json

from .models import SourceType

_BINARY_CT = (
    "image/",
    "audio/",
    "video/",
    "font/",
    "application/octet-stream",
    "application/pdf",
    "application/zip",
    "application/gzip",
)


def _looks_json(sample: str) -> bool:
    s = sample.lstrip()
    if not s or s[0] not in "{[":
        return False
    try:
        json.loads(sample)
        return True
    except json.JSONDecodeError:
        return True  # усечённый большой JSON — судим по первому символу


def _looks_jsonl(sample: str) -> bool:
    lines = [ln for ln in sample.splitlines() if ln.strip()][:5]
    if len(lines) < 2:
        return False
    for ln in lines:
        try:
            json.loads(ln)
        except json.JSONDecodeError:
            return False
    return True


def _looks_csv(sample: str) -> bool:
    lines = [ln for ln in sample.splitlines() if ln.strip()][:5]
    if len(lines) < 2:
        return False
    for delim in (",", ";", "\t"):
        counts = [ln.count(delim) for ln in lines]
        if counts[0] >= 1 and len(set(counts)) == 1:
            return True
    return False


def _sniff_body(sample: str) -> SourceType:
    stripped = sample.lstrip()
    if not stripped:
        return SourceType.UNKNOWN
    low = stripped.lower()
    if low.startswith("<!doctype html") or low.startswith("<html") or "<html" in low[:200]:
        return SourceType.HTML
    if _looks_jsonl(sample):
        return SourceType.JSONL
    if _looks_json(sample):
        return SourceType.JSON
    if stripped.startswith("<?xml"):
        return SourceType.XML
    if stripped.startswith("<"):
        # разметка: html-теги → html, иначе xml
        return SourceType.HTML if low.startswith(("<html", "<!doctype", "<div", "<body", "<head")) else SourceType.XML
    if _looks_csv(sample):
        return SourceType.CSV
    return SourceType.UNKNOWN


def _from_content_type(ct: str) -> SourceType:
    if "ld+json" in ct:
        return SourceType.HTML  # JSON-LD живёт внутри HTML-страницы
    if "json" in ct:
        return SourceType.JSON
    if "html" in ct:
        return SourceType.HTML
    if "xml" in ct:
        return SourceType.XML
    if "csv" in ct:
        return SourceType.CSV
    if ct.startswith("text/"):
        return SourceType.TEXT
    return SourceType.UNKNOWN


def source_type_from(content_type: str, body: str | bytes) -> SourceType:
    if isinstance(body, bytes):
        sample = body[:4096].decode("utf-8", "replace")
    else:
        sample = body[:4096]
    ct = (content_type or "").lower()

    if ct.startswith(_BINARY_CT):
        return SourceType.BINARY

    # тело — истина; заголовок используем, только если тело не опознали
    sniff = _sniff_body(sample)
    if sniff != SourceType.UNKNOWN:
        return sniff
    from_ct = _from_content_type(ct)
    if from_ct != SourceType.UNKNOWN:
        return from_ct
    return SourceType.TEXT if sample.strip() else SourceType.UNKNOWN
