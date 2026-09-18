"""Batch Rename — построение и применение плана массового переименования файлов.

Ключевой принцип пакета: сначала строится RENAME PLAN (old → new), он
валидируется, и только потом применяется. Применение в вебе честное — браузер
не может безопасно переименовать локальные файлы, поэтому apply отдаёт ZIP с
уже новыми именами. Оригиналы на компьютере пользователя не меняются.

Вся доменная логика — на голой stdlib.
"""

from __future__ import annotations

from .archive import build_zip
from .plan import build_plan
from .rules import apply_rule, apply_rules
from .validate import find_conflicts, validate_name

TOOL_TITLE = "Batch Rename"

__all__ = [
    "TOOL_TITLE",
    "apply_rule",
    "apply_rules",
    "build_plan",
    "build_zip",
    "find_conflicts",
    "validate_name",
]
