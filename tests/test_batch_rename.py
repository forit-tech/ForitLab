"""Офлайн-тесты Batch Rename: правила, план, валидация, ZIP, роутер.

Роутер в main.py не смонтирован (это делает оркестратор), поэтому для
эндпоинтов поднимаем локальное FastAPI-приложение прямо в тесте.
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.batch_rename import (
    apply_rule,
    apply_rules,
    build_plan,
    build_zip,
    validate_name,
)
from app.batch_rename.router import router


# --------------------------------------------------------------------------- #
# rules.py — каждая операция, расширение сохраняется
# --------------------------------------------------------------------------- #


def test_prefix_keeps_extension():
    assert apply_rule("photo.jpg", {"operation": "prefix", "params": {"text": "img_"}}) == "img_photo.jpg"


def test_suffix_keeps_extension():
    assert apply_rule("photo.jpg", {"operation": "suffix", "params": {"text": "_v2"}}) == "photo_v2.jpg"


def test_replace_all_occurrences():
    rule = {"operation": "replace", "params": {"find": "a", "replace": "X"}}
    assert apply_rule("banana.txt", rule) == "bXnXnX.txt"


def test_regex_replace():
    rule = {"operation": "regex_replace", "params": {"pattern": r"\d+", "replacement": "#"}}
    assert apply_rule("file123name45.md", rule) == "file#name#.md"


def test_lowercase_uppercase_title_over_basename():
    assert apply_rule("Hello WORLD.TXT", {"operation": "lowercase"}) == "hello world.TXT"
    assert apply_rule("Hello world.txt", {"operation": "uppercase"}) == "HELLO WORLD.txt"
    assert apply_rule("hello world.txt", {"operation": "title"}) == "Hello World.txt"


def test_numbering_prefix_with_padding_and_index():
    rule = {"operation": "numbering", "params": {"start": 1, "step": 1, "padding": 3, "position": "prefix"}}
    assert apply_rule("a.txt", rule, index=0, total=3) == "001_a.txt"
    assert apply_rule("b.txt", rule, index=1, total=3) == "002_b.txt"


def test_numbering_suffix_position():
    rule = {"operation": "numbering", "params": {"start": 5, "step": 5, "padding": 3, "position": "suffix"}}
    assert apply_rule("c.txt", rule, index=2, total=3) == "c_015.txt"


def test_dotfile_has_no_extension():
    # .gitignore не имеет расширения — префикс приклеивается к целому имени.
    assert apply_rule(".gitignore", {"operation": "prefix", "params": {"text": "x_"}}) == "x_.gitignore"


def test_double_extension_only_last_is_kept():
    assert apply_rule("archive.tar.gz", {"operation": "suffix", "params": {"text": "_bak"}}) == "archive.tar_bak.gz"


# --------------------------------------------------------------------------- #
# порядок правил важен
# --------------------------------------------------------------------------- #


def test_rule_order_prefix_then_numbering():
    rules = [
        {"operation": "prefix", "params": {"text": "img_"}},
        {"operation": "numbering", "params": {"start": 1, "step": 1, "padding": 2, "position": "prefix"}},
    ]
    name, errors = apply_rules("cat.png", rules, index=0, total=1)
    # Сначала префикс -> img_cat, потом нумерация -> 01_img_cat.
    assert name == "01_img_cat.png"
    assert errors == []


def test_rule_order_numbering_then_prefix_differs():
    rules = [
        {"operation": "numbering", "params": {"start": 1, "padding": 2, "position": "prefix"}},
        {"operation": "prefix", "params": {"text": "img_"}},
    ]
    name, _ = apply_rules("cat.png", rules, index=0, total=1)
    assert name == "img_01_cat.png"


# --------------------------------------------------------------------------- #
# плохой regex помечается, не роняет
# --------------------------------------------------------------------------- #


def test_bad_regex_is_flagged_not_raised():
    rules = [{"operation": "regex_replace", "params": {"pattern": "([", "replacement": "x"}}]
    name, errors = apply_rules("data.csv", rules, index=0, total=1)
    assert name == "data.csv"  # имя не изменилось
    assert errors and "regex" in errors[0].lower()


def test_unknown_operation_flagged():
    name, errors = apply_rules("a.txt", [{"operation": "nope"}], index=0, total=1)
    assert name == "a.txt"
    assert errors


# --------------------------------------------------------------------------- #
# validate.py — невалидные имена
# --------------------------------------------------------------------------- #


def test_validate_empty_name():
    assert validate_name("")
    assert validate_name("   ")


def test_validate_reserved_characters():
    errors = validate_name('a<b>:c*.txt')
    assert errors
    assert any("<" in e or ":" in e or "*" in e for e in errors)


def test_validate_dotdot_and_traversal():
    assert validate_name("..")
    assert validate_name(".")
    assert validate_name("../secret.txt")  # разделитель пути
    assert validate_name("a/b.txt")


def test_validate_reserved_windows_names():
    assert validate_name("CON")
    assert validate_name("con.txt")
    assert validate_name("COM1.log")
    assert validate_name("LPT9")
    # Обычное имя, начинающееся с COM, но не зарезервированное — ок.
    assert validate_name("company.txt") == []


def test_validate_too_long():
    long_name = "x" * 256 + ".txt"
    assert any("длин" in e.lower() for e in validate_name(long_name))


def test_validate_trailing_dot_or_space():
    assert validate_name("name.")
    assert validate_name("name ")


def test_validate_control_chars():
    assert validate_name("bad\x00name.txt")


def test_valid_name_has_no_errors():
    assert validate_name("normal_file-01.txt") == []


# --------------------------------------------------------------------------- #
# plan.py — конфликты и summary
# --------------------------------------------------------------------------- #


def test_plan_duplicate_conflict_makes_invalid():
    rules = [{"operation": "replace", "params": {"find": "1", "replace": ""}}]
    # a1.txt -> a.txt, a.txt -> a.txt  => дубль
    plan = build_plan(["a1.txt", "a.txt"], rules)
    assert plan["valid"] is False
    assert plan["summary"]["conflicts"] == 1
    assert plan["conflicts"][0]["case_insensitive"] is False


def test_plan_case_folding_collision():
    rules = [{"operation": "lowercase"}]
    plan = build_plan(["Report.txt", "REPORT.txt"], rules)
    # report.txt vs report.txt после lowercase — прямой дубль.
    assert plan["valid"] is False
    assert plan["summary"]["conflicts"] == 1


def test_plan_case_only_collision_flagged_as_case_insensitive():
    # Разные new_name, совпадающие только по регистру.
    plan = build_plan(["Report.txt", "report.txt"], [])
    assert plan["valid"] is False
    assert plan["conflicts"][0]["case_insensitive"] is True


def test_plan_reports_changed_and_errors_in_summary():
    rules = [{"operation": "prefix", "params": {"text": "x_"}}]
    plan = build_plan(["a.txt", "b.txt"], rules)
    assert plan["valid"] is True
    assert plan["summary"] == {"total": 2, "changed": 2, "conflicts": 0, "errors": 0}
    assert all(item["changed"] for item in plan["items"])


def test_plan_invalid_name_records_error():
    rules = [{"operation": "suffix", "params": {"text": ":"}}]
    plan = build_plan(["a.txt"], rules)
    assert plan["valid"] is False
    assert plan["summary"]["errors"] >= 1
    assert plan["items"][0]["errors"]


# --------------------------------------------------------------------------- #
# archive.py — валидный zip с новыми именами
# --------------------------------------------------------------------------- #


def test_build_zip_contains_new_names():
    files = [("001_a.txt", b"hello"), ("002_b.txt", b"world")]
    raw = build_zip(files)
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        assert zf.namelist() == ["001_a.txt", "002_b.txt"]
        assert zf.read("001_a.txt") == b"hello"
        assert zf.read("002_b.txt") == b"world"
        assert zf.testzip() is None  # архив целостный


# --------------------------------------------------------------------------- #
# router.py — эндпоинты на локальном приложении
# --------------------------------------------------------------------------- #


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_endpoint_plan(client):
    payload = {
        "names": ["a.txt", "b.txt"],
        "rules": [{"operation": "prefix", "params": {"text": "x_"}}],
    }
    resp = client.post("/api/rename/plan", json=payload)
    assert resp.status_code == 200
    plan = resp.json()
    assert plan["valid"] is True
    assert plan["items"][0]["new_name"] == "x_a.txt"


def test_endpoint_apply_returns_zip(client):
    rules = [{"operation": "prefix", "params": {"text": "x_"}}]
    files = [
        ("files", ("a.txt", b"AAA", "text/plain")),
        ("files", ("b.txt", b"BBB", "text/plain")),
    ]
    resp = client.post("/api/rename/apply", data={"rules": json.dumps(rules)}, files=files)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        assert sorted(zf.namelist()) == ["x_a.txt", "x_b.txt"]
        assert zf.read("x_a.txt") == b"AAA"


def test_endpoint_apply_rejects_invalid_plan(client):
    # Оба файла станут одинаковыми -> конфликт -> 400 с планом.
    rules = [{"operation": "replace", "params": {"find": "1", "replace": ""}}]
    files = [
        ("files", ("a1.txt", b"one", "text/plain")),
        ("files", ("a.txt", b"two", "text/plain")),
    ]
    resp = client.post("/api/rename/apply", data={"rules": json.dumps(rules)}, files=files)
    assert resp.status_code == 400
    body = resp.json()
    assert body["plan"]["valid"] is False
    assert body["plan"]["summary"]["conflicts"] == 1


def test_endpoint_apply_bad_rules_json(client):
    files = [("files", ("a.txt", b"x", "text/plain"))]
    resp = client.post("/api/rename/apply", data={"rules": "{not json"}, files=files)
    assert resp.status_code == 422
