"""Операции над ОДНИМ именем файла.

Каждая операция описывается как ``rule = {"operation": str, "params": {...}}``.
Правила применяются В ПОРЯДКЕ, в котором их задал пользователь.

Расширение (последний ``.ext``) по умолчанию сохраняется: операция меняет только
basename, после чего расширение приклеивается обратно. Для MVP расширение мы
никогда не трогаем — даже case-операции его не меняют.
"""

from __future__ import annotations

import re
from typing import Any


class RuleError(Exception):
    """Правило нельзя применить (кривой regex, неизвестная операция и т.п.).

    Ошибку не глотаем молча: ``apply_rules`` её ловит и складывает текст в
    список ошибок конкретного элемента плана, не роняя весь процесс.
    """


#: Все поддерживаемые операции. Держим списком, чтобы валидатор правил и UI
#: могли сверяться с одним источником правды.
OPERATIONS = (
    "prefix",
    "suffix",
    "replace",
    "regex_replace",
    "lowercase",
    "uppercase",
    "title",
    "numbering",
)


def split_ext(name: str) -> tuple[str, str]:
    """Разбить имя на (basename, ext), где ext — последний ``.suffix`` с точкой.

    Логика повторяет ``os.path.splitext``: у dotfiles (``.gitignore``) и у имён
    без точки расширения нет. ``file.tar.gz`` → (``file.tar``, ``.gz``).
    """
    dot = name.rfind(".")
    # Точки нет вовсе, либо она ведущая (dotfile без расширения).
    if dot <= 0:
        return name, ""
    return name[:dot], name[dot:]


def _params(rule: dict[str, Any]) -> dict[str, Any]:
    params = rule.get("params")
    return params if isinstance(params, dict) else {}


def apply_rule(name: str, rule: dict[str, Any], index: int = 0, total: int = 1) -> str:
    """Применить одно правило к имени и вернуть новое имя.

    ``index`` / ``total`` нужны операции ``numbering`` (позиция в наборе).
    Бросает :class:`RuleError`, если правило некорректно.
    """
    operation = rule.get("operation")
    if operation not in OPERATIONS:
        raise RuleError(f"Неизвестная операция: {operation!r}")

    params = _params(rule)
    base, ext = split_ext(name)

    if operation == "prefix":
        base = f"{params.get('text', '')}{base}"
    elif operation == "suffix":
        base = f"{base}{params.get('text', '')}"
    elif operation == "replace":
        find = params.get("find", "")
        replacement = params.get("replace", "")
        if find:
            base = base.replace(find, replacement)
    elif operation == "regex_replace":
        pattern = params.get("pattern", "")
        replacement = params.get("replacement", "")
        try:
            compiled = re.compile(pattern)
            base = compiled.sub(replacement, base)
        except re.error as exc:
            raise RuleError(f"Некорректный regex {pattern!r}: {exc}") from exc
    elif operation == "lowercase":
        base = base.lower()
    elif operation == "uppercase":
        base = base.upper()
    elif operation == "title":
        base = base.title()
    elif operation == "numbering":
        base = _apply_numbering(base, params, index)

    return f"{base}{ext}"


def _apply_numbering(base: str, params: dict[str, Any], index: int) -> str:
    """Добавить порядковый номер к basename с учётом позиции в наборе."""
    try:
        start = int(params.get("start", 1))
        step = int(params.get("step", 1))
        padding = int(params.get("padding", 0))
    except (TypeError, ValueError) as exc:
        raise RuleError(f"Некорректные параметры нумерации: {exc}") from exc

    if padding < 0:
        raise RuleError("padding не может быть отрицательным")

    position = params.get("position", "prefix")
    if position not in ("prefix", "suffix"):
        raise RuleError(f"Некорректная позиция нумерации: {position!r}")

    number = start + index * step
    token = str(number)
    if number >= 0:
        token = token.zfill(padding)
    else:
        # Отрицательные номера паддим по модулю, сохраняя знак впереди.
        token = "-" + str(-number).zfill(max(padding - 1, 0))

    if position == "prefix":
        return f"{token}_{base}"
    return f"{base}_{token}"


def apply_rules(
    name: str,
    rules: list[dict[str, Any]],
    index: int = 0,
    total: int = 1,
) -> tuple[str, list[str]]:
    """Применить цепочку правил по порядку.

    Возвращает ``(new_name, errors)``. Правило, бросившее :class:`RuleError`,
    пропускается: его текст ошибки попадает в ``errors``, а имя остаётся тем,
    что было до сбойного правила — процесс не падает.
    """
    current = name
    errors: list[str] = []
    for rule in rules or []:
        try:
            current = apply_rule(current, rule, index=index, total=total)
        except RuleError as exc:
            errors.append(str(exc))
    return current, errors
