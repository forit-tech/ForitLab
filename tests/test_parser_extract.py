"""Web Parser 1b: source recommendation, CSS/XPath extraction, transforms,
валидация, export, asset manifest, sanitize, отсутствие утечки секретов. Офлайн."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.parser import extract, sources
from app.parser.models import (
    ExtractionSchema,
    FieldSource,
    FieldSpec,
    SelectorType,
    SourceKind,
    Transform,
)
from app.parser.sanitize import sanitize_html
from app.parser.selectors import InvalidSelector, validate
from app.parser.transforms import InvalidTransform
from app.parser import transforms as tr


def _catalog(n: int = 6) -> str:
    cards = "".join(
        f'<div class="product" data-id="{i}"><a href="/p/{i}"><h3> Товар {i} </h3></a>'
        f'<span class="price">{i} 990 ₽</span><img src="/img/{i}.jpg"></div>'
        for i in range(1, n + 1)
    )
    return f'<html><body><div class="catalog">{cards}</div></body></html>'


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


# ---------- source recommendation ----------
def test_recommendation_picks_repeated_dom_with_evidence() -> None:
    rec = sources.analyze(_catalog(6), "https://shop.example/")
    assert rec.selected is not None
    assert rec.selected.kind == SourceKind.REPEATED_DOM
    assert rec.selected.record_count == 6
    assert rec.selected.stable_ids is True
    assert rec.selected.confidence.value == "high"
    assert rec.selected.evidence  # доказательства присутствуют
    assert rec.selected.schema is not None  # предложенная схема


def test_recommendation_prefers_countable_over_api() -> None:
    html = _catalog(6).replace("</body>", '<script>var x="/api/v1/products.json"</script></body>')
    rec = sources.analyze(html, "https://shop.example/")
    # API-кандидат присутствует как альтернатива, но не выбран (record_count неизвестен)
    kinds = [a.kind.value for a in rec.alternatives]
    assert rec.selected.kind == SourceKind.REPEATED_DOM
    api = [a for a in rec.alternatives if a.kind == SourceKind.API]
    if api:
        assert api[0].record_count is None
        assert api[0].limitations  # честное ограничение


def test_json_ld_source_counted() -> None:
    ld = json.dumps([{"@type": "Product", "name": "A", "sku": "1"}, {"@type": "Product", "name": "B", "sku": "2"}, {"@type": "Product", "name": "C", "sku": "3"}])
    html = f'<html><head><script type="application/ld+json">{ld}</script></head><body></body></html>'
    rec = sources.analyze(html, "")
    assert rec.selected.kind == SourceKind.JSON_LD
    assert rec.selected.record_count == 3


# ---------- CSS + XPath extraction ----------
def test_extract_css_and_xpath_and_types() -> None:
    schema = ExtractionSchema(
        source_kind=SourceKind.REPEATED_DOM,
        container_selector="div.product",
        fields=[
            FieldSpec(name="title", selector=".//h3", selector_type=SelectorType.XPATH, source=FieldSource.TEXT, transform=Transform.NORMALIZE_WS),
            FieldSpec(name="price", selector="span[class*=price]", source=FieldSource.TEXT, transform=Transform.NUMBER),
            FieldSpec(name="sku", selector="@data-id", selector_type=SelectorType.XPATH, source=FieldSource.TEXT),
            FieldSpec(name="link", selector="a", source=FieldSource.URL),
            FieldSpec(name="image", selector="img", source=FieldSource.IMAGE),
        ],
    )
    r = extract.apply_schema(_catalog(3), schema, "https://shop.example/", limit=10)
    assert r["columns"] == ["title", "price", "sku", "link", "image"]
    assert r["rows"][0] == {
        "title": "Товар 1",
        "price": "1990",
        "sku": "1",
        "link": "https://shop.example/p/1",
        "image": "https://shop.example/img/1.jpg",
    }
    assert all(v == 3 for v in r["match_counts"].values())


def test_asset_manifest_has_image_urls() -> None:
    schema = ExtractionSchema(
        source_kind=SourceKind.REPEATED_DOM,
        container_selector="div.product",
        fields=[FieldSpec(name="image", selector="img", source=FieldSource.IMAGE)],
    )
    r = extract.apply_schema(_catalog(3), schema, "https://shop.example/")
    assert len(r["assets"]) == 3
    assert all(a["url"].startswith("https://shop.example/img/") for a in r["assets"])


def test_html_and_attr_sources() -> None:
    schema = ExtractionSchema(
        source_kind=SourceKind.REPEATED_DOM,
        container_selector="div.product",
        fields=[
            FieldSpec(name="raw", selector="a", source=FieldSource.HTML),
            FieldSpec(name="id", selector="", source=FieldSource.ATTR, attr_name="data-id"),
        ],
    )
    r = extract.apply_schema(_catalog(2), schema, "https://shop.example/")
    assert "<h3>" in r["rows"][0]["raw"]
    assert r["rows"][0]["id"] == "1"


# ---------- transforms ----------
def test_transforms() -> None:
    assert tr.apply("  hi  ", Transform.TRIM, None) == "hi"
    assert tr.apply("a\n\t b", Transform.NORMALIZE_WS, None) == "a b"
    assert tr.apply("Цена: 1 990,50 ₽", Transform.NUMBER, None) == "1990.50"
    assert tr.apply("SKU-ABC-123", Transform.REGEX, r"(\d+)") == "123"
    assert tr.apply("Дата 31.12.2026 в 10:00", Transform.DATE, None) == "2026-12-31"


def test_regex_transform_requires_pattern() -> None:
    with pytest.raises(InvalidTransform):
        tr.validate(Transform.REGEX, None)
    with pytest.raises(InvalidTransform):
        tr.validate(Transform.REGEX, "(")


# ---------- validation & explicit errors ----------
def test_invalid_css_selector_explicit() -> None:
    with pytest.raises(InvalidSelector):
        validate("div..>>", SelectorType.CSS)


def test_invalid_xpath_selector_explicit() -> None:
    with pytest.raises(InvalidSelector):
        validate("//[bad(", SelectorType.XPATH)


def test_validate_schema_rejects_dupes_and_missing_attr() -> None:
    with pytest.raises(ValueError):
        extract.validate_schema(ExtractionSchema(
            source_kind=SourceKind.REPEATED_DOM, container_selector="div",
            fields=[FieldSpec(name="a", selector="x"), FieldSpec(name="a", selector="y")],
        ))
    with pytest.raises(ValueError):
        extract.validate_schema(ExtractionSchema(
            source_kind=SourceKind.REPEATED_DOM, container_selector="div",
            fields=[FieldSpec(name="a", selector="x", source=FieldSource.ATTR)],  # нет attr_name
        ))


def test_unsupported_selector_on_stdlib_is_explicit() -> None:
    from app.parser.dom import UnsupportedSelector, parse

    doc = parse("<div class=x>hi</div>", prefer="stdlib")
    with pytest.raises(UnsupportedSelector):
        doc.css("div")


def test_missing_cssselect_is_dependency_error_not_bad_selector(monkeypatch) -> None:
    """Отсутствие обязательного cssselect не маскируется под «Некорректный CSS-селектор».

    div.product — корректный селектор; проблема в окружении, поэтому ждём отдельную
    MissingDependencyError (500), а не InvalidSelector (400).
    """
    import sys

    from app.parser.selectors import MissingDependencyError

    monkeypatch.setitem(sys.modules, "cssselect", None)  # import cssselect → ImportError
    with pytest.raises(MissingDependencyError) as ei:
        validate("div.product", SelectorType.CSS)
    assert "cssselect" in str(ei.value)
    assert not isinstance(ei.value, InvalidSelector)
    assert ei.value.status_code == 500


# ---------- sanitize (visual selector) ----------
def test_sanitize_strips_scripts_and_handlers() -> None:
    dirty = '<div onclick="steal()"><script>evil()</script><a href="javascript:bad()">x</a><img src="/i.jpg"></div>'
    clean = sanitize_html(dirty, "https://s.example/")
    assert "<script" not in clean.lower()
    assert "onclick" not in clean.lower()
    assert "javascript:" not in clean.lower()
    assert "data-src" in clean  # внешняя картинка не грузится автоматически


# ---------- секреты не утекают ----------
def test_no_secret_leak_in_curl_analyze(client: TestClient) -> None:
    r = client.post("/api/parser/inspect", json={"input": 'curl https://api.example.com -H "Authorization: Bearer SUPERSECRET" -b "sid=TOP"'})
    text = r.text
    assert "SUPERSECRET" not in text
    assert "TOP" not in text or "***" in text


# ---------- API endpoints (офлайн, вставленный контент) ----------
def test_analyze_endpoint_html(client: TestClient) -> None:
    r = client.post("/api/parser/analyze", json={"input": _catalog(6)})
    body = r.json()
    assert body["recommendation"]["selected"]["kind"] == "repeated_dom"
    assert body["recommendation"]["selected"]["record_count"] == 6


def test_validate_endpoint_rejects_bad_selector(client: TestClient) -> None:
    r = client.post("/api/parser/validate", json={"schema": {
        "source_kind": "repeated_dom", "container_selector": "div..>>",
        "fields": [{"name": "a", "selector": "h3"}],
    }})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_selector"


def test_preview_endpoint(client: TestClient) -> None:
    r = client.post("/api/parser/preview", json={
        "input": _catalog(4),
        "schema": {"source_kind": "repeated_dom", "container_selector": "div.product",
                   "fields": [{"name": "title", "selector": "h3"}, {"name": "price", "selector": "span[class*=price]", "transform": "number"}]},
    })
    body = r.json()
    assert body["container_matches"] == 4
    assert body["rows"][0]["title"].startswith("Товар")
    assert body["rows"][0]["price"] == "1990"


def test_export_csv_and_manifest(client: TestClient) -> None:
    payload = {"input": _catalog(3),
               "schema": {"source_kind": "repeated_dom", "container_selector": "div.product",
                          "fields": [{"name": "title", "selector": "h3"}, {"name": "image", "selector": "img", "source": "image"}]}}
    csv_resp = client.post("/api/parser/export?format=csv", json=payload)
    assert csv_resp.status_code == 200
    assert "title" in csv_resp.text.splitlines()[0]
    man = client.post("/api/parser/export?format=manifest", json=payload)
    assert man.status_code == 200
    assert "/img/" in man.text
