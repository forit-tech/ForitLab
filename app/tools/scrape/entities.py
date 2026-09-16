"""Поиск повторяющихся сущностей (карточек) на странице.

Списки товаров, статьи, вакансии — это визуально «карточки», а в HTML —
группы соседних элементов с одинаковой структурой. Мы строим лёгкое дерево,
ищем самую крупную группу похожих соседей и вытаскиваем из каждого общие поля
(текст, ссылки, картинки). Это эвристика, а не семантическое понимание: она
опирается на регулярность разметки и на плохо размеченной странице промолчит.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin

VOID_TAGS = {"br", "img", "input", "hr", "meta", "link", "source", "area", "col", "wbr"}
SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "head"}
#: Контейнеры, среди детей которых имеет смысл искать повторы.
CONTAINER_TAGS = {"ul", "ol", "div", "section", "main", "table", "tbody", "article", "nav"}


@dataclass
class Node:
    tag: str
    attrs: dict[str, str]
    parent: "Node | None" = None
    children: list["Node"] = field(default_factory=list)
    text_parts: list[str] = field(default_factory=list)

    @property
    def classes(self) -> tuple[str, ...]:
        return tuple(sorted(self.attrs.get("class", "").split()))

    @property
    def signature(self) -> str:
        """Отпечаток элемента: тег + классы. По нему группируем похожих соседей."""
        cls = ".".join(self.classes)
        return f"{self.tag}.{cls}" if cls else self.tag

    def text(self) -> str:
        chunks = list(self.text_parts)
        for child in self.children:
            chunks.append(child.text())
        return re.sub(r"\s+", " ", " ".join(chunks)).strip()


class TreeParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node(tag="#root", attrs={})
        self._stack = [self.root]
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        node = Node(tag=tag, attrs={k: (v or "") for k, v in attrs}, parent=self._stack[-1])
        self._stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._skip_depth or tag in SKIP_TAGS:
            return
        node = Node(tag=tag, attrs={k: (v or "") for k, v in attrs}, parent=self._stack[-1])
        self._stack[-1].children.append(node)

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth or tag in VOID_TAGS:
            return
        for position in range(len(self._stack) - 1, 0, -1):
            if self._stack[position].tag == tag:
                del self._stack[position:]
                break

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        stripped = data.strip()
        if stripped:
            self._stack[-1].text_parts.append(stripped)


def _collect_fields(node: Node, base_url: str) -> dict[str, object]:
    """Достаёт из карточки типовые поля: заголовок, ссылку, картинку, текст."""
    fields: dict[str, object] = {}

    # Первый заголовок или ссылка — обычно название сущности.
    def walk(current: Node):
        for child in current.children:
            yield child
            yield from walk(child)

    descendants = list(walk(node))

    for child in descendants:
        if child.tag in {"h1", "h2", "h3", "h4", "h5"} and "title" not in fields:
            title = child.text()
            if title:
                fields["title"] = title[:200]
        if child.tag == "a" and child.attrs.get("href"):
            if "link" not in fields:
                fields["link"] = urljoin(base_url, child.attrs["href"])
            if "title" not in fields:
                text = child.text()
                if text:
                    fields["title"] = text[:200]
        if child.tag == "img" and child.attrs.get("src") and "image" not in fields:
            fields["image"] = urljoin(base_url, child.attrs["src"])
            if child.attrs.get("alt") and "alt" not in fields:
                fields["alt"] = child.attrs["alt"][:200]
        if child.tag == "time" and "date" not in fields:
            fields["date"] = (child.attrs.get("datetime") or child.text())[:60]

    text = node.text()
    if text:
        fields["text"] = text[:400]
    return fields


def _score_group(nodes: list[Node]) -> float:
    """Насколько группа похожа на список карточек, а не на случайный повтор."""
    if len(nodes) < 3:
        return 0.0
    texts = [len(node.text()) for node in nodes]
    if not any(texts):
        return 0.0
    avg = sum(texts) / len(texts)
    # Слишком короткие (иконки навигации) и разнобойные группы штрафуем.
    variance = sum((value - avg) ** 2 for value in texts) / len(texts)
    consistency = 1.0 / (1.0 + (variance**0.5) / (avg + 1))
    return len(nodes) * min(avg, 200) / 200 * consistency


def detect_entities(
    html: str,
    base_url: str,
    *,
    max_groups: int = 5,
    max_items: int = 200,
    include_items: bool = False,
) -> list[dict]:
    parser = TreeParser()
    parser.feed(html)
    parser.close()

    candidates: list[tuple[float, Node, list[Node]]] = []

    def visit(node: Node) -> None:
        if node.tag in CONTAINER_TAGS or node.tag == "#root":
            groups: dict[str, list[Node]] = {}
            for child in node.children:
                if child.tag in VOID_TAGS:
                    continue
                groups.setdefault(child.signature, []).append(child)
            for signature, siblings in groups.items():
                score = _score_group(siblings)
                if score > 0:
                    candidates.append((score, node, siblings))
        for child in node.children:
            visit(child)

    visit(parser.root)
    candidates.sort(key=lambda item: item[0], reverse=True)

    results: list[dict] = []
    seen_signatures: set[str] = set()
    for score, container, siblings in candidates:
        signature = siblings[0].signature
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)

        items = [_collect_fields(node, base_url) for node in siblings[:max_items]]
        items = [item for item in items if item.get("text") or item.get("title")]
        if len(items) < 3:
            continue

        # Общие поля — те, что встретились в большинстве карточек.
        field_counts: dict[str, int] = {}
        for item in items:
            for key in item:
                field_counts[key] = field_counts.get(key, 0) + 1
        common = sorted(
            (key for key, count in field_counts.items() if count >= len(items) * 0.5)
        )

        group_result = {
            "signature": signature,
            "container": container.signature,
            "count": len(items),
            "fields": common,
            "confidence": round(min(1.0, score / 20), 2),
            "preview": items[:5],
        }
        if include_items:
            group_result["items"] = items
        results.append(group_result)
        if len(results) >= max_groups:
            break

    return results
