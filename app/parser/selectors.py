"""Выполнение и валидация селекторов над ParserDOM. Ошибки — явные.

CSS и XPath — равноправные способы адресации (backend A: lxml + cssselect).
Ни одного тихого «ничего не нашлось» из-за кривого селектора: некорректный или
неподдерживаемый селектор → InvalidSelector с понятным сообщением.
"""

from __future__ import annotations

from ..errors import AppError
from .dom import DomElement, UnsupportedSelector
from .models import SelectorType


class InvalidSelector(AppError):
    status_code = 400
    code = "invalid_selector"


def validate(selector: str, selector_type: SelectorType) -> None:
    """Проверяет, что селектор компилируется. Бросает InvalidSelector."""
    if not selector or not selector.strip():
        raise InvalidSelector("Пустой селектор")
    if selector_type == SelectorType.CSS:
        try:
            from cssselect import HTMLTranslator
            from cssselect.parser import parse as css_parse

            css_parse(selector)
            HTMLTranslator().css_to_xpath(selector)
        except UnsupportedSelector:
            raise
        except Exception as exc:  # noqa: BLE001 — сюда падают SelectorError/SyntaxError cssselect
            raise InvalidSelector(f"Некорректный CSS-селектор: {exc}") from exc
    elif selector_type == SelectorType.XPATH:
        try:
            from lxml import etree

            etree.XPath(selector)
        except Exception as exc:  # noqa: BLE001
            raise InvalidSelector(f"Некорректный XPath: {exc}") from exc
    else:  # pragma: no cover - защита от нового enum
        raise InvalidSelector(f"Неизвестный тип селектора: {selector_type}")


def query(scope: DomElement, selector: str, selector_type: SelectorType) -> list[DomElement]:
    """Выполняет селектор относительно элемента/документа. Ошибки — явные."""
    try:
        if selector_type == SelectorType.CSS:
            return scope.css(selector)
        if selector_type == SelectorType.XPATH:
            return scope.xpath(selector)
    except UnsupportedSelector:
        raise
    except Exception as exc:  # noqa: BLE001
        raise InvalidSelector(f"Селектор не выполнился: {exc}") from exc
    raise InvalidSelector(f"Неизвестный тип селектора: {selector_type}")


def query_first(scope: DomElement, selector: str, selector_type: SelectorType) -> DomElement | None:
    matches = query(scope, selector, selector_type)
    return matches[0] if matches else None
