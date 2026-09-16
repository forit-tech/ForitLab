"""Регрессия адаптивной вёрстки: статические гарантии, которые легко сломать правкой CSS/HTML.

Живая проверка на вьюпортах (overflow, тач-таргеты, шрифты полей) — tools/responsive_audit.py
(Playwright, нужен поднятый сервер). Здесь — то, что проверяется без браузера и гоняется в CI.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


@pytest.fixture(scope="module")
def html() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def css() -> str:
    return (STATIC / "styles.css").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def js() -> str:
    return (STATIC / "app.js").read_text(encoding="utf-8")


def media_blocks(css: str, query_substr: str) -> list[str]:
    """Тела @media-блоков, в условии которых встречается query_substr (с учётом вложенных скобок)."""
    blocks = []
    for m in re.finditer(r"@media([^{]+)\{", css):
        if query_substr not in m.group(1):
            continue
        depth, i = 1, m.end()
        while depth and i < len(css):
            depth += {"{": 1, "}": -1}.get(css[i], 0)
            i += 1
        blocks.append(css[m.end() : i - 1])
    return blocks


def test_viewport_meta_supports_notch(html: str) -> None:
    meta = re.search(r'<meta name="viewport" content="([^"]+)"', html)
    assert meta, "нет viewport meta"
    content = meta.group(1)
    assert "width=device-width" in content
    assert "viewport-fit=cover" in content, "без viewport-fit=cover не работают env(safe-area-inset-*)"
    assert "user-scalable=no" not in content and "maximum-scale" not in content, "зум запрещать нельзя (доступность)"


def test_mobile_nav_toggle_is_accessible(html: str, js: str) -> None:
    btn = re.search(r"<button[^>]*id=\"navToggle\"[^>]*>", html)
    assert btn, "нет кнопки мобильного меню"
    tag = btn.group(0)
    assert 'aria-controls="nav"' in tag and 'aria-expanded="false"' in tag and "aria-label=" in tag
    assert 'id="navScrim"' in html
    # меню закрывается: по Escape, по тапу на подложку, при навигации
    assert '"Escape"' in js and "setMenu(false)" in js
    start = js.index("function navigate(view)")
    assert "setMenu(false)" in js[start : js.index("\n}\n", start)]


def test_burger_breakpoint_matches_js(css: str, js: str) -> None:
    # JS сбрасывает меню ровно там, где CSS перестаёт показывать бургер
    assert media_blocks(css, "max-width:1099px"), "нет брейкпоинта бургер-меню"
    assert 'matchMedia("(min-width: 1100px)")' in js


def test_form_controls_are_16px_on_touch_devices(css: str) -> None:
    blocks = media_blocks(css, "pointer:coarse")
    joined = "\n".join(blocks)
    for sel in ("input[type=text]", "input[type=url]", "input[type=number]", "select", "textarea"):
        assert sel in joined, f"{sel} не переопределён для тач-устройств"
    assert re.search(r"font-size:\s*16px", joined), "iOS Safari зумит поля с font-size < 16px"


def test_touch_targets_min_height(css: str) -> None:
    joined = "\n".join(media_blocks(css, "pointer:coarse"))
    for sel, min_h in ((".btn{", 44), (".chip{", 40), (".toggle{", 44)):
        m = re.search(re.escape(sel) + r"[^}]*min-height:(\d+)px", joined)
        assert m, f"{sel} без min-height на тач-устройствах"
        assert int(m.group(1)) >= min_h


def test_safe_area_insets_used(css: str) -> None:
    for side in ("top", "bottom", "left", "right"):
        assert f"env(safe-area-inset-{side}" in css, f"не учтён safe-area-inset-{side}"
    # фиксированный хедер и тосты уважают вырез
    assert re.search(r"\.top\{[^}]*var\(--safe-t\)", css)
    assert re.search(r"#toasts\{[^}]*var\(--safe-b\)", css)


def test_vh_always_has_small_viewport_fallback(css: str) -> None:
    # каждое объявление с vh должно сопровождаться svh/dvh-версией (Safari с плавающей адресной строкой)
    for decl in re.findall(r"([a-z-]+):[^;{}]*\d+vh[^;{}]*", css):
        assert re.search(decl + r":[^;{}]*\d+(svh|dvh)", css), f"{decl}: vh без svh/dvh"


def test_grids_cannot_force_horizontal_overflow(css: str) -> None:
    # minmax(300px, …) на экране 320px выталкивает карточку за край — минимум должен ограничиваться 100%
    for m in re.finditer(r"minmax\((\d+)px", css):
        assert int(m.group(1)) <= 160, f"жёсткий minmax({m.group(1)}px) без min(…,100%)"


def test_hover_lift_only_on_hover_devices(css: str) -> None:
    blocks = media_blocks(css, "hover:hover")
    outside = css
    for block in blocks:
        outside = outside.replace(block, "")
    for sel in (".tool-card:hover", ".statcard:hover"):
        assert any(sel in b for b in blocks), f"{sel} с transform должен быть внутри @media (hover:hover)"
        assert not re.search(re.escape(sel) + r"\{[^}]*transform", outside)


def test_breakpoints_cover_target_ranges(css: str) -> None:
    for bp in ("max-width:479px", "max-width:767px", "max-width:1023px", "max-width:1199px"):
        assert media_blocks(css, bp), f"нет брейкпоинта {bp}"
    # на телефоне инструменты — одна колонка, на планшете — две
    assert re.search(r"max-width:767px\)\{\.tool-grid\{grid-template-columns:1fr\}", css)
    assert re.search(r"max-width:1023px\)\{\.tool-grid\{grid-template-columns:repeat\(2,1fr\)\}", css)


def test_no_user_agent_sniffing_for_layout(js: str) -> None:
    assert "navigator.userAgent" not in js and "navigator.platform" not in js


def test_drift_table_has_mobile_labels(js: str) -> None:
    # таблица распределений на телефоне превращается в карточки через data-label — подписи не должны потеряться
    for label in ("Анализ", "PSI", "KS", "Статус"):
        assert f'"data-label": "{label}"' in js
