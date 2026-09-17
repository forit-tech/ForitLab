"""Трансформы значений полей. Ошибки — явные, не тихие."""

from __future__ import annotations

import re

from ..errors import AppError
from .models import Transform


class InvalidTransform(AppError):
    status_code = 400
    code = "invalid_transform"


_WS = re.compile(r"\s+")
_NUM = re.compile(r"-?\d[\d\s.,]*")
_DATE_PATTERNS = (
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), lambda m: f"{m[1]}-{m[2]}-{m[3]}"),
    (re.compile(r"\b(\d{2})[./](\d{2})[./](\d{4})\b"), lambda m: f"{m[3]}-{m[2]}-{m[1]}"),
)


def validate(transform: Transform | None, arg: str | None) -> None:
    if transform == Transform.REGEX:
        if not arg:
            raise InvalidTransform("Для трансформа regex нужен паттерн (transform_arg)")
        try:
            re.compile(arg)
        except re.error as exc:
            raise InvalidTransform(f"Некорректный regex: {exc}") from exc


def apply(value: str, transform: Transform | None, arg: str | None) -> str:
    if value is None:
        return ""
    if transform is None:
        return value
    if transform == Transform.TRIM:
        return value.strip()
    if transform == Transform.NORMALIZE_WS:
        return _WS.sub(" ", value).strip()
    if transform == Transform.REGEX:
        m = re.search(arg or "", value)
        if not m:
            return ""
        return m.group(1) if m.groups() else m.group(0)
    if transform == Transform.NUMBER:
        m = _NUM.search(value)
        if not m:
            return ""
        raw = m.group(0).strip().replace(" ", "").replace(" ", "")
        # 1 234,56 -> 1234.56 ; 1,234.56 -> 1234.56
        if "," in raw and "." in raw:
            raw = raw.replace(",", "") if raw.rfind(".") > raw.rfind(",") else raw.replace(".", "").replace(",", ".")
        elif "," in raw:
            raw = raw.replace(",", ".")
        return raw
    if transform == Transform.DATE:
        for pattern, fmt in _DATE_PATTERNS:
            m = pattern.search(value)
            if m:
                return fmt(m)
        return value.strip()
    return value
