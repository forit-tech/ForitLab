"""Security visual selector: opaque-origin picker, строгий CSP, postMessage.

Проверяем и серверный picker-документ, и клиентские гарантии (по коду app.js):
iframe без allow-same-origin, валидация источника/типа/структуры сообщения,
payload не исполняется как HTML/JS.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.parser.sanitize import build_picker_document, sanitize_html

APP_JS = (Path(__file__).resolve().parents[1] / "app" / "static" / "app.js").read_text(encoding="utf-8")

DIRTY = (
    '<html><body><div class="card" onclick="steal()">'
    '<script>window.__pwned=1;evil()</script>'
    '<a href="javascript:bad()">x</a>'
    '<img src="http://evil.example/track.gif">'
    '<span class="price">100</span>'
    '<form action="http://evil.example/post"><input name="q"></form>'
    "</div></body></html>"
)


@pytest.fixture(scope="module")
def doc() -> str:
    return build_picker_document(DIRTY, "https://shop.example/")


# ---------- сервер: sanitizer ----------
def test_remote_script_removed(doc: str) -> None:
    assert "evil()" not in doc
    assert "window.__pwned" not in doc
    # единственный script — наш picker, с nonce
    assert doc.count("<script") == 1
    assert doc.count("<script nonce=") == 1
    assert "forit-picker-select" in doc


def test_event_handlers_removed(doc: str) -> None:
    assert "onclick" not in doc.lower()


def test_javascript_urls_removed(doc: str) -> None:
    assert "javascript:" not in doc.lower()


def test_forms_removed(doc: str) -> None:
    assert "<form" not in doc.lower()
    assert "evil.example/post" not in doc


def test_external_resources_not_autoloaded(doc: str) -> None:
    # живого img src нет — только data-src (сеть молчит)
    assert not re.search(r'[^-]src="http', doc)
    assert 'data-src="http://evil.example/track.gif"' in doc


def test_strict_csp_present(doc: str) -> None:
    assert "Content-Security-Policy" in doc
    assert "default-src 'none'" in doc
    assert "form-action 'none'" in doc
    assert "base-uri 'none'" in doc
    assert "img-src data:" in doc
    # скрипт разрешён только по nonce
    assert re.search(r"script-src 'nonce-[0-9a-f]{16}'", doc)


def test_only_our_picker_script(doc: str) -> None:
    # у нашего script есть nonce, и в документе нет других исполняемых скриптов
    scripts = re.findall(r"<script[^>]*>", doc)
    assert len(scripts) == 1
    assert "nonce=" in scripts[0]


def test_instrumented_metadata(doc: str) -> None:
    assert "data-forit-idx" in doc


def test_sanitize_html_helper_also_clean() -> None:
    out = sanitize_html(DIRTY, "https://shop.example/")
    assert "<script" not in out.lower()
    assert "onclick" not in out.lower()


# ---------- клиент: гарантии по коду app.js ----------
def test_iframe_is_opaque_origin() -> None:
    # sandbox = allow-scripts; ни один sandbox-атрибут не содержит allow-same-origin
    assert 'sandbox: "allow-scripts"' in APP_JS
    assert re.search(r'sandbox:\s*"[^"]*allow-same-origin', APP_JS) is None


def test_parent_does_not_read_iframe_dom() -> None:
    # никакого доступа к contentDocument iframe в visualSelect
    assert "frame.contentDocument" not in APP_JS


def test_postmessage_is_validated() -> None:
    # источник, тип и структура сообщения проверяются
    assert "ev.source !== frame.contentWindow" in APP_JS
    assert 'data.type !== "forit-picker-select"' in APP_JS
    assert 'typeof data.selector !== "string"' in APP_JS


def test_payload_not_executed_as_html() -> None:
    # селектор из payload идёт только в .value поля, не в innerHTML
    fn = APP_JS[APP_JS.index("function onMessage"): APP_JS.index("function cleanup")]
    assert "paLastField.value = selector" in fn
    assert "innerHTML" not in fn
