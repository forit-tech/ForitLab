"""Детектор повторяющихся сущностей Web Harvester (офлайн, на фикстурах)."""

from __future__ import annotations

from app.tools.scrape.entities import detect_entities

CARDS = """
<html><body>
<main>
  <div class="product">
    <h3>Товар 1</h3><a href="/p/1">Купить</a><span>100 руб</span>
  </div>
  <div class="product">
    <h3>Товар 2</h3><a href="/p/2">Купить</a><span>200 руб</span>
  </div>
  <div class="product">
    <h3>Товар 3</h3><a href="/p/3">Купить</a><span>300 руб</span>
  </div>
  <div class="product">
    <h3>Товар 4</h3><a href="/p/4">Купить</a><span>400 руб</span>
  </div>
</main>
</body></html>
"""

NO_STRUCTURE = """
<html><body>
<h1>Заголовок</h1>
<p>Просто один абзац текста без всякой повторяющейся структуры.</p>
<footer>Контакты</footer>
</body></html>
"""

LIST_ITEMS = """
<html><body><ul>
<li><a href="/a">Первая статья про данные</a></li>
<li><a href="/b">Вторая статья про пайплайны</a></li>
<li><a href="/c">Третья статья про дрейф</a></li>
<li><a href="/d">Четвёртая статья про метрики</a></li>
</ul></body></html>
"""


def test_detects_repeated_cards() -> None:
    groups = detect_entities(CARDS, "https://shop.example")
    assert groups
    top = groups[0]
    assert top["count"] == 4
    assert "title" in top["fields"]
    assert "link" in top["fields"]


def test_card_links_are_absolute() -> None:
    groups = detect_entities(CARDS, "https://shop.example")
    first_item = groups[0]["preview"][0]
    assert first_item["link"].startswith("https://shop.example/")


def test_titles_extracted() -> None:
    groups = detect_entities(CARDS, "https://shop.example")
    titles = {item["title"] for item in groups[0]["preview"]}
    assert "Товар 1" in titles


def test_no_structure_yields_nothing() -> None:
    assert detect_entities(NO_STRUCTURE, "https://example.com") == []


def test_list_items_detected() -> None:
    groups = detect_entities(LIST_ITEMS, "https://blog.example")
    assert groups
    assert groups[0]["count"] == 4


def test_include_items_returns_full_set() -> None:
    groups = detect_entities(CARDS, "https://shop.example", include_items=True)
    assert "items" in groups[0]
    assert len(groups[0]["items"]) == 4


def test_confidence_is_bounded() -> None:
    for group in detect_entities(CARDS, "https://shop.example"):
        assert 0.0 <= group["confidence"] <= 1.0
