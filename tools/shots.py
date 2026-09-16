"""Автоскриншоты интерфейса для README (Playwright, headless).

Запуск при поднятом сервере на :8000:
    ./.venv/Scripts/python.exe tools/shots.py
Кладёт кадры в docs/images/{home,harvester,finder,burner,drift,unicode,chaos}.png
"""

from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
OUT = Path("docs/images")
OUT.mkdir(parents=True, exist_ok=True)
VW, VH = 1560, 1000


def shot(page, name, clip_h=None):
    path = OUT / f"{name}.png"
    if clip_h:
        page.screenshot(path=str(path), clip={"x": 0, "y": 0, "width": VW, "height": clip_h})
    else:
        page.screenshot(path=str(path), full_page=True)
    print("saved", path)


with sync_playwright() as p:
    br = p.chromium.launch()
    page = br.new_page(viewport={"width": VW, "height": VH}, device_scale_factor=2)

    # home — первый экран (не full page, чтобы влез hero целиком)
    page.goto(BASE + "/#home", wait_until="networkidle")
    page.wait_for_timeout(1200)
    shot(page, "home", clip_h=980)

    # harvester — реальная страница с результатом
    page.goto(BASE + "/#harvester", wait_until="networkidle")
    page.fill("#hvUrl", "https://en.wikipedia.org/wiki/List_of_countries_by_GDP_(nominal)")
    page.click("#hvGo")
    page.wait_for_timeout(6500)
    shot(page, "harvester")

    # api finder — поиск по умолчанию (все)
    page.goto(BASE + "/#finder", wait_until="networkidle")
    page.wait_for_timeout(1400)
    shot(page, "finder")

    # data burner — предпросмотр
    page.goto(BASE + "/#burner", wait_until="networkidle")
    page.wait_for_timeout(600)
    page.click("#buPreview")
    page.wait_for_timeout(1200)
    shot(page, "burner")

    # drift — демо
    page.goto(BASE + "/#drift", wait_until="networkidle")
    page.wait_for_timeout(400)
    page.click("#drDemo")
    page.wait_for_timeout(1800)
    shot(page, "drift")

    # unicode — вскрытие ловушки
    page.goto(BASE + "/#unicode", wait_until="networkidle")
    page.fill("#unText", "Аpple  admin​  1 234")  # кириллическая А + zero-width + NBSP
    page.click("#unGo")
    page.wait_for_timeout(900)
    shot(page, "unicode")

    # chaos — ответ + разбор
    page.goto(BASE + "/#chaos", wait_until="networkidle")
    page.wait_for_timeout(400)
    page.select_option("#chBody", "malformed_json")
    page.click("#chTry")
    page.wait_for_timeout(3000)
    shot(page, "chaos")

    br.close()
    print("готово")
