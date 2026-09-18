"""HTTP-слой инструмента Unicode. Тонкий: валидация → вызов домена → dict.

Префикс ``/api/unicode2``, чтобы не конфликтовать со старым ``/api/unicode``.
Роутер здесь НЕ монтируется в приложение — это делает оркестратор/registry.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..errors import PayloadTooLargeError
from . import MAX_TEXT_CHARS, TOOL_TITLE
from .clean import clean_copy, escape, normalize, unescape
from .inspect import inspect_text

router = APIRouter(prefix="/api/unicode2", tags=[TOOL_TITLE])


class TextRequest(BaseModel):
    text: str = Field(description="Текст для обработки")


class NormalizeRequest(BaseModel):
    text: str = Field(description="Текст для нормализации")
    form: str = Field(default="NFC", pattern="^(NFC|NFD|NFKC|NFKD)$")


class EscapeRequest(BaseModel):
    text: str = Field(description="Текст для escape/unescape")
    mode: str = Field(default="escape", pattern="^(escape|unescape)$")


def _check_length(text: str) -> None:
    if len(text) > MAX_TEXT_CHARS:
        raise PayloadTooLargeError(
            f"Максимум {MAX_TEXT_CHARS} символов за раз",
            {"received": len(text), "limit": MAX_TEXT_CHARS},
        )


@router.post("/inspect", summary="Анализ текста: невидимые символы, пробелы, нормализация")
async def inspect(payload: TextRequest) -> dict:
    _check_length(payload.text)
    return inspect_text(payload.text)


@router.post("/clean", summary="Clean Copy — безопасная бытовая очистка текста")
async def clean(payload: TextRequest) -> dict:
    _check_length(payload.text)
    cleaned, changes = clean_copy(payload.text)
    return {"cleaned": cleaned, "changes": changes}


@router.post("/normalize", summary="Нормализация Unicode (NFC/NFD/NFKC/NFKD)")
async def normalize_endpoint(payload: NormalizeRequest) -> dict:
    _check_length(payload.text)
    return {"result": normalize(payload.text, payload.form)}


@router.post("/escape", summary="Сделать невидимое видимым (escape) и обратно (unescape)")
async def escape_endpoint(payload: EscapeRequest) -> dict:
    _check_length(payload.text)
    result = escape(payload.text) if payload.mode == "escape" else unescape(payload.text)
    return {"result": result}
