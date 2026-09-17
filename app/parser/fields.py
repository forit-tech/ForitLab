"""Предложение полей из образца карточки. Пользователь потом правит/подтверждает."""

from __future__ import annotations

from .dom import DomElement
from .models import FieldSource, FieldSpec, SelectorType, Transform

_HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")


def _has(container: DomElement, selector: str) -> bool:
    try:
        return bool(container.css(selector))
    except Exception:  # noqa: BLE001
        return False


def propose_fields(container: DomElement) -> list[FieldSpec]:
    """Эвристика: title / link / image / price / text — как первые кандидаты."""
    fields: list[FieldSpec] = []

    for tag in _HEADINGS:
        if _has(container, tag):
            fields.append(FieldSpec(name="title", selector=tag, source=FieldSource.TEXT, transform=Transform.NORMALIZE_WS))
            break
    else:
        if _has(container, "a"):
            fields.append(FieldSpec(name="title", selector="a", source=FieldSource.TEXT, transform=Transform.NORMALIZE_WS))

    if _has(container, "a[href]"):
        fields.append(FieldSpec(name="link", selector="a", source=FieldSource.URL))
    if _has(container, "img"):
        fields.append(FieldSpec(name="image", selector="img", source=FieldSource.IMAGE))
    if _has(container, "[class*=price]"):
        fields.append(FieldSpec(name="price", selector="[class*=price]", source=FieldSource.TEXT, transform=Transform.NUMBER))

    if not fields:
        fields.append(FieldSpec(name="text", selector="", source=FieldSource.TEXT, transform=Transform.NORMALIZE_WS))
    return fields
