"""Проверка HTTP-слоя и того, что отчёт действительно находит подложенный дрейф."""

from __future__ import annotations

import io
import re

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture(scope="module")
def client(tmp_path_factory) -> TestClient:
    # Отчёты складываем во временный каталог, чтобы тесты не трогали var/.
    import os

    os.environ["FORIT_STATE_DIR"] = str(tmp_path_factory.mktemp("state"))
    import app.config as config
    import app.deps as deps

    config.settings.state_dir = config.Path(os.environ["FORIT_STATE_DIR"])
    deps._store = None
    return TestClient(create_app())


REFERENCE = "\n".join(
    ["client_id,region,amount,income"]
    + [f"{i},{'MSK' if i % 2 else 'SPB'},{100 + i % 7},{1000 + i}" for i in range(400)]
)
CURRENT = "\n".join(
    ["client_id,region,amount,income,extra"]
    + [
        f"{10_000 + i},{'MSK' if i % 3 else 'UNKNOWN'},{500 + i % 7},{'' if i % 4 == 0 else 2000 + i},x"
        for i in range(400)
    ]
)


def test_service_info_lists_tools(client: TestClient) -> None:
    body = client.get("/api").json()
    assert body["service"] == "forit-lab"
    assert any(tool["id"] == "drift" for tool in body["tools"])


def test_root_serves_web_ui(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Forit Lab" in response.text


def test_root_busts_asset_cache(client: TestClient) -> None:
    # Safari/CDN не должны держать старый CSS/JS после деплоя: ссылки версионируются, HTML перепроверяется
    from app import __version__

    response = client.get("/")
    assert response.headers["cache-control"] == "no-cache"
    for asset in ("styles.css", "app.js"):
        match = re.search(rf'"/{asset}\?v=([^"]+)"', response.text)
        assert match, f"/{asset} без ?v="
        assert match.group(1).startswith(f"{__version__}-")
    assert client.get("/styles.css?v=anything").status_code == 200
    # версия в футере — из того же источника, что и /health
    footer = re.search(r"data-app-version[^>]*>([^<]*)<", response.text)
    assert footer and footer.group(1) == f"v{client.get('/health').json()['version']}" == f"v{__version__}"


def test_asset_version_changes_with_content(tmp_path) -> None:
    from app.main import asset_version, versioned_index

    (tmp_path / "index.html").write_text('<link href="/styles.css"><script src="/app.js?v=old"></script>', encoding="utf-8")
    (tmp_path / "styles.css").write_text("a{}", encoding="utf-8")
    (tmp_path / "app.js").write_text("1", encoding="utf-8")
    before = asset_version(tmp_path)
    html = versioned_index(tmp_path)
    assert f'href="/styles.css?v={before}"' in html and f'src="/app.js?v={before}"' in html
    assert "v=old" not in html
    (tmp_path / "styles.css").write_text("a{color:red}", encoding="utf-8")
    assert asset_version(tmp_path) != before


def test_health_ok(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["ok"] is True
    assert body["status"] == "healthy"


def test_status_reports_environment(client: TestClient) -> None:
    body = client.get("/api/status").json()
    assert body["python"].startswith("3.")
    assert body["dependencies"]["fastapi"]


def test_openapi_is_valid(client: TestClient) -> None:
    body = client.get("/openapi.json").json()
    assert "/api/drift/reports" in body["paths"]
    assert body["info"]["title"] == "Forit Lab API"


def test_docs_available(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200


def test_limits_exposed(client: TestClient) -> None:
    body = client.get("/api/drift/limits").json()
    assert body["max_rows"] > 0
    assert body["notes"]


def test_upload_comparison_finds_planted_drift(client: TestClient) -> None:
    response = client.post(
        "/api/drift/reports",
        files={
            "reference": ("reference.csv", io.BytesIO(REFERENCE.encode()), "text/csv"),
            "current": ("current.csv", io.BytesIO(CURRENT.encode()), "text/csv"),
        },
    )
    assert response.status_code == 200
    report = response.json()

    assert report["schema"]["added"] == ["extra"]
    assert report["summary"]["status"] == "alert"

    codes = {
        finding["code"]
        for column in report["columns"]
        for finding in column["findings"]
    }
    assert "category.new" in codes  # регион UNKNOWN
    assert "missing.appeared" in codes  # income начал пропадать
    assert any(code.startswith("distribution.") for code in codes)  # amount уехал


def test_inline_compare_matches_upload(client: TestClient) -> None:
    response = client.post(
        "/api/drift/compare",
        json={"reference": REFERENCE, "current": CURRENT, "save": False},
    )
    assert response.status_code == 200
    assert response.json()["storage"]["stored"] is False


def test_report_roundtrip_and_text(client: TestClient) -> None:
    report_id = client.get("/api/drift/demo?save=true").json()["report_id"]

    assert client.get(f"/api/drift/reports/{report_id}").json()["report_id"] == report_id

    text = client.get(f"/api/drift/reports/{report_id}/text").text
    assert "DATASET DRIFT REPORT" in text
    assert "Verdict" in text

    listing = client.get("/api/drift/reports").json()
    assert any(item["report_id"] == report_id for item in listing["items"])

    assert client.delete(f"/api/drift/reports/{report_id}").json()["deleted"] is True
    assert client.get(f"/api/drift/reports/{report_id}").status_code == 404


def test_profile_endpoint(client: TestClient) -> None:
    response = client.post(
        "/api/drift/profile",
        files={"file": ("reference.csv", io.BytesIO(REFERENCE.encode()), "text/csv")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["rows"] == 400
    assert {column["name"] for column in body["column_profiles"]} == {
        "client_id",
        "region",
        "amount",
        "income",
    }


def test_identical_files_report_only_full_id_overlap(client: TestClient) -> None:
    """Файл против самого себя: дрейфа нет, но все идентификаторы совпадают.

    Это не ложная тревога, а ровно то, что инструмент должен кричать: такие
    же ключи в обеих выгрузках означают, что это одна и та же выборка.
    """
    response = client.post(
        "/api/drift/compare",
        json={"reference": REFERENCE, "current": REFERENCE, "save": False},
    )
    report = response.json()

    codes = {
        finding["code"]
        for column in report["columns"]
        for finding in column["findings"]
    }
    assert codes == {"leakage.identifier_overlap"}
    assert report["schema"]["added"] == []
    assert report["schema"]["type_changed"] == []


def test_error_format_is_consistent(client: TestClient) -> None:
    body = client.get("/api/drift/reports/does-not-exist").json()
    assert set(body["error"]) >= {"code", "message"}
    assert body["error"]["code"] == "not_found"


def test_disjoint_columns_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/drift/compare",
        json={"reference": "a,b\n1,2\n", "current": "c,d\n3,4\n", "save": False},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unprocessable_data"
