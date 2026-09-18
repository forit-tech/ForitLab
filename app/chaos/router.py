"""HTTP-слой нового Chaos (Passive Security Check). Namespace /api/chaos/v2.

Старый /api/chaos/respond (генератор плохих ответов) не трогаем — он остаётся
на прежнем месте. Новый Chaos живёт в отдельном namespace.
"""

from __future__ import annotations

import csv
import io
import json
from urllib.parse import urlparse, urlunparse

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field

from ..net import HttpClient
from ..net.errors import FetchError, UnsafeUrlError
from .active_safe import check_http_methods
from .metadata import check_robots, check_security_txt
from .models import lower_headers, sort_findings, summarize
from .passive import run_checks
from .tls import check_tls_origin

router = APIRouter(prefix="/api/chaos/v2", tags=["Chaos"])

_executor = None


def _get_executor():
    global _executor
    if _executor is None:
        from ..exec import build_default_executor
        from .audit import KIND as AUDIT_KIND, SecurityAuditHandler

        _executor = build_default_executor()
        _executor.register(AUDIT_KIND, SecurityAuditHandler())
    return _executor


class CheckRequest(BaseModel):
    url: str = Field(examples=["https://example.com"])


class AuditRequest(BaseModel):
    url: str
    max_pages: int | None = None
    max_depth: int | None = None


class StepRequest(BaseModel):
    cursor: str | None = None


@router.post("/check", summary="Пассивная проверка безопасности по URL (Chaos 1a)")
def check(payload: CheckRequest) -> dict:
    url = payload.url.strip()
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url  # по умолчанию пробуем https
    try:
        primary = HttpClient().request("GET", url, respect_robots=False)
    except (UnsafeUrlError, FetchError) as exc:
        return {"error": exc.message, "detail": exc.detail}

    # если итог https — отдельно проверяем, редиректит ли http:// на https
    http_probe = None
    parsed = urlparse(primary.final_url)
    if parsed.scheme == "https":
        http_url = urlunparse(("http", parsed.netloc, parsed.path or "/", "", "", ""))
        try:
            http_probe = HttpClient().request("GET", http_url, respect_robots=False)
        except (UnsafeUrlError, FetchError):
            http_probe = None

    report = run_checks(primary, http_probe, url)

    # origin-level проверки (сеть) — TLS / security.txt / robots / OPTIONS.
    origin_findings = _origin_checks(parsed)
    if origin_findings:
        merged = sort_findings(report["findings"] + origin_findings)
        report["findings"] = merged
        report["summary"] = summarize(merged)
        report["origin_findings"] = origin_findings
        report["checks_run"] = report["checks_run"] + ["tls", "security_txt", "robots", "options"]
    return report


def _origin_checks(parsed) -> list:
    """Best-effort origin-проверки для /check. Любая сетевая ошибка → пропуск."""
    origin = f"{parsed.scheme}://{parsed.netloc}"
    findings: list = []

    def _fetch(path: str, method: str = "GET"):
        try:
            return HttpClient().request(
                method, urlunparse((parsed.scheme, parsed.netloc, path, "", "", "")), respect_robots=False)
        except (UnsafeUrlError, FetchError):
            return None

    st = _fetch("/.well-known/security.txt")
    if st is not None:
        findings += check_security_txt(st.status, st.text, getattr(st, "content_type", ""), origin=origin)
    else:
        findings += check_security_txt(None, "", origin=origin)

    rb = _fetch("/robots.txt")
    findings += check_robots(rb.status if rb else None, rb.text if rb else None, origin=origin)

    opt = _fetch("/", method="OPTIONS")
    if opt is not None:
        findings += check_http_methods(lower_headers(opt.headers).get("allow"), origin=origin)

    if parsed.scheme == "https" and parsed.hostname:
        try:
            findings += check_tls_origin(parsed.hostname, parsed.port or 443)
        except Exception:  # noqa: BLE001 — origin-проба не должна ронять ответ
            pass

    return findings


@router.post("/tls", summary="Проверка TLS/сертификата по origin из URL")
def tls_check(payload: CheckRequest) -> dict:
    url = payload.url.strip()
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    if not parsed.hostname:
        return {"error": "В ссылке нет имени хоста"}
    origin = f"https://{parsed.hostname}:{parsed.port or 443}"
    try:
        findings = check_tls_origin(parsed.hostname, parsed.port or 443)
    except Exception as exc:  # noqa: BLE001
        return {"origin": origin, "error": str(exc), "findings": []}
    return {"origin": origin, "findings": sort_findings(findings), "summary": summarize(findings)}


# --------------------------------------------------------------------------
# Chaos 1b — Site-wide Passive Audit (тот же chunked-executor)
# --------------------------------------------------------------------------
@router.post("/audit", summary="Запустить проверку всего сайта (Chaos 1b)")
def audit_start(payload: AuditRequest) -> dict:
    from .audit import build_plan

    options = {"max_pages": payload.max_pages, "max_depth": payload.max_depth}
    options = {k: v for k, v in options.items() if v is not None}
    try:
        plan = build_plan(payload.url, options)
    except ValueError as exc:
        return {"error": str(exc)}
    return _get_executor().start(plan).to_public()


@router.post("/audit/{job_id}/step", summary="Шаг проверки сайта")
def audit_step(job_id: str, payload: StepRequest) -> dict:
    from ..exec import StepBudget

    return _get_executor().step(job_id, cursor=payload.cursor, budget=StepBudget(max_units=999, max_ms=9000)).to_public()


@router.post("/audit/{job_id}/cancel", summary="Остановить проверку сайта")
def audit_cancel(job_id: str) -> dict:
    return _get_executor().cancel(job_id).to_public()


@router.get("/audit/{job_id}/status", summary="Статус проверки сайта")
def audit_status(job_id: str) -> dict:
    return _get_executor().status(job_id).to_public()


@router.get("/audit/{job_id}/export", response_class=PlainTextResponse, summary="Экспорт по-страничных результатов")
def audit_export(job_id: str, format: str = Query(default="csv", pattern="^(csv|json)$")) -> Response:
    from ..parser.results import ResultFile

    ex = _get_executor()
    state = ex.status(job_id)
    rows = list(ResultFile(ex._store.directory, job_id).read())
    if format == "json":
        body, media = json.dumps(rows, ensure_ascii=False, indent=2), "application/json"
    else:
        cols = (state.internal_state.get("columns") if state.internal_state else None) or (list(rows[0].keys()) if rows else [])
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(cols)
        for r in rows:
            w.writerow([r.get(c, "") for c in cols])
        body, media = buf.getvalue(), "text/csv"
    return Response(content=body, media_type=f"{media}; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="audit-{job_id}.{format}"'})
