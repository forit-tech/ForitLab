"""Web Parser 1f: Reproduce (codegen) + миграция старого Scrape."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.parser.models import ExtractionSchema, FieldSource, FieldSpec, RequestSpec, SelectorType, SourceKind
from app.parser.reproduce import reproduce, to_curl, to_python


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


def _schema():
    return ExtractionSchema(
        source_kind=SourceKind.REPEATED_DOM,
        container_selector="div.product",
        fields=[
            FieldSpec(name="title", selector="h3", source=FieldSource.TEXT),
            FieldSpec(name="sku", selector="@data-id", selector_type=SelectorType.XPATH, source=FieldSource.TEXT),
            FieldSpec(name="link", selector="a", source=FieldSource.URL),
        ],
    )


# ---------- codegen ----------
def test_curl_masks_secrets():
    spec = RequestSpec(method="POST", url="https://api.ex/u", headers={"Authorization": "Bearer SECRET"}, body='{"a":1}')
    curl = to_curl(spec)
    assert "SECRET" not in curl
    assert "$AUTH_TOKEN" in curl
    assert "-X POST" in curl
    assert "--data" in curl


def test_python_uses_env_for_secrets():
    spec = RequestSpec(method="GET", url="https://api.ex/u", headers={"Authorization": "Bearer SECRET", "Accept": "application/json"})
    code = to_python(spec, _schema())
    assert "SECRET" not in code
    assert 'os.environ["AUTH_TOKEN"]' in code
    assert "import requests" in code
    assert "from lxml import html" in code
    assert "cssselect('div.product')" in code


def test_generated_python_actually_extracts():
    """Сгенерированный extractor реально работает (истинная воспроизводимость)."""
    from app.parser.reproduce import _extract_snippet
    from lxml import html as lxml_html

    code = _extract_snippet(_schema())

    class R:
        text = '<div class="product" data-id="7"><a href="/p/7"><h3>Товар 7</h3></a></div>'
        url = "https://shop.ex/"

    ns = {"html": lxml_html, "resp": R()}
    exec(code, ns)
    assert ns["rows"] == [{"title": "Товар 7", "sku": "7", "link": "https://shop.ex/p/7"}]


def test_reproduce_returns_both():
    out = reproduce(RequestSpec(url="https://api.ex/u"), None)
    assert out["curl"].startswith("curl")
    assert "requests" in out["python"]


def test_reproduce_endpoint(client):
    r = client.post("/api/parser/reproduce", json={
        "request": {"method": "GET", "url": "https://shop.ex/cat", "headers": {"Authorization": "Bearer X"}},
        "schema": {"source_kind": "repeated_dom", "container_selector": "div.product",
                   "fields": [{"name": "title", "selector": "h3"}]},
    }).json()
    assert "$AUTH_TOKEN" in r["curl"]
    assert "cssselect('div.product')" in r["python"]
    assert "X" not in r["curl"].replace("$AUTH_TOKEN", "")  # секрет не утёк


# ---------- миграция Scrape → Parser ----------
def test_tools_lists_parser_not_scrape(client):
    tools = client.get("/api/tools").json()
    ids = [t["id"] for t in tools]
    assert "parser" in ids
    assert "scrape" not in ids


def test_scrape_endpoints_still_work_compat(client):
    # старую реализацию не удалили — она осталась совместимой
    assert client.get("/api/scrape/limits").status_code == 200


def test_harvester_nav_removed_and_redirects():
    from pathlib import Path

    html = (Path(__file__).resolve().parents[1] / "app" / "static" / "index.html").read_text(encoding="utf-8")
    assert ">Harvester<" not in html  # кнопки в nav больше нет
    js = (Path(__file__).resolve().parents[1] / "app" / "static" / "app.js").read_text(encoding="utf-8")
    assert 'view = "parser"; // миграция' in js  # #harvester редиректит на #parser


def test_live_scrape_modules_still_imported():
    # parser/entities/discovery — живые зависимости нового Parser, НЕ удалены
    from app.tools.scrape.parser import parse  # noqa: F401
    from app.tools.scrape.entities import detect_entities  # noqa: F401
    from app.tools.scrape.discovery import candidates_from_page  # noqa: F401
