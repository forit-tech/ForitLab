"""HTTP-слой Scrape Lab."""

from __future__ import annotations

import csv
import io
import json
import re
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field

from ...config import settings
from ...errors import AppError, NotFoundError
from . import TOOL_TITLE
from .discovery import candidates_from_page, well_known_candidates
from .entities import detect_entities
from .fetcher import FetchError, FetchResult, fetch, validate_url
from .parser import PageParser, parse

router = APIRouter(prefix="/api/scrape", tags=[TOOL_TITLE])

ExtractTarget = Literal["tables", "links", "images", "headings", "forms", "meta", "jsonld", "text"]
ExportFormat = Literal["csv", "tsv", "json", "ndjson"]

#: Сколько кандидатов проверяем реальным запросом. Больше — уже похоже на скан.
MAX_PROBES = 8


class ScrapeRequest(BaseModel):
    url: str = Field(description="Ссылка на страницу", examples=["https://example.com"])
    respect_robots: bool | None = Field(
        default=None,
        description="Переопределяет настройку сервера. Отключать на чужих сайтах не стоит.",
    )


class LimitsResponse(BaseModel):
    timeout_s: float
    max_bytes: int
    max_redirects: int
    respect_robots: bool
    allow_private_addresses: bool
    user_agent: str
    notes: list[str]


class SelfTestResponse(BaseModel):
    outbound_available: bool
    verdict: str
    checks: list[dict]


def _fetch_and_parse(url: str, respect_robots: bool | None) -> tuple[FetchResult, PageParser]:
    result = fetch(url, respect_robots=respect_robots)
    if "html" not in result.content_type and "xml" not in result.content_type:
        # Не HTML — разбирать нечего, но сказать об этом надо внятно.
        raise AppError(
            f"Ожидался HTML, а пришёл {result.content_type}",
            {
                "content_type": result.content_type,
                "bytes": len(result.body),
                "hint": "Для JSON-эндпоинтов используйте /api/scrape/apis?probe=true",
            },
        )
    return result, parse(result.text, result.final_url)


def _page_summary(result: FetchResult, page: PageParser) -> dict:
    internal = sum(1 for link in page.links if link.internal)
    words = len(re.findall(r"\w+", page.page_text()))

    return {
        "url": result.url,
        "final_url": result.final_url,
        "status": result.status,
        "content_type": result.content_type,
        "charset": result.charset,
        "elapsed_ms": result.elapsed_ms,
        "redirects": result.redirects,
        "truncated": result.truncated,
        "bytes": len(result.body),
        "meta": {
            "title": page.title,
            "description": page.meta.get("description") or page.meta.get("og:description"),
            "canonical": page.canonical,
            "lang": page.lang,
            "og": {k: v for k, v in page.meta.items() if k.startswith("og:")},
            "twitter": {k: v for k, v in page.meta.items() if k.startswith("twitter:")},
        },
        "counts": {
            "links": len(page.links),
            "links_internal": internal,
            "links_external": len(page.links) - internal,
            "images": len(page.images),
            "images_without_alt": sum(1 for image in page.images if not image.alt),
            "headings": len(page.headings),
            "tables": len(page.tables),
            "forms": len(page.forms),
            "json_ld_blocks": len(page.jsonld),
            "feeds": len(page.feeds),
            "words": words,
        },
        "extractable": [
            {
                "target": "tables",
                "items": len(page.tables),
                "download": "/api/scrape/extract?target=tables",
            },
            {"target": "links", "items": len(page.links), "download": "/api/scrape/extract?target=links"},
            {"target": "images", "items": len(page.images), "download": "/api/scrape/extract?target=images"},
            {
                "target": "headings",
                "items": len(page.headings),
                "download": "/api/scrape/extract?target=headings",
            },
            {"target": "forms", "items": len(page.forms), "download": "/api/scrape/extract?target=forms"},
            {"target": "jsonld", "items": len(page.jsonld), "download": "/api/scrape/extract?target=jsonld"},
            {"target": "meta", "items": len(page.meta), "download": "/api/scrape/extract?target=meta"},
            {"target": "text", "items": words, "download": "/api/scrape/extract?target=text"},
        ],
    }


@router.get("/limits", response_model=LimitsResponse, summary="Границы, в которых работает парсер")
def limits() -> LimitsResponse:
    return LimitsResponse(
        timeout_s=settings.scrape_timeout_s,
        max_bytes=settings.scrape_max_bytes,
        max_redirects=settings.scrape_max_redirects,
        respect_robots=settings.scrape_respect_robots,
        allow_private_addresses=settings.scrape_allow_private,
        user_agent=settings.scrape_user_agent,
        notes=[
            "Разрешены только http и https на портах 80 и 443.",
            "Адреса внутренних сетей отклоняются до соединения — защита от SSRF.",
            "Каждый редирект проверяется заново.",
            "robots.txt соблюдается по умолчанию.",
            "Тело страницы читается не целиком: сверх лимита помечается truncated.",
        ],
    )


@router.get(
    "/self-test",
    response_model=SelfTestResponse,
    summary="Работают ли исходящие соединения с этого хостинга",
    description=(
        "На бесплатных тарифах исходящий трафик часто закрыт. Эта ручка отвечает "
        "на вопрос «парсер вообще может работать здесь?» до того, как вы начнёте "
        "разбираться со своей ссылкой."
    ),
)
def self_test() -> SelfTestResponse:
    checks = []
    for url in ("https://example.com", "https://api.github.com/meta"):
        try:
            result = fetch(url, respect_robots=False)
            checks.append(
                {
                    "url": url,
                    "ok": True,
                    "status": result.status,
                    "elapsed_ms": result.elapsed_ms,
                    "bytes": len(result.body),
                }
            )
        except AppError as exc:
            checks.append({"url": url, "ok": False, "error": exc.message})

    available = any(check.get("ok") for check in checks)
    return SelfTestResponse(
        outbound_available=available,
        verdict=(
            "Исходящие соединения работают — парсер полноценно функционален."
            if available
            else "Исходящие соединения недоступны. Это ограничение хостинга, а не ошибка сервиса."
        ),
        checks=checks,
    )


@router.post("/inspect", summary="Разобрать страницу по ссылке")
def inspect(payload: ScrapeRequest) -> dict:
    result, page = _fetch_and_parse(payload.url, payload.respect_robots)
    summary = _page_summary(result, page)
    summary["tables"] = [table.as_dict() for table in page.tables]
    summary["headings"] = page.headings[:50]
    summary["feeds"] = page.feeds
    summary["forms"] = [
        {
            "action": form.action,
            "method": form.method,
            "fields": [
                {"name": f.name, "type": f.type, "required": f.required} for f in form.fields
            ],
        }
        for form in page.forms
    ]
    summary["json_ld"] = page.jsonld[:10]

    candidates = candidates_from_page(page, result.final_url)[:25]
    summary["api_candidates"] = candidates
    if candidates:
        # Мост к API Finder: любой кандидат можно опознать там.
        summary["open_in_api_finder"] = {
            "endpoint": "POST /api/apifinder/check-url",
            "note": "Передайте url кандидата, чтобы попробовать определить условия использования.",
        }

    summary["entities"] = detect_entities(result.text, result.final_url)
    summary["text_preview"] = page.page_text(1500)
    return summary


@router.get("/inspect", summary="То же, но ссылка в query — удобно для curl")
def inspect_query(url: str = Query(description="Ссылка на страницу")) -> dict:
    return inspect(ScrapeRequest(url=url))


@router.post(
    "/apis",
    summary="Найти открытые API, о которых сайт рассказывает сам",
    description=(
        "Собирает кандидатов из заголовков, ссылок и инлайновых скриптов. "
        "С `probe=true` дополнительно проверяет до восьми самых вероятных — "
        "это реальные запросы к чужому серверу, поэтому по умолчанию выключено."
    ),
)
def discover_apis(
    payload: ScrapeRequest,
    probe: bool = Query(default=False, description="Проверить кандидатов запросами"),
    include_well_known: bool = Query(default=True, description="Добавить стандартные пути"),
) -> dict:
    result, page = _fetch_and_parse(payload.url, payload.respect_robots)

    candidates = candidates_from_page(page, result.final_url)
    if include_well_known:
        known = {item["url"] for item in candidates}
        candidates += [item for item in well_known_candidates(result.final_url) if item["url"] not in known]

    probed: list[dict] = []
    if probe:
        targets = [
            item
            for item in candidates
            if item["same_host"] and item["confidence"] in {"high", "medium"}
        ][:MAX_PROBES]
        if not targets:
            targets = [item for item in candidates if item["same_host"]][:MAX_PROBES]

        for item in targets:
            probed.append(_probe(item))

    return {
        "url": result.final_url,
        "candidates": candidates,
        "probed": probed,
        "probe_limit": MAX_PROBES,
        "note": (
            "Кандидат — это не гарантия. Проверяйте вручную и соблюдайте "
            "условия использования сайта."
        ),
    }


def _probe(item: dict) -> dict:
    """Один осторожный запрос к кандидату: что там вообще лежит."""
    outcome: dict[str, object] = {"url": item["url"], "source": item["source"]}
    try:
        result = fetch(item["url"], respect_robots=True)
    except (AppError, FetchError) as exc:
        outcome.update({"ok": False, "error": exc.message})
        return outcome

    outcome.update(
        {
            "ok": True,
            "status": result.status,
            "content_type": result.content_type,
            "bytes": len(result.body),
            "elapsed_ms": result.elapsed_ms,
        }
    )
    if "json" in result.content_type:
        try:
            parsed = json.loads(result.text)
        except json.JSONDecodeError:
            outcome["json"] = False
            return outcome
        outcome["json"] = True
        if isinstance(parsed, dict):
            outcome["top_level_keys"] = list(parsed)[:25]
            outcome["shape"] = "object"
        elif isinstance(parsed, list):
            outcome["shape"] = "array"
            outcome["items"] = len(parsed)
            if parsed and isinstance(parsed[0], dict):
                outcome["item_keys"] = list(parsed[0])[:25]
                outcome["ready_for_drift"] = True
    return outcome


# ---------------------------------------------------------------------------
# Выгрузка
# ---------------------------------------------------------------------------


def _rows_for(target: str, page: PageParser, index: int | None) -> tuple[list[str], list[list[object]]]:
    if target == "tables":
        if not page.tables:
            raise NotFoundError("На странице нет таблиц")
        position = index or 0
        if position >= len(page.tables):
            raise NotFoundError(
                f"Таблицы с номером {position} нет",
                {"available": len(page.tables)},
            )
        table = page.tables[position]
        headers = table.headers or [f"column_{i + 1}" for i in range(len(table.rows[0]))]
        return headers, [list(row) for row in table.rows]

    if target == "links":
        return ["text", "href", "rel", "internal"], [
            [link.text, link.href, link.rel or "", link.internal] for link in page.links
        ]
    if target == "images":
        return ["src", "alt", "title", "has_alt"], [
            [image.src, image.alt or "", image.title or "", bool(image.alt)] for image in page.images
        ]
    if target == "headings":
        return ["level", "text"], [[item["level"], item["text"]] for item in page.headings]
    if target == "forms":
        rows = [
            [form.action, form.method, field.name or "", field.type, field.required]
            for form in page.forms
            for field in form.fields
        ]
        return ["action", "method", "field", "type", "required"], rows
    if target == "meta":
        return ["name", "content"], [[name, content] for name, content in page.meta.items()]

    raise NotFoundError(f"Нечего выгружать для target={target}")


def _serialize(headers: list[str], rows: list[list[object]], output: str) -> tuple[str, str]:
    if output in {"csv", "tsv"}:
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter="\t" if output == "tsv" else ",", lineterminator="\n")
        writer.writerow(headers)
        writer.writerows(rows)
        media = "text/csv" if output == "csv" else "text/tab-separated-values"
        return buffer.getvalue(), media
    if output == "ndjson":
        body = "\n".join(json.dumps(dict(zip(headers, row)), ensure_ascii=False) for row in rows)
        return body + "\n", "application/x-ndjson"
    records = [dict(zip(headers, row)) for row in rows]
    return json.dumps(records, ensure_ascii=False, indent=2), "application/json"


@router.get(
    "/extract",
    summary="Выгрузить часть страницы датасетом",
    description=(
        "Скачивает выбранный кусок в CSV/TSV/JSON/NDJSON. Результат можно "
        "сразу отправить в Drift Lab или Data Burner."
    ),
    response_class=PlainTextResponse,
)
def extract(
    url: str = Query(description="Ссылка на страницу"),
    target: ExtractTarget = Query(default="tables"),
    index: int | None = Query(default=None, description="Номер таблицы, если их несколько"),
    format: ExportFormat = Query(default="csv"),
    download: bool = Query(default=True),
    respect_robots: bool | None = Query(default=None),
) -> Response:
    result, page = _fetch_and_parse(url, respect_robots)
    host = urlparse(result.final_url).netloc.replace(":", "_")

    if target == "text":
        body, media = page.page_text(200_000), "text/plain"
        filename = f"{host}-text.txt"
    elif target == "jsonld":
        if not page.jsonld:
            raise NotFoundError("На странице нет блоков JSON-LD")
        body = json.dumps(page.jsonld, ensure_ascii=False, indent=2)
        media = "application/json"
        filename = f"{host}-jsonld.json"
    else:
        headers, rows = _rows_for(target, page, index)
        body, media = _serialize(headers, rows, format)
        extension = "jsonl" if format == "ndjson" else format
        suffix = f"-{index}" if target == "tables" and index else ""
        filename = f"{host}-{target}{suffix}.{extension}"

    response_headers = {"X-Scrape-Source": result.final_url}
    if download:
        response_headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return Response(content=body, media_type=f"{media}; charset=utf-8", headers=response_headers)


@router.get(
    "/entities",
    summary="Найти повторяющиеся сущности (карточки) на странице",
    description=(
        "Эвристика: ищет группы соседних элементов одинаковой структуры и "
        "вытаскивает из каждой общие поля. На нерегулярной разметке молчит."
    ),
)
def entities(
    url: str = Query(description="Ссылка на страницу"),
    respect_robots: bool | None = Query(default=None),
) -> dict:
    result = fetch(url, respect_robots=respect_robots)
    if "html" not in result.content_type:
        raise AppError(f"Ожидался HTML, пришёл {result.content_type}")
    groups = detect_entities(result.text, result.final_url)
    return {
        "url": result.final_url,
        "groups": groups,
        "note": (
            "Каждая группа — кандидат в датасет. Поля можно выбрать и выгрузить "
            "через /api/scrape/extract, либо собрать Build Dataset."
        ),
    }


@router.get(
    "/build-dataset",
    summary="Собрать датасет из повторяющихся сущностей",
    description="Превращает самую крупную группу карточек в строки CSV/JSON/NDJSON.",
    response_class=PlainTextResponse,
)
def build_dataset(
    url: str = Query(description="Ссылка на страницу"),
    group: int = Query(default=0, ge=0, description="Номер группы из /entities"),
    format: ExportFormat = Query(default="csv"),
    fields: str | None = Query(default=None, description="Поля через запятую; по умолчанию все общие"),
    download: bool = Query(default=True),
    respect_robots: bool | None = Query(default=None),
) -> Response:
    result = fetch(url, respect_robots=respect_robots)
    if "html" not in result.content_type:
        raise AppError(f"Ожидался HTML, пришёл {result.content_type}")

    groups = detect_entities(result.text, result.final_url, max_items=2000, include_items=True)
    if not groups:
        raise NotFoundError("Повторяющихся сущностей не найдено")
    if group >= len(groups):
        raise NotFoundError(f"Группы {group} нет", {"available": len(groups)})

    chosen = groups[group]
    columns = (
        [f.strip() for f in fields.split(",") if f.strip()] if fields else chosen["fields"]
    ) or ["title", "text"]

    rows = [[item.get(column, "") for column in columns] for item in chosen["items"]]

    body, media = _serialize(columns, rows, format)
    host = urlparse(result.final_url).netloc.replace(":", "_")
    extension = "jsonl" if format == "ndjson" else format
    headers = {"X-Scrape-Source": result.final_url}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{host}-entities.{extension}"'
    return Response(content=body, media_type=f"{media}; charset=utf-8", headers=headers)


@router.get("/validate", summary="Проверить ссылку, ничего не загружая")
def validate(url: str = Query(description="Ссылка для проверки")) -> dict:
    normalized = validate_url(url)
    parsed = urlparse(normalized)
    return {
        "url": normalized,
        "host": parsed.hostname,
        "scheme": parsed.scheme,
        "safe": True,
        "note": "Адрес прошёл проверку на внутренние сети, схему и порт. Запрос не отправлялся.",
    }
