"""Абстракция DOM — приложение знает только ParserDOM, но не lxml.

Backend выбирается один раз: предпочтительно A (lxml + cssselect) — нативные CSS
и XPath, отличная HTML-tolerance. Fallback B (html5lib+cssselect+elementpath)
подключается в этой же точке, если lxml недоступен на реальном хостинге. Пол —
stdlib-backend: строит дерево без внешних зависимостей, но селекторы объявляет
неподдерживаемыми ЯВНО (никакого тихого «ничего не нашёл»).

Смысл абстракции: если Host-0 откажет lxml, меняется только backend здесь, а не
половина Web Parser.
"""

from __future__ import annotations

from typing import Iterator, Protocol


class UnsupportedSelector(Exception):
    """Backend не умеет этот способ выбора (например, stdlib не даёт CSS/XPath)."""


class DomElement(Protocol):
    tag: str

    @property
    def attrs(self) -> dict[str, str]: ...
    @property
    def classes(self) -> tuple[str, ...]: ...
    def get(self, name: str, default: str | None = None) -> str | None: ...
    def text(self) -> str: ...
    def inner_html(self) -> str: ...
    def outer_html(self) -> str: ...
    def children(self) -> list["DomElement"]: ...
    def css(self, selector: str) -> list["DomElement"]: ...
    def xpath(self, selector: str) -> list["DomElement"]: ...
    def xpath_raw(self, selector: str) -> list: ...


# ---------------------------------------------------------------------------
# Backend A: lxml + cssselect
# ---------------------------------------------------------------------------
class _LxmlElement:
    def __init__(self, node) -> None:
        self._n = node

    @property
    def tag(self) -> str:
        return self._n.tag if isinstance(self._n.tag, str) else str(self._n.tag)

    @property
    def attrs(self) -> dict[str, str]:
        return dict(self._n.attrib)

    @property
    def classes(self) -> tuple[str, ...]:
        return tuple(sorted((self._n.get("class") or "").split()))

    def get(self, name: str, default: str | None = None) -> str | None:
        return self._n.get(name, default)

    def text(self) -> str:
        return " ".join(self._n.itertext()).strip()

    def inner_html(self) -> str:
        from lxml import html as _h

        return "".join(_h.tostring(c, encoding="unicode") for c in self._n)

    def outer_html(self) -> str:
        from lxml import html as _h

        return _h.tostring(self._n, encoding="unicode")

    def children(self) -> list[DomElement]:
        return [_LxmlElement(c) for c in self._n if isinstance(c.tag, str)]

    def css(self, selector: str) -> list[DomElement]:
        return [_LxmlElement(n) for n in self._n.cssselect(selector)]

    def xpath(self, selector: str) -> list[DomElement]:
        return [_LxmlElement(n) for n in self._n.xpath(selector) if hasattr(n, "tag") and isinstance(n.tag, str)]

    def xpath_raw(self, selector: str) -> list:
        """Сырые результаты XPath: элементы ИЛИ строки (атрибуты, text())."""
        return list(self._n.xpath(selector))


class LxmlBackend:
    name = "lxml"
    supports_css = True
    supports_xpath = True

    def parse(self, html: str, base_url: str = ""):
        from lxml import html as lxml_html

        root = lxml_html.fromstring(html or "<html></html>")
        if base_url:
            root.make_links_absolute(base_url, resolve_base_href=False)
        return _LxmlDocument(root)


class _LxmlDocument:
    def __init__(self, root) -> None:
        self._root = root
        self.root: DomElement = _LxmlElement(root)

    def css(self, selector: str) -> list[DomElement]:
        return [_LxmlElement(n) for n in self._root.cssselect(selector)]

    def xpath(self, selector: str) -> list[DomElement]:
        out = []
        for n in self._root.xpath(selector):
            if hasattr(n, "tag"):
                out.append(_LxmlElement(n))
        return out


# ---------------------------------------------------------------------------
# Backend floor: stdlib (дерево есть, селекторов нет — честно)
# ---------------------------------------------------------------------------
class _StdlibElement:
    def __init__(self, node) -> None:
        self._n = node  # app.tools.scrape.entities.Node

    @property
    def tag(self) -> str:
        return self._n.tag

    @property
    def attrs(self) -> dict[str, str]:
        return dict(self._n.attrs)

    @property
    def classes(self) -> tuple[str, ...]:
        return self._n.classes

    def get(self, name: str, default: str | None = None) -> str | None:
        return self._n.attrs.get(name, default)

    def text(self) -> str:
        return self._n.text()

    def inner_html(self) -> str:  # stdlib-дерево не хранит исходный HTML
        return ""

    def outer_html(self) -> str:
        return ""

    def children(self) -> list[DomElement]:
        return [_StdlibElement(c) for c in self._n.children]

    def css(self, selector: str) -> list[DomElement]:
        raise UnsupportedSelector("stdlib backend не поддерживает CSS — нужен lxml")

    def xpath(self, selector: str) -> list[DomElement]:
        raise UnsupportedSelector("stdlib backend не поддерживает XPath — нужен lxml")

    def xpath_raw(self, selector: str) -> list:
        raise UnsupportedSelector("stdlib backend не поддерживает XPath — нужен lxml")


class StdlibBackend:
    name = "stdlib"
    supports_css = False
    supports_xpath = False

    def parse(self, html: str, base_url: str = ""):
        # переиспользуем лёгкое дерево из существующего Scrape, ничего не удаляя
        from ..tools.scrape.entities import TreeParser

        tp = TreeParser()
        tp.feed(html or "")
        tp.close()
        return _StdlibDocument(tp.root)


class _StdlibDocument:
    def __init__(self, root) -> None:
        self.root: DomElement = _StdlibElement(root)

    def css(self, selector: str) -> list[DomElement]:
        raise UnsupportedSelector("stdlib backend не поддерживает CSS — нужен lxml или html5lib")

    def xpath(self, selector: str) -> list[DomElement]:
        raise UnsupportedSelector("stdlib backend не поддерживает XPath — нужен lxml или elementpath")


# ---------------------------------------------------------------------------
# Выбор backend (единственная точка, где решается A/B/floor)
# ---------------------------------------------------------------------------
_BACKEND = None


def _detect_backend():
    try:
        import lxml  # noqa: F401
        import cssselect  # noqa: F401

        return LxmlBackend()
    except Exception:
        # сюда позже встанет fallback B (html5lib+cssselect+elementpath),
        # когда/если решим не тянуть lxml. Пока пол — stdlib.
        return StdlibBackend()


def get_backend(prefer: str | None = None):
    """Возвращает активный backend. prefer='stdlib' форсит пол (для тестов)."""
    global _BACKEND
    if prefer == "stdlib":
        return StdlibBackend()
    if prefer == "lxml":
        return LxmlBackend()
    if _BACKEND is None:
        _BACKEND = _detect_backend()
    return _BACKEND


def backend_info() -> dict:
    b = get_backend()
    return {"backend": b.name, "css": b.supports_css, "xpath": b.supports_xpath}


def parse(html: str, base_url: str = "", *, prefer: str | None = None):
    """Разобрать HTML в DOM выбранного backend. Скрипты не исполняются."""
    return get_backend(prefer).parse(html, base_url)
