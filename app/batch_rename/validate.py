"""Проверки финальных имён ДО применения плана.

Всё, что здесь, работает над уже посчитанными new_name. Функции наполняют
``item["errors"]`` и список конфликтов. Пока валидация не прошла — план не
применяется.
"""

from __future__ import annotations

from typing import Any

#: Windows запрещает эти символы в именах файлов.
_RESERVED_CHARS = set('<>:"/\\|?*')

#: Зарезервированные Windows-имена (сравнение без учёта регистра, по basename).
_RESERVED_WINDOWS = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)

#: Максимальная длина имени файла (типичный лимит FS).
_MAX_LENGTH = 255


def validate_name(name: str) -> list[str]:
    """Проверить одно финальное имя. Возвращает список текстов ошибок."""
    errors: list[str] = []

    if not name or not name.strip():
        errors.append("Пустое финальное имя")
        # Дальше проверять нечего — остальные проверки только зашумят вывод.
        return errors

    if name in (".", ".."):
        errors.append(f"Недопустимое имя {name!r} (текущая/родительская папка)")

    if "/" in name or "\\" in name:
        errors.append("Имя содержит разделитель пути (/ или \\) — path traversal")

    bad_chars = sorted({ch for ch in name if ch in _RESERVED_CHARS})
    if bad_chars:
        shown = " ".join(bad_chars)
        errors.append(f"Запрещённые символы: {shown}")

    control = [ch for ch in name if ord(ch) < 32 or ord(ch) == 127]
    if control:
        errors.append("Имя содержит управляющие символы")

    stem = name.split(".", 1)[0]
    if stem.upper() in _RESERVED_WINDOWS:
        errors.append(f"Зарезервированное Windows-имя: {stem}")

    if len(name) > _MAX_LENGTH:
        errors.append(f"Слишком длинное имя ({len(name)} > {_MAX_LENGTH})")

    if name != name.rstrip(" ."):
        errors.append("Имя оканчивается пробелом или точкой")

    return errors


def find_conflicts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Найти столкновения финальных имён и пометить участников ошибками.

    Учитывает case-folding: ``Report.txt`` и ``report.txt`` считаются
    конфликтом (collision after case-folding), потому что на многих ФС
    (Windows/macOS) регистр не различается.

    Возвращает список конфликтов: ``{"name", "old_names", "case_insensitive"}``.
    Дополнительно проставляет каждому участнику ошибку в ``item["errors"]``.
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        key = str(item.get("new_name", "")).casefold()
        groups.setdefault(key, []).append(item)

    conflicts: list[dict[str, Any]] = []
    for members in groups.values():
        if len(members) < 2:
            continue
        raw_names = {str(m.get("new_name", "")) for m in members}
        case_only = len(raw_names) > 1
        display = members[0].get("new_name", "")
        for member in members:
            note = (
                "Конфликт имён после приведения регистра"
                if case_only
                else "Дубль финального имени"
            )
            member.setdefault("errors", []).append(f"{note}: {display}")
        conflicts.append(
            {
                "name": display,
                "old_names": [m.get("old_name") for m in members],
                "case_insensitive": case_only,
            }
        )
    return conflicts
