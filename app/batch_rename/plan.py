"""Построение RENAME PLAN для всего набора имён.

План — обычный dict (легко сериализуется в JSON для preview на фронте):

    {
      "items": [
        {"old_name", "new_name", "changed": bool, "errors": [str, ...]},
        ...
      ],
      "conflicts": [ {...}, ... ],
      "valid": bool,
      "summary": {"total", "changed", "conflicts", "errors"},
    }

Порядок построения: применяем правила по порядку → валидируем каждое имя →
ищем конфликты. Только план с ``valid == True`` можно применять.
"""

from __future__ import annotations

from typing import Any

from .rules import apply_rules
from .validate import find_conflicts, validate_name


def build_plan(names: list[str], rules: list[dict[str, Any]]) -> dict[str, Any]:
    """Собрать план ``old -> new`` для набора имён с заданными правилами."""
    items: list[dict[str, Any]] = []
    total = len(names)

    for index, old_name in enumerate(names):
        new_name, rule_errors = apply_rules(old_name, rules, index=index, total=total)
        errors = list(rule_errors)
        errors.extend(validate_name(new_name))
        items.append(
            {
                "old_name": old_name,
                "new_name": new_name,
                "changed": new_name != old_name,
                "errors": errors,
            }
        )

    conflicts = find_conflicts(items)

    changed = sum(1 for item in items if item["changed"])
    error_count = sum(len(item["errors"]) for item in items)
    valid = error_count == 0 and not conflicts

    return {
        "items": items,
        "conflicts": conflicts,
        "valid": valid,
        "summary": {
            "total": total,
            "changed": changed,
            "conflicts": len(conflicts),
            "errors": error_count,
        },
    }
