"""Сборка site-report из page-findings и origin-findings.

Ключевая идея: page-findings (CSP/headers/cookies/content) агрегируются по id и
показывают «сколько страниц затронуто», а origin-findings (TLS/HSTS/server/CORS/
security.txt) добавляются ОДИН раз — сертификат не должен «размножаться» на
каждую из 51 страниц.
"""

from __future__ import annotations

from .models import SEVERITY_ORDER


def update_agg(agg: dict, url: str, findings: list[dict], examples_limit: int = 5) -> dict:
    """Инкрементально влить findings ОДНОЙ страницы в аккумулятор (мутирует agg).

    Дедуп по id внутри страницы: один id считается за одну затронутую страницу.
    """
    seen: set[str] = set()
    for f in findings:
        fid = f["id"]
        if fid in seen:
            continue
        seen.add(fid)
        entry = agg.setdefault(fid, {
            "id": fid,
            "severity": f["severity"],
            "title": f["title"],
            "affected_pages": 0,
            "examples": [],
            "why": f.get("why", ""),
            "recommendation": f.get("recommendation", ""),
        })
        entry["affected_pages"] += 1
        if len(entry["examples"]) < examples_limit:
            entry["examples"].append(url)
    return agg


def finalize_pages(agg: dict, checked_pages: int) -> list[dict]:
    """Аккумулятор → отсортированный список аггрегированных page-findings."""
    out = [
        {
            "id": e["id"],
            "severity": e["severity"],
            "title": e["title"],
            "affected_pages": e["affected_pages"],
            "checked_pages": checked_pages,
            "examples": e["examples"][:5],
            "why": e.get("why", ""),
            "recommendation": e.get("recommendation", ""),
        }
        for e in agg.values()
    ]
    out.sort(key=lambda x: (SEVERITY_ORDER[x["severity"]], -x["affected_pages"]))
    return out


def dedupe_origin(origin_findings: list[dict]) -> list[dict]:
    """Origin-findings добавляются один раз: дедуп по id, сортировка по важности."""
    by_id: dict[str, dict] = {}
    for f in origin_findings or []:
        by_id.setdefault(f["id"], f)
    out = list(by_id.values())
    out.sort(key=lambda x: SEVERITY_ORDER[x["severity"]])
    return out


def aggregate_pages(pages: list[dict], checked_pages: int | None = None) -> list[dict]:
    """Удобный all-in-one: pages = [{"url":..., "findings":[...]}].

    checked_pages по умолчанию = число страниц во входе.
    """
    agg: dict = {}
    for page in pages:
        update_agg(agg, page["url"], page.get("findings", []))
    return finalize_pages(agg, checked_pages if checked_pages is not None else len(pages))


def build_site_report(agg: dict, checked_pages: int, origin_findings: list[dict] | None = None) -> dict:
    """Объединить page-агрегат и origin-findings в отчёт по сайту."""
    aggregated = finalize_pages(agg, checked_pages)
    origins = dedupe_origin(origin_findings or [])
    summary = {
        s: sum(1 for a in aggregated if a["severity"] == s) for s in ("high", "medium", "low", "info")
    }
    return {
        "aggregated_findings": aggregated,
        "origin_findings": origins,
        "summary": summary,
    }
