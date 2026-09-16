"""HTTP-слой Drift Lab. Роутер тонкий: вся логика в service.py."""

from __future__ import annotations

import time

from fastapi import APIRouter, File, Query, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from ...config import settings
from ...errors import PayloadTooLargeError, UnprocessableDataError
from ...schemas import (
    DeleteResponse,
    DriftReport,
    ErrorResponse,
    LimitsResponse,
    ProfileResponse,
    ReportList,
)
from . import TOOL_TITLE
from .render import render_text
from .service import (
    build_profile,
    delete_report,
    demo_payloads,
    get_report,
    limits,
    list_reports,
    run_comparison,
)

router = APIRouter(prefix="/api/drift", tags=[TOOL_TITLE])

ERRORS = {
    404: {"model": ErrorResponse, "description": "Отчёт не найден"},
    413: {"model": ErrorResponse, "description": "Файл больше лимита тарифа"},
    422: {"model": ErrorResponse, "description": "Файл прочитан, но непригоден для анализа"},
}

#: Максимум, который читаем из потока, прежде чем признать файл слишком большим.
_READ_CHUNK = 256 * 1024


class InlineCompareRequest(BaseModel):
    """Вариант без multipart: данные приходят прямо в JSON.

    Полезно и для curl-одностроки, и как запасной путь, если Passenger
    капризничает с multipart-загрузками.
    """

    reference: str = Field(description="Содержимое reference-файла (CSV/JSON/NDJSON)")
    current: str = Field(description="Содержимое current-файла (CSV/JSON/NDJSON)")
    reference_name: str = Field(default="reference", max_length=80)
    current_name: str = Field(default="current", max_length=80)
    save: bool = True


async def _read_upload(upload: UploadFile, label: str) -> bytes:
    """Читаем порциями, чтобы не втянуть в память файл больше лимита."""
    limit = settings.max_upload_bytes
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = await upload.read(_READ_CHUNK)
        if not chunk:
            break
        size += len(chunk)
        if size > limit:
            raise PayloadTooLargeError(
                f"Файл {label} больше лимита {settings.max_upload_mb:g} МБ",
                {"limit_bytes": limit, "hint": "Поднимается через FORIT_MAX_UPLOAD_MB"},
            )
        chunks.append(chunk)
    await upload.close()
    if not chunks:
        raise UnprocessableDataError(f"Файл {label} пустой")
    return b"".join(chunks)


@router.get(
    "/limits",
    response_model=LimitsResponse,
    summary="Лимиты обработки",
    description="Что именно ограничивает бесплатный тариф и какими переменными это меняется.",
)
async def read_limits() -> dict:
    return limits()


@router.post(
    "/reports",
    response_model=DriftReport,
    response_model_exclude_none=True,
    responses=ERRORS,
    summary="Сравнить две выгрузки",
    description=(
        "Принимает два файла (CSV/TSV/JSON/NDJSON) и возвращает отчёт о расхождениях: "
        "схема, распределения (PSI, KS), категории (chi², JSD), пропуски, утечки идентификаторов."
    ),
)
async def create_report(
    reference: UploadFile = File(description="Эталонная выгрузка"),
    current: UploadFile = File(description="Новая выгрузка"),
    save: bool = Query(default=True, description="Сохранить отчёт для повторного чтения"),
) -> dict:
    reference_payload = await _read_upload(reference, "reference")
    current_payload = await _read_upload(current, "current")
    return run_comparison(
        reference_payload,
        current_payload,
        reference_name=reference.filename or "reference",
        current_name=current.filename or "current",
        reference_filename=reference.filename,
        current_filename=current.filename,
        save=save,
    )


@router.post(
    "/compare",
    response_model=DriftReport,
    response_model_exclude_none=True,
    responses=ERRORS,
    summary="Сравнить две выгрузки, переданные текстом",
)
async def compare_inline(payload: InlineCompareRequest) -> dict:
    return run_comparison(
        payload.reference.encode("utf-8"),
        payload.current.encode("utf-8"),
        reference_name=payload.reference_name,
        current_name=payload.current_name,
        save=payload.save,
    )


@router.post(
    "/profile",
    response_model=ProfileResponse,
    response_model_exclude_none=True,
    responses=ERRORS,
    summary="Профиль одной выгрузки",
    description="Типы, пропуски, кардинальность, распределения — без сравнения.",
)
async def create_profile(file: UploadFile = File(description="Файл для профилирования")) -> dict:
    started = time.perf_counter()
    payload = await _read_upload(file, "file")
    profile = build_profile(payload, name=file.filename or "dataset", filename=file.filename)
    result = profile.as_dict()
    result["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
    return result


@router.get(
    "/demo",
    response_model=DriftReport,
    response_model_exclude_none=True,
    summary="Демо-отчёт на встроенных данных",
    description="Прогон на data/samples — чтобы попробовать инструмент, ничего не загружая.",
)
async def demo(
    save: bool = Query(default=False, description="Сохранять ли демо-отчёт"),
) -> dict:
    reference_payload, current_payload = demo_payloads()
    return run_comparison(
        reference_payload,
        current_payload,
        reference_name="reference.csv",
        current_name="current.csv",
        reference_filename="reference.csv",
        current_filename="current.csv",
        save=save,
    )


@router.get(
    "/reports",
    response_model=ReportList,
    summary="Список сохранённых отчётов",
)
async def read_reports(limit: int = Query(default=50, ge=1, le=200)) -> dict:
    return list_reports(limit)


@router.get(
    "/reports/{report_id}",
    response_model=DriftReport,
    response_model_exclude_none=True,
    responses=ERRORS,
    summary="Сохранённый отчёт",
)
async def read_report(report_id: str) -> dict:
    return get_report(report_id)


@router.get(
    "/reports/{report_id}/text",
    response_class=PlainTextResponse,
    responses={200: {"content": {"text/plain": {}}}, **ERRORS},
    summary="Отчёт в текстовом виде",
    description="Тот же отчёт, но человекочитаемым блоком — для тикета или CI-лога.",
)
async def read_report_text(report_id: str) -> PlainTextResponse:
    return PlainTextResponse(render_text(get_report(report_id)))


@router.delete(
    "/reports/{report_id}",
    response_model=DeleteResponse,
    responses=ERRORS,
    summary="Удалить отчёт",
)
async def remove_report(report_id: str) -> dict:
    delete_report(report_id)
    return {"deleted": True, "report_id": report_id}
