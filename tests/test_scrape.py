"""Scrape Lab: защита от SSRF и разбор HTML.

Сеть здесь не трогаем: тесты про безопасность должны падать детерминированно,
а тесты парсера не должны зависеть от того, что сегодня лежит на чужом сайте.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.tools.scrape.discovery import candidates_from_page
from app.tools.scrape.fetcher import UnsafeUrlError, validate_url
from app.tools.scrape.parser import parse
from app.tools.scrape.router import _rows_for, _serialize


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


PAGE = """
<!doctype html>
<html lang="ru">
<head>
  <title>Отчёт по регионам</title>
  <meta name="description" content="Тестовая страница">
  <meta property="og:title" content="Отчёт">
  <link rel="canonical" href="https://example.com/report">
  <link rel="alternate" type="application/rss+xml" href="/feed.xml">
  <link rel="alternate" type="application/json" href="/report.json">
  <script type="application/ld+json">{"@type": "Dataset", "name": "Регионы"}</script>
  <script>const API = "/api/v1/regions"; fetch("/api/v1/totals");</script>
  <style>.legend { color: red; }</style>
</head>
<body>
  <h1>Регионы</h1>
  <h2>Сводка</h2>
  <p>Текст страницы про регионы.</p>
  <table>
    <caption>Выручка</caption>
    <tr><th>Регион</th><th>Выручка</th></tr>
    <tr><td><a href="/r/msk">Москва</a></td><td>100</td></tr>
    <tr><td><a href="/r/spb">Санкт-Петербург</a></td><td>90</td></tr>
  </table>
  <table>
    <tr><td>1</td><td>2</td></tr>
  </table>
  <img src="/logo.png" alt="Логотип">
  <img src="/noalt.png">
  <form action="/search" method="get">
    <input name="q" type="text" required>
    <input name="page" type="number">
  </form>
  <a href="https://external.example.org/docs">Внешняя ссылка</a>
</body>
</html>
"""


@pytest.fixture(scope="module")
def page():
    return parse(PAGE, "https://example.com/report")


# --- безопасность ---------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/x",
        "javascript:alert(1)",
        "https://example.com:8080/",
        "https://user:pass@example.com/",
        "https://",
    ],
)
def test_unsafe_schemes_and_ports_rejected(url: str) -> None:
    with pytest.raises(UnsafeUrlError):
        validate_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/",
        "http://127.0.0.1/",
        "http://10.0.0.1/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",  # метаданные облака
        "http://[::1]/",
    ],
)
def test_private_addresses_rejected(url: str) -> None:
    with pytest.raises(UnsafeUrlError):
        validate_url(url)


def test_public_url_accepted() -> None:
    assert validate_url("https://example.com/page") == "https://example.com/page"


def test_validate_endpoint_reports_error_shape(client: TestClient) -> None:
    body = client.get("/api/scrape/validate", params={"url": "http://127.0.0.1/"}).json()
    assert body["error"]["code"] == "unsafe_url"


# --- разбор HTML ----------------------------------------------------------


def test_title_and_meta(page) -> None:
    assert page.title == "Отчёт по регионам"
    assert page.meta["description"] == "Тестовая страница"
    assert page.meta["og:title"] == "Отчёт"
    assert page.canonical == "https://example.com/report"
    assert page.lang == "ru"


def test_table_headers_and_cells(page) -> None:
    table = page.tables[0]
    assert table.caption == "Выручка"
    assert table.headers == ["Регион", "Выручка"]
    # Текст внутри <a> обязан остаться текстом ячейки.
    assert table.rows == [["Москва", "100"], ["Санкт-Петербург", "90"]]


def test_table_without_header_row_is_kept(page) -> None:
    assert page.tables[1].rows == [["1", "2"]] or page.tables[1].headers == ["1", "2"]


def test_links_are_absolute_and_classified(page) -> None:
    hrefs = {link.href for link in page.links}
    assert "https://example.com/r/msk" in hrefs
    external = [link for link in page.links if not link.internal]
    assert any("external.example.org" in link.href for link in external)


def test_images_track_missing_alt(page) -> None:
    assert len(page.images) == 2
    assert sum(1 for image in page.images if not image.alt) == 1


def test_forms_and_fields(page) -> None:
    form = page.forms[0]
    assert form.action == "https://example.com/search"
    assert form.method == "get"
    assert [field.name for field in form.fields] == ["q", "page"]
    assert form.fields[0].required is True


def test_json_ld_parsed(page) -> None:
    assert page.jsonld == [{"@type": "Dataset", "name": "Регионы"}]


def test_feeds_and_json_alternates(page) -> None:
    assert page.feeds[0]["url"] == "https://example.com/feed.xml"
    assert page.alternate_json[0]["url"] == "https://example.com/report.json"


def test_css_does_not_leak_into_text(page) -> None:
    text = page.page_text()
    assert "color: red" not in text
    assert "Текст страницы про регионы." in text


def test_headings_collected(page) -> None:
    assert {item["text"] for item in page.headings} == {"Регионы", "Сводка"}


# --- поиск API ------------------------------------------------------------


def test_api_candidates_found(page) -> None:
    urls = {item["url"] for item in candidates_from_page(page, "https://example.com/report")}
    assert "https://example.com/report.json" in urls  # объявлен самим сайтом
    assert "https://example.com/api/v1/regions" in urls  # найден в скрипте
    assert "https://example.com/feed.xml" in urls


def test_static_assets_not_reported_as_api(page) -> None:
    urls = {item["url"] for item in candidates_from_page(page, "https://example.com/report")}
    assert not any(url.endswith((".png", ".css", ".js")) for url in urls)


# --- выгрузка -------------------------------------------------------------


def test_extract_tables_to_csv(page) -> None:
    headers, rows = _rows_for("tables", page, 0)
    body, media = _serialize(headers, rows, "csv")
    assert media == "text/csv"
    assert body.splitlines()[0] == "Регион,Выручка"
    assert "Москва,100" in body


def test_extract_links_to_ndjson(page) -> None:
    headers, rows = _rows_for("links", page, None)
    body, media = _serialize(headers, rows, "ndjson")
    assert media == "application/x-ndjson"
    assert len(body.strip().splitlines()) == len(page.links)


def test_extract_missing_table_index(page) -> None:
    from app.errors import NotFoundError

    with pytest.raises(NotFoundError):
        _rows_for("tables", page, 99)


def test_limits_endpoint(client: TestClient) -> None:
    body = client.get("/api/scrape/limits").json()
    assert body["allow_private_addresses"] is False
    assert body["respect_robots"] is True
    assert body["user_agent"].isascii()  # заголовки обязаны быть latin-1
