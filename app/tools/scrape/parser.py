"""Разбор HTML на стандартной библиотеке.

`html.parser` вместо BeautifulSoup — по той же причине, по которой здесь нет
pandas: лишние мегабайты на бесплатном хостинге. Для таблиц, ссылок, форм и
JSON-LD его возможностей хватает с запасом.

Ключевая деталь реализации — стек захвата текста. Теги вкладываются друг в
друга (`<td><a>Россия</a></td>`), и один общий буфер тут не работает: текст
ссылки просто затирает текст ячейки. Поэтому каждый захват живёт в своём
кадре, а при закрытии отдаёт накопленное родителю.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

#: Теги, содержимое которых не является текстом страницы.
INVISIBLE_TAGS = {"style", "noscript", "template", "svg"}
VOID_TAGS = {"br", "img", "input", "hr", "meta", "link", "source", "area", "col"}
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
#: Теги, которые сами по себе не являются разделителем слов.
INLINE_TAGS = {"a", "b", "i", "em", "strong", "span", "code", "small", "sup", "sub"}


@dataclass
class Table:
    index: int
    caption: str | None
    headers: list[str]
    rows: list[list[str]]

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def as_dict(self, preview_rows: int = 5) -> dict[str, object]:
        return {
            "index": self.index,
            "caption": self.caption,
            "headers": self.headers,
            "columns": len(self.headers) or (len(self.rows[0]) if self.rows else 0),
            "rows": self.row_count,
            "preview": self.rows[:preview_rows],
            "download": f"/api/scrape/extract?target=tables&index={self.index}",
        }


@dataclass
class Link:
    text: str
    href: str
    rel: str | None
    internal: bool


@dataclass
class Image:
    src: str
    alt: str | None
    title: str | None


@dataclass
class FormField:
    name: str | None
    type: str
    required: bool


@dataclass
class Form:
    action: str
    method: str
    fields: list[FormField] = field(default_factory=list)


class PageParser(HTMLParser):
    """Однопроходный сборщик всего интересного со страницы."""

    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.base_host = urlparse(base_url).netloc

        self.title: str | None = None
        self.meta: dict[str, str] = {}
        self.links: list[Link] = []
        self.images: list[Image] = []
        self.headings: list[dict[str, str]] = []
        self.tables: list[Table] = []
        self.forms: list[Form] = []
        self.jsonld: list[object] = []
        self.feeds: list[dict[str, str]] = []
        self.alternate_json: list[dict[str, str]] = []
        self.scripts: list[str] = []
        self.lang: str | None = None
        self.canonical: str | None = None
        self.text_parts: list[str] = []

        #: Стек захвата: [(вид, буфер, данные)].
        self._captures: list[tuple[str, list[str], dict]] = []
        #: Глубина вложенности в style/svg: там текста страницы нет, но эти
        #: теги встречаются внутри ячеек — и CSS утекает в заголовки колонок.
        self._invisible_depth = 0
        self._table_stack: list[dict] = []

    # --- работа со стеком захвата ----------------------------------------

    def _push(self, kind: str, **data: object) -> None:
        self._captures.append((kind, [], dict(data)))

    def _pop(self, kind: str) -> tuple[str, dict] | None:
        """Снимает верхний кадр нужного вида и отдаёт родителю его текст."""
        for position in range(len(self._captures) - 1, -1, -1):
            if self._captures[position][0] == kind:
                _, buffer, data = self._captures[position]
                del self._captures[position:]
                text = re.sub(r"\s+", " ", "".join(buffer)).strip()
                if self._captures and kind in INLINE_TAGS:
                    # Текст вложенного элемента принадлежит и родителю тоже.
                    self._captures[-1][1].append(" " + text + " ")
                return text, data
        return None

    @property
    def _capturing(self) -> str | None:
        return self._captures[-1][0] if self._captures else None

    def _absolute(self, url: str) -> str:
        try:
            return urljoin(self.base_url, url.strip())
        except ValueError:
            return url

    # --- обработчики ------------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): (value or "") for key, value in attrs}
        if tag in INVISIBLE_TAGS:
            self._invisible_depth += 1
            return

        if tag == "html":
            self.lang = attributes.get("lang") or self.lang
        elif tag == "title":
            self._push("title")
        elif tag == "meta":
            name = attributes.get("name") or attributes.get("property")
            content = attributes.get("content")
            if name and content:
                self.meta[name.lower()] = content
        elif tag == "link":
            self._handle_link_tag(attributes)
        elif tag == "a" and attributes.get("href"):
            href = self._absolute(attributes["href"])
            self._push("a", href=href, rel=attributes.get("rel") or None)
        elif tag == "img" and attributes.get("src"):
            self.images.append(
                Image(
                    src=self._absolute(attributes["src"]),
                    alt=attributes.get("alt"),
                    title=attributes.get("title") or None,
                )
            )
        elif tag in HEADING_TAGS:
            self._push("heading", level=tag)
        elif tag == "table":
            self._table_stack.append({"caption": None, "headers": [], "rows": [], "row": None})
        elif tag == "caption" and self._table_stack:
            self._push("caption")
        elif tag == "tr" and self._table_stack:
            self._table_stack[-1]["row"] = []
        elif tag in {"td", "th"} and self._table_stack:
            self._push("cell", is_header=tag == "th")
        elif tag == "form":
            self.forms.append(
                Form(
                    action=self._absolute(attributes.get("action", "")),
                    method=(attributes.get("method") or "get").lower(),
                )
            )
        elif tag in {"input", "select", "textarea"} and self.forms:
            self.forms[-1].fields.append(
                FormField(
                    name=attributes.get("name") or None,
                    type=attributes.get("type") or tag,
                    required="required" in attributes,
                )
            )
        elif tag == "script":
            script_type = (attributes.get("type") or "").lower()
            self._push("jsonld" if script_type == "application/ld+json" else "script")

    def _handle_link_tag(self, attributes: dict[str, str]) -> None:
        rel = (attributes.get("rel") or "").lower()
        href = attributes.get("href")
        link_type = (attributes.get("type") or "").lower()
        if not href:
            return
        absolute = self._absolute(href)

        if "canonical" in rel:
            self.canonical = absolute
        elif "alternate" in rel and ("rss" in link_type or "atom" in link_type):
            self.feeds.append(
                {"url": absolute, "type": link_type, "title": attributes.get("title", "")}
            )
        elif "alternate" in rel and "json" in link_type:
            self.alternate_json.append({"url": absolute, "type": link_type})

    def handle_endtag(self, tag: str) -> None:
        if tag in INVISIBLE_TAGS:
            self._invisible_depth = max(0, self._invisible_depth - 1)
            return

        if tag == "title":
            popped = self._pop("title")
            if popped:
                self.title = popped[0]
        elif tag == "a":
            popped = self._pop("a")
            if popped:
                text, data = popped
                href = str(data["href"])
                self.links.append(
                    Link(
                        text=text[:200],
                        href=href,
                        rel=data.get("rel"),  # type: ignore[arg-type]
                        internal=urlparse(href).netloc == self.base_host,
                    )
                )
        elif tag in HEADING_TAGS:
            popped = self._pop("heading")
            if popped and popped[0]:
                self.headings.append({"level": str(popped[1]["level"]), "text": popped[0][:300]})
        elif tag == "caption" and self._table_stack:
            popped = self._pop("caption")
            if popped:
                self._table_stack[-1]["caption"] = popped[0][:200]
        elif tag in {"td", "th"} and self._table_stack:
            popped = self._pop("cell")
            if popped:
                text, data = popped
                table = self._table_stack[-1]
                if table.get("row") is None:
                    table["row"] = []
                table["row"].append(text)
                if data.get("is_header"):
                    table.setdefault("header_cells", []).append(text)
        elif tag == "tr" and self._table_stack:
            self._finish_row()
        elif tag == "table" and self._table_stack:
            self._finish_table()
        elif tag == "script":
            for kind in ("jsonld", "script"):
                popped = self._pop(kind)
                if popped is None:
                    continue
                content = popped[0]
                if kind == "jsonld" and content:
                    try:
                        self.jsonld.append(json.loads(content))
                    except json.JSONDecodeError:
                        pass
                elif content:
                    self.scripts.append(content[:20000])
                break

    def _finish_row(self) -> None:
        table = self._table_stack[-1]
        row = table.get("row")
        header_cells = table.pop("header_cells", None)
        if row:
            # Строка целиком из <th> — это шапка, а не данные.
            if header_cells and len(header_cells) == len(row) and not table["headers"]:
                table["headers"] = row
            else:
                table["rows"].append(row)
        table["row"] = None

    def _finish_table(self) -> None:
        raw = self._table_stack.pop()
        rows = raw["rows"]
        headers = raw["headers"]

        if not headers and rows:
            # Шапки из <th> не было — берём первую строку, если она похожа на заголовки.
            first = rows[0]
            if all(cell and not cell.replace(".", "", 1).isdigit() for cell in first):
                headers, rows = first, rows[1:]

        width = max((len(row) for row in rows), default=len(headers))
        headers = [header or f"column_{i + 1}" for i, header in enumerate(headers)]
        # Шапка уже одной ширины со строками — дополняем её, а не обрезаем данные.
        headers += [f"column_{i + 1}" for i in range(len(headers), width)]

        if headers or rows:
            self.tables.append(
                Table(index=len(self.tables), caption=raw["caption"], headers=headers, rows=rows)
            )

    def handle_data(self, data: str) -> None:
        if self._invisible_depth:
            return
        if self._captures:
            self._captures[-1][1].append(data)
            return
        stripped = data.strip()
        if stripped:
            self.text_parts.append(stripped)

    # --- результат --------------------------------------------------------

    def page_text(self, limit: int = 20000) -> str:
        return re.sub(r"\s+", " ", " ".join(self.text_parts))[:limit]


def parse(html: str, base_url: str) -> PageParser:
    parser = PageParser(base_url)
    parser.feed(html)
    parser.close()
    return parser
