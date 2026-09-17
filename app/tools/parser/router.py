"""HTTP-слой Web Parser.

1a: INPUT → INSPECT.
1b: анализ источников, рекомендация, валидация схемы, preview извлечения,
    sandbox для визуального выбора, экспорт (CSV/JSON/JSONL + asset manifest).
Мультистраничный сбор/пагинация/Crawl/Audit/Request Builder — НЕ здесь (позже).
"""

from __future__ import annotations

import csv
import io
import json

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field

from ...net import HttpClient
from ...net.errors import FetchError, UnsafeUrlError
from ...parser import TOOL_TITLE
from ...parser import extract as extract_mod
from ...parser import sources as sources_mod
from ...parser.detect import source_type_from
from ...parser.dom import backend_info
from ...parser.inputs import detect_input
from ...parser.inspect import inspect as run_inspect
from ...parser.models import ExtractionSchema, InputKind, SourceKind
from ...parser.sanitize import build_picker_document

router = APIRouter(prefix="/api/parser", tags=[TOOL_TITLE])

# executor + обработчик сбора (ленивая инициализация, чтобы тесты могли подменять)
_executor = None


def _get_executor():
    global _executor
    if _executor is None:
        from ...exec import build_default_executor
        from ...parser.collect import KIND as COLLECT_KIND, CollectHandler
        from ...parser.crawl_audit import KIND as CRAWL_KIND, CrawlHandler

        _executor = build_default_executor()
        _executor.register(COLLECT_KIND, CollectHandler())
        _executor.register(CRAWL_KIND, CrawlHandler())
    return _executor


# --------------------------------------------------------------------------
# загрузка источника (URL → fetch через общий HttpClient; иначе — как есть)
# --------------------------------------------------------------------------
def _load(raw: str) -> tuple[str, str, str]:
    """(text, base_url, source_type). Бросает AppError на не-html/json ввод."""
    from ...errors import AppError

    spec = detect_input(raw)
    if spec.kind == InputKind.URL:
        resp = HttpClient().request("GET", spec.url)
        return resp.text, resp.final_url, source_type_from(resp.content_type, resp.body).value
    if spec.kind in (InputKind.HTML, InputKind.JSON):
        return spec.body or "", "", spec.kind.value
    raise AppError("Для анализа нужен URL, HTML или JSON", {"kind": spec.kind.value})


# --------------------------------------------------------------------------
# схемы запросов
# --------------------------------------------------------------------------
class InspectRequest(BaseModel):
    input: str = Field(examples=["https://example.com"])


class AnalyzeRequest(BaseModel):
    input: str


class SchemaModel(BaseModel):
    source_kind: str = "repeated_dom"
    container_selector: str = ""
    container_type: str = "css"
    json_pointer: str | None = None
    fields: list[dict] = Field(default_factory=list)


class PreviewRequest(BaseModel):
    input: str
    schema_: SchemaModel = Field(alias="schema")
    limit: int = Field(default=25, ge=1, le=200)

    model_config = {"populate_by_name": True}


class ValidateRequest(BaseModel):
    schema_: SchemaModel = Field(alias="schema")
    model_config = {"populate_by_name": True}


# --------------------------------------------------------------------------
# endpoints
# --------------------------------------------------------------------------
@router.get("/backend", summary="Активный selector-backend")
def backend() -> dict:
    return backend_info()


@router.post("/inspect", summary="Определить источник и показать сводку (1a)")
def inspect(payload: InspectRequest) -> dict:
    return run_inspect(payload.input)


@router.post("/analyze", summary="Источники данных + рекомендация (1b)")
def analyze(payload: AnalyzeRequest) -> dict:
    try:
        text, base_url, stype = _load(payload.input)
    except (UnsafeUrlError, FetchError) as exc:
        return {"error": exc.message, "detail": exc.detail}
    if stype == "json":
        records = _json_array(text)
        rec = _json_recommendation(records)
    else:
        rec = sources_mod.analyze(text, base_url).to_dict()
    return {"backend": backend_info(), "source_type": stype, "recommendation": rec, "base_url": base_url}


@router.post("/validate", summary="Проверить схему извлечения до сбора (1b)")
def validate(payload: ValidateRequest) -> dict:
    schema = ExtractionSchema.from_dict(payload.schema_.model_dump(by_alias=False))
    extract_mod.validate_schema(schema)  # бросит понятную ошибку при проблеме
    return {"ok": True, "fields": [f.name for f in schema.fields]}


@router.post("/preview", summary="Превью извлечения по схеме на одной странице (1b)")
def preview(payload: PreviewRequest) -> dict:
    try:
        text, base_url, _ = _load(payload.input)
    except (UnsafeUrlError, FetchError) as exc:
        return {"error": exc.message, "detail": exc.detail}
    schema = ExtractionSchema.from_dict(payload.schema_.model_dump(by_alias=False))
    return _run_preview(text, base_url, schema, payload.limit)


class RequestModel(BaseModel):
    method: str = "GET"
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    cookies: dict[str, str] = Field(default_factory=dict)
    body: str | None = None
    content_type: str | None = None


@router.post("/build-request", summary="URL/cURL → RequestSpec (1c)")
def build_request(payload: AnalyzeRequest) -> dict:
    from ...parser.inputs import detect_input
    from ...parser.models import InputKind, RequestSpec

    spec = detect_input(payload.input)
    if spec.kind == InputKind.CURL and spec.request:
        req = spec.request
    elif spec.kind == InputKind.URL:
        req = RequestSpec(method="GET", url=spec.url or "")
    else:
        return {"error": "Ожидается URL или строка curl"}
    # отдаём реальные значения — билдер редактирует их на клиенте; на сервер не пишем
    return {"request": req.to_dict()}


@router.post("/request", summary="Выполнить запрос и показать ответ (1c Explore)")
def do_request(payload: RequestModel) -> dict:
    from ...parser.models import RequestSpec, SourceType

    spec = RequestSpec(
        method=payload.method.upper() or "GET",
        url=payload.url,
        headers=dict(payload.headers),
        cookies=dict(payload.cookies),
        body=payload.body,
        content_type=payload.content_type,
    )
    headers = dict(spec.headers)
    if spec.content_type and not any(k.lower() == "content-type" for k in headers):
        headers["Content-Type"] = spec.content_type
    if spec.cookies and not any(k.lower() == "cookie" for k in headers):
        headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in spec.cookies.items())
    body = spec.body.encode("utf-8") if isinstance(spec.body, str) else spec.body

    try:
        # Явный запрос, построенный пользователем (как в Postman) — robots не применяем,
        # но SSRF/pinning остаются. Секреты не логируются; в ответе — маскируются.
        resp = HttpClient().request(spec.method, spec.url, headers=headers, body=body, respect_robots=False)
    except (UnsafeUrlError, FetchError) as exc:
        return {"error": exc.message, "detail": exc.detail, "request": spec.to_masked()}

    stype = source_type_from(resp.content_type, resp.body)
    from ...parser.inspect import _response_view

    result = {"request": spec.to_masked(), "response": _response_view(resp, stype).to_dict()}
    if stype in (SourceType.JSON, SourceType.JSONL):
        try:
            result["json"] = json.loads(resp.text)
        except (json.JSONDecodeError, ValueError):
            result["json"] = None
    return result


class ReproduceRequest(BaseModel):
    request: RequestModel | None = None
    url: str | None = None
    schema_: SchemaModel | None = Field(default=None, alias="schema")
    model_config = {"populate_by_name": True}


@router.post("/reproduce", summary="Воспроизводимый код: curl + Python (1f)")
def reproduce(payload: ReproduceRequest) -> dict:
    from ...parser.models import RequestSpec
    from ...parser.reproduce import reproduce as gen

    if payload.request:
        spec = RequestSpec(method=payload.request.method.upper(), url=payload.request.url,
                           headers=dict(payload.request.headers), cookies=dict(payload.request.cookies),
                           body=payload.request.body, content_type=payload.request.content_type)
    elif payload.url:
        spec = RequestSpec(method="GET", url=payload.url)
    else:
        return {"error": "Нужен url или request"}
    schema = ExtractionSchema.from_dict(payload.schema_.model_dump(by_alias=False)) if payload.schema_ else None
    return gen(spec, schema)


@router.post("/sandbox", summary="Санитизированный HTML для визуального выбора (1b)")
def sandbox(payload: AnalyzeRequest) -> dict:
    try:
        text, base_url, stype = _load(payload.input)
    except (UnsafeUrlError, FetchError) as exc:
        return {"error": exc.message, "detail": exc.detail}
    if stype == "json":
        return {"error": "Визуальный выбор доступен для HTML-страниц, не для JSON"}
    # opaque-origin picker-документ: строгий CSP + только наш picker + postMessage
    return {"html": build_picker_document(text, base_url), "base_url": base_url}


@router.post("/export", response_class=PlainTextResponse, summary="Экспорт результата (1b)")
def export(
    payload: PreviewRequest,
    format: str = Query(default="csv", pattern="^(csv|json|jsonl|manifest)$"),
) -> Response:
    text, base_url, _ = _load(payload.input)
    schema = ExtractionSchema.from_dict(payload.schema_.model_dump(by_alias=False))
    result = _run_preview(text, base_url, schema, payload.limit)
    if "error" in result:
        return Response(content=json.dumps(result, ensure_ascii=False), media_type="application/json", status_code=400)

    if format == "manifest":
        body = json.dumps(result["assets"], ensure_ascii=False, indent=2)
        return _download(body, "application/json", "assets-manifest.json")
    body, media, name = _serialize(result["columns"], result["rows"], format)
    return _download(body, media, name)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _run_preview(text: str, base_url: str, schema: ExtractionSchema, limit: int) -> dict:
    from ...errors import AppError

    try:
        if schema.source_kind == SourceKind.REPEATED_DOM:
            return extract_mod.apply_schema(text, schema, base_url, limit=limit)
        if schema.source_kind in (SourceKind.JSON_LD, SourceKind.EMBEDDED_JSON):
            records = sources_mod.json_records(text, base_url, schema.source_kind)
            fields = [f.name for f in schema.fields] or None
            return extract_mod.project_json(records, fields, limit=limit)
        return {"error": f"Источник {schema.source_kind.value} в 1b не извлекается (нужен запрос/пагинация — позже)"}
    except AppError as exc:
        return {"error": exc.message, "detail": exc.detail}
    except ValueError as exc:
        return {"error": str(exc)}


def _json_array(text: str) -> list:
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return []
    return sources_mod._largest_record_array(data) or ([data] if isinstance(data, dict) else [])


def _json_recommendation(records: list) -> dict:
    from ...parser.models import Confidence, SourceCandidate, SourceRecommendation

    keys = sources_mod._keys(records)
    cand = SourceCandidate(
        kind=SourceKind.EMBEDDED_JSON,
        location="вставленный JSON",
        record_count=len(records),
        fields=keys[:20],
        structured=True,
        pagination_detected=False,
        stable_ids=any("id" in k.lower() for k in keys),
        evidence=[f"{len(records)} объектов", f"ключи: {', '.join(keys[:8])}"],
        confidence=Confidence.HIGH if records else Confidence.LOW,
    )
    return SourceRecommendation(
        selected=cand if records else None,
        reason=f"Вставленный JSON: {len(records)} объектов" if records else "В JSON не найдено массива объектов",
        confidence=cand.confidence,
    ).to_dict()


def _serialize(columns: list[str], rows: list[dict], fmt: str) -> tuple[str, str, str]:
    if fmt in ("csv", "tsv"):
        buf = io.StringIO()
        writer = csv.writer(buf, delimiter="\t" if fmt == "tsv" else ",", lineterminator="\n")
        writer.writerow(columns)
        for row in rows:
            writer.writerow([row.get(c, "") for c in columns])
        return buf.getvalue(), "text/csv", "extract.csv"
    if fmt == "jsonl":
        return "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", "application/x-ndjson", "extract.jsonl"
    return json.dumps(rows, ensure_ascii=False, indent=2), "application/json", "extract.json"


def _download(body: str, media: str, filename: str) -> Response:
    return Response(
        content=body,
        media_type=f"{media}; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --------------------------------------------------------------------------
# 1d — Multi-page collection (chunked-cursor)
# --------------------------------------------------------------------------
class CollectRequest(BaseModel):
    input: str = Field(description="URL-источник (стартовая страница каталога)")
    schema_: SchemaModel = Field(alias="schema")
    max_pages: int | None = None
    max_rows: int | None = None
    allow_subdomains: bool = False
    respect_robots: bool = True
    pagination: str = Field(default="auto", pattern="^(auto|none)$")
    model_config = {"populate_by_name": True}


class StepRequest(BaseModel):
    cursor: str | None = None


@router.post("/collect", summary="Запустить многостраничный сбор (1d)")
def collect_start(payload: CollectRequest) -> dict:
    from ...parser.collect import build_plan

    schema = ExtractionSchema.from_dict(payload.schema_.model_dump(by_alias=False))
    options = {
        "max_pages": payload.max_pages,
        "max_rows": payload.max_rows,
        "allow_subdomains": payload.allow_subdomains,
        "respect_robots": payload.respect_robots,
        "pagination": payload.pagination,
    }
    options = {k: v for k, v in options.items() if v is not None}
    try:
        plan = build_plan(payload.input, schema, options)
    except ValueError as exc:
        return {"error": str(exc)}
    state = _get_executor().start(plan)
    return state.to_public()


@router.post("/collect/{job_id}/step", summary="Шаг сбора (порция страниц)")
def collect_step(job_id: str, payload: StepRequest) -> dict:
    from ...exec import StepBudget

    budget = StepBudget(max_units=999, max_ms=9000)  # реальные потолки внутри обработчика/настроек
    return _get_executor().step(job_id, cursor=payload.cursor, budget=budget).to_public()


@router.post("/collect/{job_id}/cancel", summary="Остановить сбор")
def collect_cancel(job_id: str) -> dict:
    return _get_executor().cancel(job_id).to_public()


@router.get("/collect/{job_id}/status", summary="Статус сбора")
def collect_status(job_id: str) -> dict:
    return _get_executor().status(job_id).to_public()


def _export_job(job_id: str, format: str, prefix: str) -> Response:
    from ...parser.results import ResultFile

    ex = _get_executor()
    state = ex.status(job_id)  # бросит NotFound, если джобы нет
    rows = list(ResultFile(ex._store.directory, job_id).read())
    columns = (state.internal_state.get("columns") if state.internal_state else None) or (list(rows[0].keys()) if rows else [])
    if format == "manifest":
        assets = [{"row": i, "url": v} for i, r in enumerate(rows) for v in r.values() if isinstance(v, str) and v.startswith(("http://", "https://"))]
        return _download(json.dumps(assets, ensure_ascii=False, indent=2), "application/json", f"{prefix}-{job_id}-manifest.json")
    body, media, _ = _serialize(columns, rows, format)
    return _download(body, media, f"{prefix}-{job_id}.{'jsonl' if format == 'jsonl' else format}")


@router.get("/collect/{job_id}/export", response_class=PlainTextResponse, summary="Экспорт собранного датасета")
def collect_export(job_id: str, format: str = Query(default="csv", pattern="^(csv|json|jsonl|manifest)$")) -> Response:
    return _export_job(job_id, format, "collect")


# --------------------------------------------------------------------------
# 1e — Crawl / Audit (тот же chunked-executor, kind=parser.crawl)
# --------------------------------------------------------------------------
class CrawlRequest(BaseModel):
    input: str = Field(description="URL стартовой страницы")
    max_pages: int | None = None
    max_depth: int | None = None
    allow_subdomains: bool = False
    respect_robots: bool = True


@router.post("/crawl", summary="Запустить обход сайта (1e)")
def crawl_start(payload: CrawlRequest) -> dict:
    from ...parser.crawl_audit import build_plan

    options = {"max_pages": payload.max_pages, "max_depth": payload.max_depth,
               "allow_subdomains": payload.allow_subdomains, "respect_robots": payload.respect_robots}
    options = {k: v for k, v in options.items() if v is not None}
    try:
        plan = build_plan(payload.input, options)
    except ValueError as exc:
        return {"error": str(exc)}
    return _get_executor().start(plan).to_public()


@router.post("/crawl/{job_id}/step", summary="Шаг обхода")
def crawl_step(job_id: str, payload: StepRequest) -> dict:
    from ...exec import StepBudget

    return _get_executor().step(job_id, cursor=payload.cursor, budget=StepBudget(max_units=999, max_ms=9000)).to_public()


@router.post("/crawl/{job_id}/cancel", summary="Остановить обход")
def crawl_cancel(job_id: str) -> dict:
    return _get_executor().cancel(job_id).to_public()


@router.get("/crawl/{job_id}/status", summary="Статус обхода")
def crawl_status(job_id: str) -> dict:
    return _get_executor().status(job_id).to_public()


@router.get("/crawl/{job_id}/export", response_class=PlainTextResponse, summary="Экспорт audit-таблицы")
def crawl_export(job_id: str, format: str = Query(default="csv", pattern="^(csv|json|jsonl|manifest)$")) -> Response:
    return _export_job(job_id, format, "crawl")
