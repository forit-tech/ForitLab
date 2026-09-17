"""Reproducible spike для выбора selector-backend Web Parser.

Проверяет, доступен ли предпочтительный бэкенд A (lxml + cssselect) в текущем
окружении, и что CSS и XPath реально работают на «грязном» HTML без сети и без
исполнения скриптов. Это тот самый Host-0 gate: запусти на проде до того, как
selector-зависимость станет обязательной для deploy.

    <prod-venv>/bin/python3.13 tools/selector_spike.py

Код выхода 0 — вариант A пригоден. 1 — нужен fallback B (html5lib+cssselect+elementpath).
"""

from __future__ import annotations

import sys

SAMPLE = """
<html><body>
  <div class="product" data-id="1"><a href="/p/1"><h3>Товар 1</h3></a><span class="price">100</span></div>
  <div class="product" data-id="2"><a href="/p/2"><h3>Товар 2</h3></a><span class="price">200</span>
  <img src="/img/2.jpg">
</body></html>
"""  # намеренно незакрытый <div> и отсутствие </a> у второй карточки — HTML-tolerance


def main() -> int:
    print("python", sys.version.split()[0])
    try:
        import lxml  # noqa: F401
        from lxml import html as lxml_html
        import cssselect  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        print("A недоступен:", exc)
        print("=> fallback B (html5lib + cssselect + elementpath)")
        return 1

    print("lxml", lxml.__version__)
    doc = lxml_html.fromstring(SAMPLE)

    css = doc.cssselect("div.product")
    print("CSS div.product ->", len(css), "элемента")

    xp = doc.xpath("//div[@class='product']//span[@class='price']/text()")
    print("XPath prices ->", xp)

    attr = doc.xpath("//div[@class='product']/@data-id")
    print("XPath @data-id ->", attr)

    ok = len(css) == 2 and xp == ["100", "200"] and attr == ["1", "2"]
    print("РЕЗУЛЬТАТ:", "A пригоден" if ok else "A ведёт себя неожиданно — проверить")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
