"""Unicode Crime Lab: находит ли он то, что глазами не видно."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.tools.unicodelab.analyzer import analyze, clean


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


def kinds(text: str) -> dict[str, int]:
    return analyze(text)["issues_by_kind"]


def test_clean_ascii_is_clean() -> None:
    result = analyze("hello world")
    assert result["status"] == "ok"
    assert result["issues"] == []
    assert result["mixed_script_words"] == []


def test_zero_width_detected() -> None:
    result = analyze("admin​")
    assert kinds("admin​")["zero_width"] == 1
    assert result["status"] == "alert"


def test_nbsp_detected() -> None:
    assert kinds("1 234")["exotic_space"] == 1


def test_bidi_override_detected() -> None:
    assert kinds("file‮gnp.exe")["bidi_control"] == 1


def test_soft_hyphen_detected() -> None:
    assert kinds("про­верка")["soft_hyphen"] == 1


def test_replacement_char_detected() -> None:
    assert kinds("сло�во")["replacement_char"] == 1


def test_homoglyph_word_detected() -> None:
    result = analyze("Аpple")  # первая буква — кириллическая А
    assert result["mixed_script_words"]
    finding = result["mixed_script_words"][0]
    assert set(finding["scripts"]) == {"cyrillic", "latin"}
    assert finding["characters"][0]["looks_like"] == "A"


def test_pure_cyrillic_is_not_mixed() -> None:
    assert analyze("Яблоко")["mixed_script_words"] == []


def test_nfd_detected() -> None:
    result = analyze("й")  # и + комбинирующая краткая = й
    assert result["normalization"]["is_nfc"] is False
    assert result["issues_by_kind"].get("combining_mark") == 1


def test_clean_removes_invisible_and_normalizes() -> None:
    # zero-width исчезает без следа, NBSP превращается в обычный пробел, края обрезаются.
    assert clean(" ad​min  ") == "admin"
    assert clean("1 234") == "1 234"


def test_clean_is_idempotent() -> None:
    once = clean("  te​xt here  ")
    assert clean(once) == once


def test_length_counts_bytes_and_chars() -> None:
    result = analyze("привет")
    assert result["length"]["characters"] == 6
    assert result["length"]["bytes"] == 12


def test_samples_endpoint(client: TestClient) -> None:
    samples = client.get("/api/unicode/samples").json()
    assert {sample["id"] for sample in samples} >= {"homoglyph", "zero_width", "nbsp"}


def test_every_sample_is_flagged(client: TestClient) -> None:
    """Каждая строка-ловушка обязана срабатывать — иначе это не ловушка."""
    for sample in client.get("/api/unicode/samples").json():
        result = client.post("/api/unicode/inspect", json={"text": sample["text"]}).json()
        assert result["status"] != "ok", sample["id"]


def test_compare_explains_nfc_difference(client: TestClient) -> None:
    body = client.post(
        "/api/unicode/compare", json={"left": "й", "right": "й"}
    ).json()
    assert body["equal"] is False
    assert body["equal_after_nfc"] is True
    assert "нормализации" in body["verdict"]


def test_compare_explains_invisible_difference(client: TestClient) -> None:
    body = client.post(
        "/api/unicode/compare", json={"left": "admin", "right": "admin​"}
    ).json()
    assert body["equal"] is False
    assert body["equal_after_cleaning"] is True


def test_compare_identical(client: TestClient) -> None:
    body = client.post("/api/unicode/compare", json={"left": "abc", "right": "abc"}).json()
    assert body["equal"] is True
    assert body["differences"] == []


def test_normalize_endpoint(client: TestClient) -> None:
    body = client.post(
        "/api/unicode/normalize", json={"text": "й", "form": "NFC"}
    ).json()
    assert body["changed"] is True
    assert body["after"]["length"] == 1


def test_normalize_rejects_unknown_form(client: TestClient) -> None:
    response = client.post("/api/unicode/normalize", json={"text": "x", "form": "NFZ"})
    assert response.status_code == 422


def test_length_limit_enforced(client: TestClient) -> None:
    from app.config import settings

    response = client.post(
        "/api/unicode/inspect", json={"text": "x" * (settings.unicode_max_chars + 1)}
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
