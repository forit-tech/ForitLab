"""HTTP-слой File Inspector. Тонкий: вся логика в inspect/metadata/sanitize.

Оркестратор смонтирует этот router в main.py — здесь его НЕ монтируем.
"""

from __future__ import annotations

import urllib.parse

from fastapi import APIRouter, File, Query, UploadFile
from fastapi.responses import Response

from ..config import settings
from ..errors import PayloadTooLargeError, UnprocessableDataError
from ..schemas import ErrorResponse
from . import TOOL_TITLE
from .inspect import inspect_file
from .sanitize import sanitize_copy

router = APIRouter(prefix="/api/file", tags=[TOOL_TITLE])

# Лимит загрузки: берём общий тарифный лимит, но не больше 25 МБ (константа MVP).
MAX_UPLOAD_BYTES = min(settings.max_upload_bytes, 25 * 1024 * 1024)
_READ_CHUNK = 1 << 20  # 1 МБ

ERRORS = {
    413: {"model": ErrorResponse, "description": "Файл больше лимита"},
    422: {"model": ErrorResponse, "description": "Файл прочитан, но непригоден для анализа"},
}


async def _read_upload(upload: UploadFile) -> tuple[str, bytes]:
    """Прочитать загрузку порциями с проверкой лимита. Возвращает (имя, байты)."""
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = await upload.read(_READ_CHUNK)
        if not chunk:
            break
        size += len(chunk)
        if size > MAX_UPLOAD_BYTES:
            raise PayloadTooLargeError(
                f"Файл больше лимита {MAX_UPLOAD_BYTES // (1024 * 1024)} МБ",
                {"limit_bytes": MAX_UPLOAD_BYTES},
            )
        chunks.append(chunk)
    await upload.close()
    data = b"".join(chunks)
    if not data:
        raise UnprocessableDataError("Файл пустой")
    return upload.filename or "file", data


@router.post(
    "/inspect",
    responses=ERRORS,
    summary="Инспекция метаданных файла",
    description="Загрузите файл → отчёт: размер, sha256, mime/format, метаданные и чувствительные поля.",
)
async def inspect_endpoint(file: UploadFile = File(description="Файл для инспекции")) -> dict:
    name, data = await _read_upload(file)
    # Битые/незнакомые файлы не должны ронять — inspect_file устойчив сам по себе.
    return inspect_file(name, data).as_dict()


@router.post(
    "/sanitize",
    response_model=None,  # эндпоинт возвращает либо JSON-dict, либо файловый Response
    responses=ERRORS,
    summary="Очистить метаданные (before/after)",
    description=(
        "Загрузите файл → отчёт до/после очистки и список убранных полей. "
        "С download=true возвращает очищенные байты как вложение."
    ),
)
async def sanitize_endpoint(
    file: UploadFile = File(description="Файл для очистки"),
    download: bool = Query(default=False, description="Вернуть очищенные байты как attachment"),
) -> dict | Response:
    name, data = await _read_upload(file)
    cleaned, removed = sanitize_copy(name, data)
    before = inspect_file(name, data).as_dict()

    if cleaned is None:
        result = {
            "before": before,
            "after": before,
            "removed_fields": [],
            "can_sanitize": False,
        }
        if download:
            # Нечего чистить — не отдаём файл, отвечаем понятной ошибкой статуса.
            raise UnprocessableDataError(
                "Для этого формата безопасная очистка не поддержана",
                {"format": before["format"]},
            )
        return result

    after = inspect_file(name, cleaned).as_dict()

    if download:
        cleaned_name = _cleaned_name(name)
        quoted = urllib.parse.quote(cleaned_name)
        return Response(
            content=cleaned,
            media_type=after["mime"],
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{quoted}",
                "X-Removed-Fields": str(len(removed)),
            },
        )

    return {
        "before": before,
        "after": after,
        "removed_fields": removed,
        "can_sanitize": True,
    }


def _cleaned_name(name: str) -> str:
    """foo.jpg → foo.clean.jpg (имя для скачивания очищенной копии)."""
    if "." in name:
        stem, ext = name.rsplit(".", 1)
        return f"{stem}.clean.{ext}"
    return f"{name}.clean"
