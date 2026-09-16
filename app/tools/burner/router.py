"""HTTP-слой Data Burner."""

from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field

from ...config import settings
from ...errors import AppError
from . import TOOL_TITLE
from .generator import MEDIA_TYPES, filename_for, generate
from .presets import PRESET_DESCRIPTIONS, drifted_spec, preset_spec, weird_of_the_day
from .spec import DatasetSpec, DriftSpec, OutputFormat

router = APIRouter(prefix="/api/burner", tags=[TOOL_TITLE])


class PresetInfo(BaseModel):
    id: str
    description: str
    example: str


class DatasetResponse(BaseModel):
    summary: dict
    content: str = Field(description="Готовый файл целиком, текстом")


class DriftPairResponse(BaseModel):
    """Ровно то, что принимает POST /api/drift/compare."""

    reference: str
    current: str
    reference_summary: dict
    current_summary: dict
    hint: str


class WeirdDatasetInfo(BaseModel):
    date: str
    rows: int
    format: str
    download: str
    answer: str
    note: str


def _check_size(rows: int, columns: int) -> None:
    if rows > settings.burner_max_rows:
        raise AppError(
            f"Максимум {settings.burner_max_rows} строк на бесплатном тарифе",
            {"requested": rows, "limit": settings.burner_max_rows},
        )
    if columns > settings.burner_max_columns:
        raise AppError(
            f"Максимум {settings.burner_max_columns} колонок",
            {"requested": columns, "limit": settings.burner_max_columns},
        )


def _as_file(spec: DatasetSpec, body: str) -> Response:
    return Response(
        content=body,
        media_type=MEDIA_TYPES[spec.format],
        headers={"Content-Disposition": f'attachment; filename="{filename_for(spec)}"'},
    )


@router.get("/presets", response_model=list[PresetInfo], summary="Готовые сценарии порчи")
async def presets() -> list[PresetInfo]:
    return [
        PresetInfo(
            id=name,
            description=description,
            example=f"/api/burner/datasets?preset={name}&rows=1000&format=csv",
        )
        for name, description in PRESET_DESCRIPTIONS.items()
    ]


@router.get(
    "/datasets",
    summary="Сгенерировать выгрузку по пресету",
    description="Отдаёт готовый файл. Для собственной схемы используйте POST с телом.",
    response_class=PlainTextResponse,
)
async def dataset_from_preset(
    preset: str = Query(default="dirty", description="Идентификатор из /api/burner/presets"),
    rows: int = Query(default=1000, ge=1),
    format: OutputFormat = Query(default="csv"),
    seed: int | None = Query(default=None, description="Фиксирует генерацию"),
    download: bool = Query(default=True, description="Отдать файлом или показать в браузере"),
) -> Response:
    if preset not in PRESET_DESCRIPTIONS:
        raise AppError(
            f"Неизвестный пресет: {preset}", {"available": sorted(PRESET_DESCRIPTIONS)}
        )
    spec = preset_spec(preset, rows, format, seed)
    _check_size(spec.rows, len(spec.columns))
    body, summary = generate(spec)

    if not download:
        return PlainTextResponse(body, media_type=MEDIA_TYPES[spec.format].split(";")[0])
    return _as_file(spec, body)


@router.post(
    "/datasets",
    response_model=DatasetResponse,
    summary="Сгенерировать выгрузку по своей схеме",
    description="Колонки, распределения и дефекты описываются в теле запроса.",
)
async def dataset_from_spec(spec: DatasetSpec) -> DatasetResponse:
    _check_size(spec.rows, len(spec.columns))
    body, summary = generate(spec)
    return DatasetResponse(summary=summary, content=body)


@router.get(
    "/pair",
    response_model=DriftPairResponse,
    summary="Пара выгрузок с заданным дрейфом",
    description=(
        "Возвращает reference и current одним ответом — его можно отправить "
        "прямо в POST /api/drift/compare."
    ),
)
async def drift_pair(
    preset: str = Query(default="clean"),
    rows: int = Query(default=2000, ge=1),
    format: OutputFormat = Query(default="csv"),
    seed: int | None = Query(default=None),
    numeric_shift: float = Query(default=0.6, ge=0.0, le=5.0),
    new_categories: int = Query(default=2, ge=0, le=20),
    null_rate_increase: float = Query(default=0.12, ge=0.0, le=0.9),
    change_type: bool = Query(default=True),
) -> DriftPairResponse:
    if preset not in PRESET_DESCRIPTIONS:
        raise AppError(
            f"Неизвестный пресет: {preset}", {"available": sorted(PRESET_DESCRIPTIONS)}
        )

    reference = preset_spec(preset, rows, format, seed)
    _check_size(reference.rows, len(reference.columns))

    drift = DriftSpec(
        numeric_shift=numeric_shift,
        new_categories=new_categories,
        null_rate_increase=null_rate_increase,
        change_type=change_type,
    )
    current = drifted_spec(reference, drift, seed)
    _check_size(current.rows, len(current.columns))

    reference_body, reference_summary = generate(reference)
    current_body, current_summary = generate(current)

    return DriftPairResponse(
        reference=reference_body,
        current=current_body,
        reference_summary=reference_summary,
        current_summary=current_summary,
        hint=(
            "POST /api/drift/compare с телом "
            '{"reference": <reference>, "current": <current>} покажет, '
            "что именно из подложенного нашлось."
        ),
    )


@router.get(
    "/weird-of-the-day",
    summary="Странный датасет дня",
    description=(
        "Один синтетический датасет в сутки с ровно одной подложенной проблемой. "
        "Ответ — в /api/burner/weird-of-the-day/answer, но сначала попробуйте сами."
    ),
    response_class=PlainTextResponse,
)
async def weird_dataset(
    for_date: date | None = Query(default=None, alias="date"),
    rows: int = Query(default=2000, ge=1),
    format: OutputFormat = Query(default="csv"),
) -> Response:
    target = for_date or datetime.now(timezone.utc).date()
    spec, case_id, _ = weird_of_the_day(target, rows, format)
    _check_size(spec.rows, len(spec.columns))
    body, _ = generate(spec)
    return Response(
        content=body,
        media_type=MEDIA_TYPES[spec.format],
        headers={
            "Content-Disposition": f'attachment; filename="{filename_for(spec)}"',
            # Идентификатор задачи не раскрываем: в нём весь смысл игры.
            "X-Weird-Date": target.isoformat(),
        },
    )


@router.get(
    "/weird-of-the-day/answer",
    response_model=WeirdDatasetInfo,
    summary="Что было не так с датасетом дня",
)
async def weird_answer(
    for_date: date | None = Query(default=None, alias="date"),
    rows: int = Query(default=2000, ge=1),
    format: OutputFormat = Query(default="csv"),
) -> WeirdDatasetInfo:
    target = for_date or datetime.now(timezone.utc).date()
    spec, case_id, answer = weird_of_the_day(target, rows, format)
    return WeirdDatasetInfo(
        date=target.isoformat(),
        rows=spec.rows,
        format=spec.format,
        download=f"/api/burner/weird-of-the-day?date={target.isoformat()}",
        answer=f"[{case_id}] {answer}",
        note="Файл детерминирован: тот же день — тот же датасет, ответ можно перепроверить.",
    )
