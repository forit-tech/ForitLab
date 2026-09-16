"""HTTP-слой API Finder."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from ...errors import NotFoundError
from ...safefetch import validate_url
from . import TOOL_TITLE
from .catalog import FREE_TYPES, STALE_AFTER_DAYS, get_registry
from .service import explore, explore_topic, match_candidate, search, surprise
from .verify import check_availability, probe_preview

router = APIRouter(prefix="/api/apifinder", tags=[TOOL_TITLE])


class FinderInfo(BaseModel):
    tool: str
    rule: str
    total_apis: int
    sources: list[str]
    categories: dict[str, int]
    free_types: list[str]
    stale_after_days: int


class CheckUrlRequest(BaseModel):
    url: str = Field(description="URL кандидата (например, из Web Harvester)")


@router.get("/", response_model=FinderInfo, summary="О каталоге и правилах")
def info() -> FinderInfo:
    registry = get_registry()
    return FinderInfo(
        tool="apifinder",
        rule=(
            "Только бесплатные API: free forever / free tier / open data / без ключа. "
            "Trial-only исключён. «Бесплатно» и «без ключа» — разные вещи."
        ),
        total_apis=len(registry.all()),
        sources=registry.source_names(),
        categories=registry.categories(),
        free_types=sorted(FREE_TYPES),
        stale_after_days=STALE_AFTER_DAYS,
    )


@router.get("/search", summary="Поиск API по теме и фильтрам")
def search_apis(
    q: str = Query(default="", description="Тема или задача естественным языком"),
    category: str | None = Query(default=None),
    no_key: bool | None = Query(default=None, description="Только без ключа"),
    free_type: str | None = Query(default=None, description="free_forever | free_tier | open_data"),
    cors: bool | None = Query(default=None),
    commercial: bool | None = Query(default=None, description="Разрешено коммерческое использование"),
    has_sdk: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
) -> dict:
    results = search(
        q,
        category=category,
        no_key=no_key,
        free_type=free_type,
        cors=cors,
        commercial=commercial,
        has_sdk=has_sdk,
        limit=limit,
    )
    return {"query": q, "count": len(results), "results": results}


@router.get("/categories", summary="Категории и число API в каждой")
def categories() -> dict:
    return get_registry().categories()


@router.get("/explore", summary="Режим Explore: темы для тех, кто не знает, что искать")
def explore_mode() -> dict:
    return explore()


@router.get("/explore/{topic_id}", summary="API по выбранной теме Explore")
def explore_by_topic(topic_id: str) -> dict:
    results = explore_topic(topic_id)
    if not results:
        raise NotFoundError(f"Неизвестная тема: {topic_id}")
    return {"topic": topic_id, "count": len(results), "results": results}


@router.get("/surprise", summary="Surprise me: связка API и идея проекта")
def surprise_me(seed: int | None = Query(default=None)) -> dict:
    return surprise(seed)


@router.get("/apis/{api_id}", summary="Карточка API")
def api_details(api_id: str) -> dict:
    record = get_registry().get(api_id)
    if record is None:
        raise NotFoundError(f"API {api_id} не найден в каталоге")
    return record.as_card()


@router.get(
    "/apis/{api_id}/check",
    summary="Проверить доступность эндпоинта",
    description=(
        "Проверяет только доступность публичного безопасного эндпоинта — не "
        "условия бесплатности. Пользовательские ключи не используются."
    ),
)
def api_check(api_id: str) -> dict:
    record = get_registry().get(api_id)
    if record is None:
        raise NotFoundError(f"API {api_id} не найден в каталоге")
    availability = check_availability(record.verify_url)
    record.availability = availability
    card = record.as_card()
    card["availability"] = availability
    return card


@router.get(
    "/apis/{api_id}/probe",
    summary="Тест эндпоинта с предпросмотром ответа",
    description="Доступность + кусок ответа. Начало цепочки probe → Build Dataset → Drift Lab.",
)
def api_probe(api_id: str) -> dict:
    record = get_registry().get(api_id)
    if record is None:
        raise NotFoundError(f"API {api_id} не найден в каталоге")
    preview = probe_preview(record.verify_url)
    return {
        "api": record.name,
        "verify_url": record.verify_url,
        "result": preview,
        "next": (
            "Если shape=array с item_keys — ответ готов для Build Dataset: "
            "передайте его в Web Harvester или сразу в Drift Lab."
        ),
    }


@router.post(
    "/check-url",
    summary="Мост из Web Harvester: опознать найденный API-кандидат",
    description=(
        "По URL из discovery пытается сопоставить запись каталога. Если совпадения "
        "нет — возвращает статус discovered без выдуманных условий."
    ),
)
def check_url(payload: CheckUrlRequest) -> dict:
    # Прогоняем через тот же SSRF-фильтр, что и остальные исходящие запросы.
    validate_url(payload.url)
    return match_candidate(payload.url)


@router.get("/favorites/export", summary="Экспорт выбранных API")
def export_favorites(
    ids: str = Query(description="Список id через запятую"),
    format: str = Query(default="json", description="json | csv"),
) -> dict:
    from fastapi.responses import PlainTextResponse

    registry = get_registry()
    wanted = [item.strip() for item in ids.split(",") if item.strip()]
    records = [registry.get(api_id) for api_id in wanted]
    found = [record for record in records if record is not None]
    missing = [api_id for api_id, record in zip(wanted, records) if record is None]

    today = datetime.now(timezone.utc).date()
    cards = [record.as_card(today) for record in found]

    if format == "csv":
        import csv
        import io

        buffer = io.StringIO()
        columns = ["id", "name", "category", "auth", "free_type", "request_limit", "docs_url", "last_verified_at"]
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(columns)
        for card in cards:
            writer.writerow([card.get(col, "") for col in columns])
        return PlainTextResponse(
            buffer.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="favorites.csv"'},
        )

    return {"count": len(cards), "missing": missing, "favorites": cards}
