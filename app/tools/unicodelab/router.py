"""HTTP-слой Unicode Crime Lab."""

from __future__ import annotations

import unicodedata

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from ...config import settings
from ...errors import PayloadTooLargeError
from . import TOOL_TITLE
from .analyzer import analyze, clean

router = APIRouter(prefix="/api/unicode", tags=[TOOL_TITLE])


class InspectRequest(BaseModel):
    text: str = Field(description="Строка, которую нужно вскрыть")


class CompareRequest(BaseModel):
    left: str
    right: str


class NormalizeRequest(BaseModel):
    text: str
    form: str = Field(default="NFC", pattern="^(NFC|NFD|NFKC|NFKD)$")


class SampleString(BaseModel):
    id: str
    text: str
    looks_like: str
    problem: str


SAMPLES = [
    SampleString(
        id="homoglyph",
        text="Аpple",  # А кириллическая
        looks_like="Apple",
        problem="Первая буква — кириллическая А (U+0410), а не латинская A.",
    ),
    SampleString(
        id="zero_width",
        text="admin​",
        looks_like="admin",
        problem="В конце zero-width space: логин не совпадёт с эталоном.",
    ),
    SampleString(
        id="nbsp",
        text="1 234,56",
        looks_like="1 234,56",
        problem="Неразрывный пробел вместо обычного — число не распарсится.",
    ),
    SampleString(
        id="nfd",
        text="й",  # и + комбинирующая краткая = й в форме NFD
        looks_like="й",
        problem="Записано в NFD: две кодовые точки вместо одной.",
    ),
    SampleString(
        id="bidi",
        text="file‮gnp.exe",
        looks_like="fileexe.png",
        problem="RIGHT-TO-LEFT OVERRIDE переворачивает отображение имени файла.",
    ),
    SampleString(
        id="soft_hyphen",
        text="про­верка",
        looks_like="проверка",
        problem="Мягкий перенос невидим, но ломает точное сравнение.",
    ),
    SampleString(
        id="mojibake",
        text="Ð¿ÑÐ¸Ð²ÐµÑ",
        looks_like="привет",
        problem="UTF-8, прочитанный как cp1252 — классические кракозябры.",
    ),
]


def _check_length(text: str) -> None:
    if len(text) > settings.unicode_max_chars:
        raise PayloadTooLargeError(
            f"Максимум {settings.unicode_max_chars} символов за раз",
            {"received": len(text), "limit": settings.unicode_max_chars},
        )


@router.get("/samples", response_model=list[SampleString], summary="Строки-ловушки для проверки")
async def samples() -> list[SampleString]:
    return SAMPLES


@router.post("/inspect", summary="Разобрать строку по символам")
async def inspect(payload: InspectRequest) -> dict:
    _check_length(payload.text)
    return analyze(payload.text)


@router.get("/inspect", summary="То же, но строка в query — удобно для curl")
async def inspect_query(
    text: str = Query(description="Строка для разбора"),
) -> dict:
    _check_length(text)
    return analyze(text)


@router.post("/normalize", summary="Привести строку к выбранной форме нормализации")
async def normalize(payload: NormalizeRequest) -> dict:
    _check_length(payload.text)
    normalized = unicodedata.normalize(payload.form, payload.text)
    return {
        "form": payload.form,
        "changed": normalized != payload.text,
        "before": {"text": payload.text, "length": len(payload.text)},
        "after": {"text": normalized, "length": len(normalized)},
        "cleaned": clean(payload.text),
    }


@router.post("/compare", summary="Почему две одинаковые на вид строки не равны")
async def compare(payload: CompareRequest) -> dict:
    _check_length(payload.left)
    _check_length(payload.right)

    left, right = payload.left, payload.right
    nfc_equal = unicodedata.normalize("NFC", left) == unicodedata.normalize("NFC", right)
    cleaned_equal = clean(left) == clean(right)

    differences = []
    for index in range(max(len(left), len(right))):
        left_char = left[index] if index < len(left) else None
        right_char = right[index] if index < len(right) else None
        if left_char != right_char:
            differences.append(
                {
                    "index": index,
                    "left": f"U+{ord(left_char):04X}" if left_char else None,
                    "right": f"U+{ord(right_char):04X}" if right_char else None,
                    "left_char": left_char,
                    "right_char": right_char,
                }
            )
        if len(differences) >= 50:
            break

    if left == right:
        verdict = "Строки полностью идентичны."
    elif nfc_equal:
        verdict = "Строки различаются только формой нормализации: после NFC они равны."
    elif cleaned_equal:
        verdict = "Строки равны после очистки от невидимых символов и экзотических пробелов."
    else:
        verdict = "Строки действительно разные — дело не в невидимых символах."

    return {
        "equal": left == right,
        "equal_after_nfc": nfc_equal,
        "equal_after_cleaning": cleaned_equal,
        "verdict": verdict,
        "first_difference_at": differences[0]["index"] if differences else None,
        "differences": differences,
        "left": analyze(left),
        "right": analyze(right),
    }
