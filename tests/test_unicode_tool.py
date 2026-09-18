"""Unicode tool (новый пакет app/unicode_tool): домен + тонкий роутер.

Роутер тестируем на отдельном FastAPI-приложении, чтобы не монтировать его в
app/main.py.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.errors import register_error_handlers
from app.unicode_tool import MAX_TEXT_CHARS
from app.unicode_tool.clean import clean_copy, escape, normalize, unescape
from app.unicode_tool.inspect import find_issues, inspect_text
from app.unicode_tool.router import router


@pytest.fixture(scope="module")
def client() -> TestClient:
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(router)
    return TestClient(app)


def kinds_at(text: str) -> dict[str, dict]:
    """Отображение kind -> issue (для строк, где каждый kind встречается раз)."""
    return {issue["kind"]: issue for issue in find_issues(text)}


# --- inspect: детект по kind/codepoint/index ---------------------------------

def test_zero_width_detected() -> None:
    text = "ab​cd"
    issue = kinds_at(text)["zero_width"]
    assert issue["codepoint"] == "U+200B"
    assert issue["index"] == 2
    assert issue["action"] == "remove"


def test_bom_detected_separately() -> None:
    issue = kinds_at("﻿hi")["bom"]
    assert issue["codepoint"] == "U+FEFF"
    assert issue["index"] == 0
    assert issue["action"] == "remove"


def test_nbsp_detected() -> None:
    issue = kinds_at("1 234")["nbsp"]
    assert issue["codepoint"] == "U+00A0"
    assert issue["action"] == "replace"


def test_unusual_space_detected() -> None:
    # U+2003 EM SPACE
    issue = kinds_at("a b")["unusual_space"]
    assert issue["codepoint"] == "U+2003"
    assert issue["action"] == "replace"


def test_bidi_detected() -> None:
    # U+202E RIGHT-TO-LEFT OVERRIDE
    issue = kinds_at("file‮gnp.exe")["bidi"]
    assert issue["codepoint"] == "U+202E"
    assert issue["action"] == "remove"


def test_control_detected_but_not_tab_newline() -> None:
    # \x07 BELL — control; \t \n \r не считаются проблемой.
    found = kinds_at("a\x07b\tc\nd")
    assert "control" in found
    assert found["control"]["codepoint"] == "U+0007"
    # таб и перевод строки не попали в issues вовсе
    assert all(i["char"] not in "\t\n" for i in find_issues("a\tb\nc"))


def test_soft_hyphen_detected() -> None:
    issue = kinds_at("pro­verka")["soft_hyphen"]
    assert issue["codepoint"] == "U+00AD"
    assert issue["action"] == "remove"


def test_smart_quotes_flagged_but_kept() -> None:
    issue = kinds_at("“hi”")["smart_quote"]
    assert issue["action"] == "keep"


def test_dash_flagged_but_kept() -> None:
    issue = kinds_at("a—b")["dash"]
    assert issue["action"] == "keep"


def test_inspect_report_shape() -> None:
    report = inspect_text(" hi​")
    assert report["length"] == 4
    assert report["bytes"] == len(" hi​".encode("utf-8"))
    assert report["issues_by_kind"] == {"nbsp": 1, "zero_width": 1}
    assert "is_nfc" in report["normalization"]
    assert report["suggested_clean"]["changed"] is True


def test_mixed_script_detected() -> None:
    # "Аpple": первая буква — кириллическая А (U+0410).
    report = inspect_text("Аpple")
    assert report["mixed_script"]
    assert set(report["mixed_script"][0]["scripts"]) == {"cyrillic", "latin"}


def test_pure_script_not_mixed() -> None:
    assert inspect_text("Яблоко")["mixed_script"] == []
    assert inspect_text("apple")["mixed_script"] == []


# --- clean_copy: убирает невидимое, NBSP->пробел, не трогает буквы ------------

def test_clean_removes_invisible_keeps_letters() -> None:
    cleaned, _ = clean_copy("ad​min")
    assert cleaned == "admin"


def test_clean_nbsp_becomes_space() -> None:
    cleaned, changes = clean_copy("1 234")
    assert cleaned == "1 234"
    replaced = [c for c in changes if c["action"] == "replaced"]
    assert replaced[0]["kind"] == "nbsp"
    assert replaced[0]["to"] == " "


def test_clean_changes_record_removals() -> None:
    cleaned, changes = clean_copy("x​﻿y")
    assert cleaned == "xy"
    removed = [c for c in changes if c["action"] == "removed"]
    assert {c["kind"] for c in removed} == {"zero_width", "bom"}
    assert {c["codepoint"] for c in removed} == {"U+200B", "U+FEFF"}


def test_clean_does_not_touch_ordinary_and_typographic() -> None:
    # Кавычки и тире — смысловая типографика, остаются.
    text = "He said “hi” — ok"
    cleaned, changes = clean_copy(text)
    assert cleaned == text
    assert changes == []


def test_clean_trims_trailing_line_spaces() -> None:
    cleaned, _ = clean_copy("line one   \nline two\t\n")
    assert cleaned == "line one\nline two"


def test_clean_normalizes_to_nfc() -> None:
    # "й" как и + комбинирующая краткая (NFD) -> одна кодовая точка (NFC).
    nfd = "й"
    cleaned, changes = clean_copy(nfd)
    assert cleaned == "й"
    assert len(cleaned) == 1
    assert any(c.get("kind") == "nfc" for c in changes)


def test_clean_ascii_is_noop() -> None:
    cleaned, changes = clean_copy("hello world")
    assert cleaned == "hello world"
    assert changes == []


# --- normalize ----------------------------------------------------------------

def test_normalize_nfc_shrinks_length() -> None:
    nfd = "й"  # 2 codepoints
    assert len(nfd) == 2
    assert len(normalize(nfd, "NFC")) == 1


def test_normalize_nfd_grows_length() -> None:
    nfc = "й"  # 1 codepoint
    assert len(normalize(nfc, "NFD")) == 2


def test_normalize_rejects_unknown_form() -> None:
    with pytest.raises(ValueError):
        normalize("x", "NFZ")


# --- escape / unescape round-trip --------------------------------------------

def test_escape_makes_invisible_visible() -> None:
    assert escape("A B​") == "A B\\u200b"


def test_escape_keeps_ascii_readable() -> None:
    assert escape("Hello, world! 123") == "Hello, world! 123"


def test_escape_unescape_round_trip() -> None:
    for text in ["A B​", " ‮﻿", "path\\to\\x", "тест 🚀 mix"]:
        assert unescape(escape(text)) == text


def test_escape_astral_uses_capital_u() -> None:
    rocket = "\U0001f680"
    assert escape(rocket) == "\\U0001f680"
    assert unescape("\\U0001f680") == rocket


# --- router (тонкий) ----------------------------------------------------------

def test_endpoint_inspect(client: TestClient) -> None:
    body = client.post("/api/unicode2/inspect", json={"text": "a​b"}).json()
    assert body["issues_by_kind"] == {"zero_width": 1}


def test_endpoint_clean(client: TestClient) -> None:
    body = client.post("/api/unicode2/clean", json={"text": "1 234"}).json()
    assert body["cleaned"] == "1 234"
    assert body["changes"]


def test_endpoint_normalize(client: TestClient) -> None:
    body = client.post(
        "/api/unicode2/normalize", json={"text": "й", "form": "NFC"}
    ).json()
    assert body["result"] == "й"


def test_endpoint_normalize_rejects_unknown_form(client: TestClient) -> None:
    resp = client.post("/api/unicode2/normalize", json={"text": "x", "form": "NFZ"})
    assert resp.status_code == 422


def test_endpoint_escape_and_unescape(client: TestClient) -> None:
    esc = client.post(
        "/api/unicode2/escape", json={"text": "A​", "mode": "escape"}
    ).json()["result"]
    assert esc == "A\\u200b"
    back = client.post(
        "/api/unicode2/escape", json={"text": esc, "mode": "unescape"}
    ).json()["result"]
    assert back == "A​"


def test_endpoint_length_limit(client: TestClient) -> None:
    resp = client.post(
        "/api/unicode2/inspect", json={"text": "x" * (MAX_TEXT_CHARS + 1)}
    )
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "payload_too_large"
