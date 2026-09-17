"""Статические проверки UI-примитивов Phase 0 (без запуска браузера).

Проверяем контракт: kit/caps подключены и версионируются, нет UA-сниффинга,
caps — feature-detection, kit экспортирует нужные примитивы.
"""

from __future__ import annotations

from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


@pytest.fixture(scope="module")
def kit() -> str:
    return (STATIC / "ui" / "kit.js").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def caps() -> str:
    return (STATIC / "ui" / "caps.js").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def index() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


def test_no_user_agent_sniffing(kit: str, caps: str) -> None:
    for src in (kit, caps):
        assert "navigator.userAgent" not in src
        assert "navigator.platform" not in src


def test_caps_uses_feature_detection(caps: str) -> None:
    for feature in ("showOpenFilePicker", "showDirectoryPicker", "FileReader", "WebAssembly", "crypto"):
        assert feature in caps
    assert "window.ForitCaps" in caps
    assert "fileSystemAccess" in caps


def test_kit_exposes_primitives(kit: str) -> None:
    for name in ("tabs", "diffView", "jsonTree", "progressBar", "badge", "dialog", "popover"):
        assert name in kit
    assert "window.ForitKit" in kit
    # модалка использует нативный dialog с ловушкой фокуса
    assert "showModal" in kit and 'e.key !== "Tab"' in kit


def test_index_links_kit_assets(index: str) -> None:
    assert "/ui/kit.css" in index
    assert "/ui/caps.js" in index
    assert "/ui/kit.js" in index


def test_kit_assets_are_versioned() -> None:
    from app.main import VERSIONED_ASSETS

    for asset in ("ui/kit.css", "ui/kit.js", "ui/caps.js"):
        assert asset in VERSIONED_ASSETS
