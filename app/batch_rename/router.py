"""HTTP-слой Batch Rename. Роутер тонкий: вся логика в domain-модулях.

Эндпоинты:
  POST /api/rename/plan   — {names, rules} → RenamePlan (только имена, для preview).
  POST /api/rename/apply  — multipart: файлы + rules (JSON) → ZIP с новыми именами.

Никакого применения без прошедшей валидации: если план не valid, apply
возвращает 400 вместе с самим планом, чтобы фронт показал причины.

Роутер намеренно НЕ монтируется в main.py — это делает оркестратор.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from . import TOOL_TITLE
from .archive import build_zip
from .plan import build_plan

router = APIRouter(prefix="/api/rename", tags=[TOOL_TITLE])

#: Лимиты apply (чтобы не собирать гигантский ZIP в памяти).
MAX_FILES = 500
MAX_TOTAL_BYTES = 100 * 1024 * 1024  # 100 МБ суммарно
_READ_CHUNK = 256 * 1024


class PlanRequest(BaseModel):
    """Запрос на построение плана без файлов — для живого preview."""

    names: list[str] = Field(default_factory=list, description="Исходные имена файлов")
    rules: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Правила в порядке применения: {operation, params}",
    )


@router.post("/plan", summary="Построить план переименования (preview)")
async def make_plan(request: PlanRequest) -> dict[str, Any]:
    """Собрать RenamePlan только по именам — файлы не нужны."""
    return build_plan(request.names, request.rules)


def _parse_rules(raw: str) -> list[dict[str, Any]]:
    try:
        rules = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"rules — невалидный JSON: {exc}") from exc
    if not isinstance(rules, list):
        raise HTTPException(status_code=422, detail="rules должен быть JSON-массивом")
    return rules


async def _read_upload(upload: UploadFile, budget: int) -> tuple[bytes, int]:
    """Прочитать файл порциями, не превышая оставшийся бюджет по размеру."""
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = await upload.read(_READ_CHUNK)
        if not chunk:
            break
        size += len(chunk)
        if size > budget:
            await upload.close()
            raise HTTPException(
                status_code=413,
                detail=f"Суммарный размер файлов превышает лимит {MAX_TOTAL_BYTES} байт",
            )
        chunks.append(chunk)
    await upload.close()
    return b"".join(chunks), size


@router.post("/apply", summary="Применить план → ZIP с новыми именами")
async def apply(
    files: list[UploadFile] = File(..., description="Файлы для переименования"),
    rules: str = Form(..., description="Правила как JSON-массив"),
) -> Response:
    """Построить план по именам загруженных файлов и, если valid, отдать ZIP.

    Если план невалиден — 400 с планом внутри (не применяем).
    """
    if not files:
        raise HTTPException(status_code=422, detail="Не передано ни одного файла")
    if len(files) > MAX_FILES:
        raise HTTPException(
            status_code=413,
            detail=f"Слишком много файлов ({len(files)} > {MAX_FILES})",
        )

    parsed_rules = _parse_rules(rules)
    names = [upload.filename or "" for upload in files]
    plan = build_plan(names, parsed_rules)

    if not plan["valid"]:
        # Валидация не прошла — ничего не применяем, отдаём план с причинами.
        return JSONResponse(
            status_code=400,
            content={"detail": "План не прошёл валидацию", "plan": plan},
        )

    # План valid — читаем содержимое и собираем ZIP под новыми именами.
    remaining = MAX_TOTAL_BYTES
    payload: list[tuple[str, bytes]] = []
    for upload, item in zip(files, plan["items"]):
        data, size = await _read_upload(upload, remaining)
        remaining -= size
        payload.append((item["new_name"], data))

    archive = build_zip(payload)
    headers = {"Content-Disposition": 'attachment; filename="renamed.zip"'}
    return Response(content=archive, media_type="application/zip", headers=headers)
