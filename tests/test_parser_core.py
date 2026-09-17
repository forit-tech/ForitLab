"""Web Parser 1a: input detection, DOM abstraction, detect, inspect, ResponseView.

Всё офлайн: URL-путь тестируем через подменённый HttpClient, остальное — напрямую.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.net.client import Hop, HttpResponse
from app.parser import inspect as inspect_mod
from app.parser.detect import source_type_from
from app.parser.dom import UnsupportedSelector, backend_info, get_backend, parse
from app.parser.inputs import detect_input, parse_curl
from app.parser.models import InputKind, SourceType


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


# ---------- input detection ----------
@pytest.mark.parametrize(
    "raw,kind",
    [
        ("https://example.com/x", InputKind.URL),
        ('{"a": 1}', InputKind.JSON),
        ("[1,2,3]", InputKind.JSON),
        ("<html><body><div>x</div></body></html>", InputKind.HTML),
        ("<div class='a'>hi</div>", InputKind.HTML),
        ("curl https://api.example.com/u", InputKind.CURL),
        ("просто текст без структуры", InputKind.UNKNOWN),
        ("", InputKind.UNKNOWN),
    ],
)
def test_detect_input(raw: str, kind: InputKind) -> None:
    assert detect_input(raw).kind == kind


def test_url_with_spaces_is_not_url() -> None:
    # строка с пробелами — не одиночный URL
    assert detect_input("https://example.com две штуки").kind != InputKind.URL


# ---------- cURL ----------
def test_parse_curl_extracts_parts() -> None:
    spec = parse_curl(
        'curl -X POST "https://api.example.com/users?limit=10" '
        '-H "Authorization: Bearer SEKRET" -H "Content-Type: application/json" '
        '-d "{\\"n\\":1}" -b "sid=abc123"'
    )
    assert spec.method == "POST"
    assert spec.url.startswith("https://api.example.com/users")
    assert spec.query.get("limit") == "10"
    assert spec.headers["Content-Type"] == "application/json"
    assert spec.body is not None


def test_curl_masks_secrets() -> None:
    spec = parse_curl('curl https://api.example.com -H "Authorization: Bearer SEKRET" -b "sid=SECRETVAL"')
    masked = spec.to_masked()
    assert masked["headers"]["Authorization"] == "***"
    assert masked["cookies"]["sid"] == "***"
    # секрет не должен утечь ни в одно строковое значение
    assert "SEKRET" not in str(masked)
    assert "SECRETVAL" not in str(masked)


def test_curl_method_defaults() -> None:
    assert parse_curl("curl https://x.example").method == "GET"
    assert parse_curl('curl https://x.example -d "a=1"').method == "POST"


# ---------- source type detection (content-type mismatch → тело важнее) ----------
@pytest.mark.parametrize(
    "ct,body,expected",
    [
        ("text/html; charset=utf-8", "<!doctype html><html></html>", SourceType.HTML),
        ("application/json", '{"a":1}', SourceType.JSON),
        ("text/plain", '{"a":1}', SourceType.JSON),               # mismatch: тело JSON
        ("application/json", "<html><body>hi</body></html>", SourceType.HTML),  # mismatch: тело HTML
        ("application/x-ndjson", '{"a":1}\n{"a":2}', SourceType.JSONL),
        ("image/png", b"\x89PNG\r\n", SourceType.BINARY),
        ("text/csv", "a,b,c\n1,2,3\n4,5,6", SourceType.CSV),
        ("application/xml", "<?xml version='1.0'?><root/>", SourceType.XML),
        ("text/plain", "just words here", SourceType.TEXT),
    ],
)
def test_source_type(ct: str, body, expected: SourceType) -> None:
    assert source_type_from(ct, body) == expected


# ---------- DOM abstraction ----------
def test_backend_info_shape() -> None:
    info = backend_info()
    assert set(info) == {"backend", "css", "xpath"}


def test_active_backend_supports_selectors_or_is_floor() -> None:
    # активный backend либо lxml (css+xpath), либо честный stdlib-пол
    b = get_backend()
    assert b.name in {"lxml", "stdlib", "html5lib"}
    if b.name == "lxml":
        assert b.supports_css and b.supports_xpath


HTML = (
    "<div class='product'><a href='/p/1'><h3>T1</h3></a><span class='price'>100</span></div>"
    "<div class='product'><span class='price'>200</span>"  # намеренно незакрытый
)


def test_stdlib_backend_builds_tree_but_refuses_selectors() -> None:
    doc = parse(HTML, prefer="stdlib")
    assert doc.root.children(), "stdlib backend должен строить дерево"
    with pytest.raises(UnsupportedSelector):
        doc.css("div.product")
    with pytest.raises(UnsupportedSelector):
        doc.xpath("//div")


def test_lxml_backend_css_and_xpath() -> None:
    pytest.importorskip("lxml")
    doc = parse(HTML, prefer="lxml")
    assert len(doc.css("div.product")) == 2
    prices = [e.text() for e in doc.xpath("//span[@class='price']")]
    assert prices == ["100", "200"]


# ---------- ResponseView + inspect ----------
def _fake_response(**over) -> HttpResponse:
    base = dict(
        url="http://api.example/data",
        final_url="http://api.example/data",
        status=200,
        method="GET",
        content_type="application/json",
        charset="utf-8",
        body=b'{"items":[{"id":1}]}',
        text='{"items":[{"id":1}]}',
        elapsed_ms=12.3,
        resolved_ip="93.184.216.34",
        headers={"content-type": "application/json", "set-cookie": "sid=abc"},
        cookies=["sid=abc"],
        redirect_chain=[Hop(url="http://api.example/old", status=301, location="/data")],
        truncated=False,
    )
    base.update(over)
    return HttpResponse(**base)


def test_inspect_url_maps_response_and_masks_setcookie(monkeypatch) -> None:
    class FakeClient:
        def request(self, method, url, **kw):
            return _fake_response()

    monkeypatch.setattr(inspect_mod, "HttpClient", lambda *a, **k: FakeClient())
    out = inspect_mod.inspect("http://api.example/data")
    assert out["source_type"] == "json"
    resp = out["response"]
    assert resp["status"] == 200
    assert resp["resolved_ip"] == "93.184.216.34"
    assert resp["headers"]["set-cookie"] == "***"  # секрет замаскирован
    assert resp["cookie_count"] == 1
    assert len(resp["redirect_chain"]) == 1
    assert out["summary"]["shape"] == "object" or out["summary"]["shape"] == "array"


def test_inspect_url_ssrf_error(monkeypatch) -> None:
    from app.net.errors import UnsafeUrlError

    class FakeClient:
        def request(self, method, url, **kw):
            raise UnsafeUrlError("Адрес отклонён", {"host": "x"})

    monkeypatch.setattr(inspect_mod, "HttpClient", lambda *a, **k: FakeClient())
    out = inspect_mod.inspect("http://internal.example/")
    assert "error" in out


def _card(i: int) -> str:
    return f"<div class='product'><a href='/p/{i}'><h3>Товар {i}</h3></a><span class='price'>{i}00 ₽</span></div>"


def test_inspect_pasted_html() -> None:
    # детектор карточек требует >=3 похожих соседей (2 — не список)
    listing = "<html><body><div class='list'>" + "".join(_card(i) for i in range(1, 5)) + "</div></body></html>"
    out = inspect_mod.inspect(listing)
    assert out["source_type"] == "html"
    assert out["summary"]["counts"]["repeated_entities"] >= 1
    assert any(h["kind"] == "repeated_dom" for h in out["summary"]["source_hints"])


def test_inspect_pasted_json_array() -> None:
    out = inspect_mod.inspect('[{"id":1},{"id":2}]')
    assert out["source_type"] == "json"
    assert out["summary"]["shape"] == "array"
    assert out["summary"]["items"] == 2


def test_inspect_curl_parsed_not_executed() -> None:
    out = inspect_mod.inspect('curl https://api.example.com -H "Authorization: Bearer S"')
    assert out["request"]["headers"]["Authorization"] == "***"
    assert any("Request Builder" in n or "1c" in n for n in out["notes"])


def test_inspect_unknown_input() -> None:
    assert "error" in inspect_mod.inspect("не пойми что")


# ---------- API + отсутствие регрессии старого Scrape ----------
def test_parser_backend_endpoint(client: TestClient) -> None:
    body = client.get("/api/parser/backend").json()
    assert "backend" in body


def test_parser_inspect_endpoint_html(client: TestClient) -> None:
    r = client.post("/api/parser/inspect", json={"input": "<html><body><table><tr><td>1</td></tr></table></body></html>"})
    assert r.status_code == 200
    assert r.json()["source_type"] == "html"


def test_old_scrape_still_registered(client: TestClient) -> None:
    # старый Scrape не сломан и не удалён
    assert client.get("/api/scrape/limits").status_code == 200
    tools = client.get("/api/tools").json()
    rows = tools["tools"] if isinstance(tools, dict) else tools
    assert any(t["id"] == "scrape" for t in rows)
