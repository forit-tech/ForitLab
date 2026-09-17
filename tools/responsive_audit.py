"""Responsive-аудит интерфейса Forit Lab (Playwright, headless Chromium + WebKit).

Проходит все страницы на наборе вьюпортов (телефоны, планшеты, десктоп), заполняет
результаты (демо/предпросмотр/вскрытие), и на каждом размере проверяет:
  * горизонтальный overflow документа (scrollWidth > innerWidth);
  * элементы, вылезающие за правый край вьюпорта (кроме тех, что внутри scroll-контейнеров);
  * размер шрифта интерактивных полей ввода на мобильных (< 16px → зум в iOS Safari);
  * минимальный размер тач-таргетов (кнопки/ссылки/чипы) на мобильных.

Запуск при поднятом сервере на :8000:
    ./.venv/Scripts/python.exe tools/responsive_audit.py              # только проверки
    ./.venv/Scripts/python.exe tools/responsive_audit.py --shots      # + скриншоты в var/responsive/
    ./.venv/Scripts/python.exe tools/responsive_audit.py --webkit     # движок Safari (WebKit)
Код выхода 1, если есть нарушения.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = os.environ.get("FORIT_BASE", "http://127.0.0.1:8000")
OUT = Path("var/responsive")

VIEWPORTS = [
    ("iphone-se-1", 320, 568, True),
    ("iphone-se", 375, 667, True),
    ("iphone-14", 390, 844, True),
    ("iphone-15-pro", 393, 852, True),
    ("iphone-pro-max", 430, 932, True),
    ("ipad-mini", 768, 1024, True),
    ("ipad-air", 820, 1180, True),
    ("ipad-pro-portrait", 1024, 1366, True),
    ("laptop", 1366, 768, False),
    ("desktop", 1920, 1080, False),
]

MIN_TOUCH = 40  # ~44pt по HIG; допускаем 40 для вторичных inline-действий
MIN_INPUT_FONT = 16


def fill_home(page):
    page.wait_for_selector("#toolGrid .tool-card")


def fill_about(page):
    page.wait_for_selector("#aboutTools .rblock")


def fill_harvester(page):
    # сеть наружу в аудите не нужна — рендерим результат из фикстуры через сам renderHarvest
    page.evaluate(
        """() => {
      const d = {status:200, elapsed_ms:512, final_url:'https://en.wikipedia.org/wiki/List_of_countries_by_GDP_(nominal)_with_a_really_long_path_segment_that_never_ends',
        counts:{tables:2, links:1234, images:40, words:18000},
        meta:{title:'List of countries by GDP (nominal) — Wikipedia', description:'A very long description '.repeat(6), canonical:'https://en.wikipedia.org/wiki/List_of_countries_by_GDP_(nominal)', lang:'en'},
        tables:[{index:0, caption:'GDP by country (IMF, World Bank, UN)', rows:213, columns:8,
          headers:['Country/Territory','UN region','IMF estimate','IMF year','World Bank estimate','WB year','United Nations estimate','UN year'],
          preview:Array.from({length:6},(_,i)=>['United States of America '+i,'Americas','26,854,599','2023','25,462,700','2022','23,315,081','2021'])}],
        entities:[{signature:'div.card>h3+p+a.more', count:24, confidence:.82, fields:['title','text','link','price','rating'],
          preview:Array.from({length:4},(_,i)=>({title:'Item '+i, text:'Some text that is fairly long and descriptive', link:'https://example.com/item/'+i, price:'$'+(i*10), rating:'4.'+i}))}],
        api_candidates:[{confidence:'high', url:'https://api.example.com/v1/countries/gdp?format=json&year=2023&source=imf&page=1'},
                        {confidence:'low', url:'/w/api.php?action=query&format=json'}]};
      const url = 'https://en.wikipedia.org/wiki/List_of_countries_by_GDP_(nominal)';
      document.querySelector('#hvUrl').value = url;
      document.querySelector('#hvOut').replaceChildren(renderHarvest(d, url));
    }"""
    )


def fill_finder(page):
    page.wait_for_selector("#afOut .rcard", timeout=15000)


def fill_burner(page):
    page.wait_for_function("document.querySelector('#buPreset').options.length > 0")
    page.click("#buPreview")
    page.wait_for_selector("#buOut pre.code", timeout=15000)


def fill_drift(page):
    page.click("#drDemo")
    page.wait_for_selector("#drOut .verdict", timeout=20000)


def fill_unicode(page):
    page.fill("#unText", "Аpple  admin​  1 234 " + "очень_длинная_строка_без_пробелов_" * 4)
    page.click("#unGo")
    page.wait_for_selector("#unOut .verdict", timeout=15000)


def fill_chaos(page):
    page.fill("#chStatus", "200")
    page.fill("#chDelay", "0")
    page.select_option("#chBody", "malformed_json")
    page.click("#chTry")
    page.wait_for_selector("#chOut .panel", timeout=15000)


PAGES = [
    ("home", fill_home),
    ("about", fill_about),
    ("harvester", fill_harvester),
    ("finder", fill_finder),
    ("burner", fill_burner),
    ("drift", fill_drift),
    ("unicode", fill_unicode),
    ("chaos", fill_chaos),
]

CHECK_JS = """([mobile, minTouch, minFont]) => {
  const vw = document.documentElement.clientWidth;
  const problems = [];
  const docW = document.documentElement.scrollWidth;
  if (docW > vw + 1) problems.push({kind:'doc-overflow', detail:`scrollWidth ${docW} > ${vw}`});

  const describe = (e) => {
    let s = e.tagName.toLowerCase();
    if (e.id) s += '#' + e.id;
    if (e.classList.length) s += '.' + [...e.classList].slice(0,3).join('.');
    return s;
  };
  // элемент внутри контейнера, который сам скроллится/обрезает по X — такие не считаем
  const clipped = (e) => {
    for (let p = e.parentElement; p && p !== document.body; p = p.parentElement) {
      const ox = getComputedStyle(p).overflowX;
      if (ox === 'auto' || ox === 'scroll' || ox === 'hidden' || ox === 'clip') return true;
    }
    return false;
  };
  const visible = (e) => {
    const r = e.getBoundingClientRect();
    const cs = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none' && !e.closest('[hidden]');
  };
  const view = document.querySelector('.view.active');
  const scope = [document.querySelector('header.top'), view].filter(Boolean);
  const seen = new Set();
  for (const root of scope) for (const e of root.querySelectorAll('*')) {
    if (!visible(e)) continue;
    const r = e.getBoundingClientRect();
    if ((r.right > vw + 1 || r.left < -1) && !clipped(e)) {
      const key = describe(e);
      if (!seen.has(key)) { seen.add(key); problems.push({kind:'x-overflow', detail:`${key} [${Math.round(r.left)}..${Math.round(r.right)}]`}); }
    }
  }
  if (mobile) {
    for (const root of scope) for (const e of root.querySelectorAll('input:not([type=checkbox]):not([type=radio]),select,textarea')) {
      if (!visible(e)) continue;
      const fs = parseFloat(getComputedStyle(e).fontSize);
      if (fs < minFont) problems.push({kind:'input-font', detail:`${describe(e)} font-size ${fs}px`});
    }
    for (const root of scope) for (const e of root.querySelectorAll('button,a.btn,a.act,.chip,select,label.toggle,#nav button')) {
      if (!visible(e)) continue;
      const r = e.getBoundingClientRect();
      if (r.height < minTouch) problems.push({kind:'touch', detail:`${describe(e)} "${(e.textContent||'').trim().slice(0,24)}" ${Math.round(r.width)}x${Math.round(r.height)}`});
    }
  }
  return problems;
}"""


def check_about_helpers(page, w, h, mobile, shot_prefix) -> list[dict]:
    """«Как это работает»: подсказка (маленький ?) и справка (большой ?) открываются, влезают в экран и закрываются."""
    problems = []
    def tap(sel):
        # в тач-контексте — настоящий tap; без has_touch (десктоп, --webkit) — клик
        try:
            (page.tap if mobile else page.click)(sel, timeout=4000)
        except Exception:  # noqa: BLE001
            page.click(sel)
    page.evaluate("window.scrollTo(0, 0)")
    tap("#aboutHintBtn")
    page.wait_for_timeout(250)
    box = page.locator("#aboutHint").bounding_box()
    if page.evaluate("!document.querySelector('#aboutHint').classList.contains('open')"):
        problems.append({"kind": "hint", "detail": "подсказка не открылась"})
    elif box["x"] < 0 or box["x"] + box["width"] > w + 1:
        problems.append({"kind": "hint", "detail": f"подсказка за краем [{round(box['x'])}..{round(box['x'] + box['width'])}]"})
    if shot_prefix:
        page.screenshot(path=f"{shot_prefix}-hint.png")
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    tap("#aboutInfoBtn")
    page.wait_for_timeout(350)
    card = page.locator("#aboutDialog .lm-card").bounding_box()
    if not page.evaluate("document.querySelector('#aboutDialog').open"):
        problems.append({"kind": "dialog", "detail": "справка не открылась"})
    elif card["x"] < -1 or card["y"] < -1 or card["x"] + card["width"] > w + 1 or card["y"] + card["height"] > h + 1:
        problems.append({"kind": "dialog", "detail": f"справка не влезает: {card}"})
    if shot_prefix:
        page.screenshot(path=f"{shot_prefix}-dialog.png")
    page.keyboard.press("Escape")
    page.wait_for_timeout(250)
    if page.evaluate("document.querySelector('#aboutDialog').open || document.documentElement.classList.contains('modal-open')"):
        problems.append({"kind": "dialog", "detail": "справка не закрылась по Escape / скролл остался заблокирован"})
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", action="store_true", help="сохранить скриншоты в var/responsive/")
    ap.add_argument("--webkit", action="store_true", help="гонять в WebKit (движок Safari)")
    ap.add_argument("--only", help="через запятую: имена страниц")
    args = ap.parse_args()
    only = set(args.only.split(",")) if args.only else None

    report: dict[str, list] = {}
    total = 0
    with sync_playwright() as p:
        engine = p.webkit if args.webkit else p.chromium
        browser = engine.launch()
        for vname, w, h, mobile in VIEWPORTS:
            ctx_opts = dict(viewport={"width": w, "height": h}, device_scale_factor=2 if args.shots else 1)
            if mobile and not args.webkit:
                ctx_opts.update(is_mobile=True, has_touch=True)
            ctx = browser.new_context(**ctx_opts)
            page = ctx.new_page()
            for pname, fill in PAGES:
                if only and pname not in only:
                    continue
                page.goto(f"{BASE}/#{pname}", wait_until="networkidle")
                page.evaluate(f"navigate('{pname}')")
                page.wait_for_timeout(150)
                try:
                    fill(page)
                except Exception as e:  # noqa: BLE001
                    report.setdefault(f"{vname}/{pname}", []).append({"kind": "fill-failed", "detail": str(e)[:200]})
                page.wait_for_timeout(250)
                problems = page.evaluate(CHECK_JS, [mobile, MIN_TOUCH, MIN_INPUT_FONT])
                # мобильное меню тоже проверяем в раскрытом виде
                if page.locator("#navToggle").is_visible():
                    try:
                        page.click("#navToggle", timeout=4000)
                    except Exception as e:  # noqa: BLE001
                        problems.append({"kind": "menu-toggle", "detail": str(e).splitlines()[0][:160]})
                        report[f"{vname}/{pname}"] = report.get(f"{vname}/{pname}", []) + problems
                        total += len(problems)
                        continue
                    page.wait_for_timeout(250)
                    if page.evaluate("!document.documentElement.classList.contains('nav-open')"):
                        problems.append({"kind": "menu-toggle", "detail": "меню не открылось"})
                    problems += [dict(x, kind="menu-" + x["kind"]) for x in page.evaluate(CHECK_JS, [mobile, MIN_TOUCH, MIN_INPUT_FONT])]
                    if args.shots and pname == "home":
                        OUT.mkdir(parents=True, exist_ok=True)
                        page.screenshot(path=str(OUT / f"{vname}-menu.png"))
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(200)
                if pname == "about":
                    problems += check_about_helpers(page, w, h, mobile, args.shots and OUT / f"{vname}-about")
                if problems:
                    report[f"{vname}/{pname}"] = report.get(f"{vname}/{pname}", []) + problems
                    total += len(problems)
                if args.shots:
                    OUT.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(OUT / f"{vname}-{pname}.png"), full_page=True)
            ctx.close()
        browser.close()

    for key, probs in report.items():
        print(f"\n== {key} ({len(probs)})")
        for pr in probs[:40]:
            print(f"   {pr['kind']:<16} {pr['detail']}")
    print(f"\nитого нарушений: {total}")
    if args.shots:
        print(f"скриншоты: {OUT.resolve()}")
    (Path("var") / "responsive-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
