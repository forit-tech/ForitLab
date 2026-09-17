"""Санитизация + сборка picker-документа для визуального выбора.

Модель безопасности (важно):
* недоверенный документ НЕ получает same-origin с Forit Lab;
* remote/пользовательские скрипты, on*-обработчики, javascript:-ссылки и внешние
  ресурсы удаляются ДО формирования srcdoc;
* в документ добавляется ТОЛЬКО наш picker-скрипт (с nonce) + строгий CSP;
* iframe грузится с sandbox="allow-scripts" БЕЗ allow-same-origin → opaque-origin,
  поэтому исполниться может лишь наш picker (чужих скриптов уже нет), а родитель
  не имеет DOM-доступа к iframe;
* picker общается с родителем только через postMessage; родитель валидирует
  источник/тип/структуру и никогда не исполняет payload как HTML/JS.
"""

from __future__ import annotations

import secrets

_DROP_TAGS = ("script", "iframe", "object", "embed", "link", "base", "meta", "noscript", "form")

# Минимальный picker: исполняется ВНУТРИ opaque-origin iframe. Читает только
# собственный документ, наружу отдаёт строку-селектор через postMessage.
_PICKER_JS = """
(function(){
  var last=null;
  function cssPath(node){
    if(!node||node.nodeType!==1) return '';
    var tag=node.tagName.toLowerCase();
    var cls=[].slice.call(node.classList||[]).filter(function(c){return c && !/[0-9]{3,}/.test(c);}).slice(0,2);
    if(cls.length) return tag+'.'+cls.join('.');
    if(node.id) return tag+'#'+node.id;
    var p=node.parentElement;
    if(p){var same=[].slice.call(p.children).filter(function(c){return c.tagName===node.tagName;});
      if(same.length>1) return tag+':nth-of-type('+(same.indexOf(node)+1)+')';}
    return tag;
  }
  document.addEventListener('mouseover',function(e){
    if(last&&last.style) last.style.outline='';
    last=e.target; if(last&&last.style){ last.style.outline='2px solid #fb7132'; }
  },true);
  document.addEventListener('click',function(e){
    e.preventDefault(); e.stopPropagation();
    var t=e.target;
    parent.postMessage({type:'forit-picker-select', selector: cssPath(t),
      tag:(t.tagName||'').toLowerCase(), idx:(t.getAttribute&&t.getAttribute('data-forit-idx'))||null}, '*');
  },true);
  document.addEventListener('submit',function(e){e.preventDefault();},true);
})();
"""

_STYLE = "*{cursor:crosshair}body{margin:0;padding:12px;font-family:system-ui,sans-serif;background:#fff;color:#111}"


def _sanitize_root(html: str, base_url: str):
    from lxml import html as lxml_html

    try:
        root = lxml_html.fromstring(html or "<html></html>")
    except Exception:  # noqa: BLE001
        return lxml_html.fromstring("<html><body></body></html>")

    if base_url:
        try:
            root.make_links_absolute(base_url, resolve_base_href=False)
        except Exception:  # noqa: BLE001
            pass

    idx = 0
    for el in list(root.iter()):
        if not isinstance(el.tag, str):
            continue
        tag = el.tag.lower()
        if tag in _DROP_TAGS:
            el.drop_tree()
            continue
        for name, value in list(el.attrib.items()):
            low = name.lower()
            if low.startswith("on"):
                del el.attrib[name]
            elif low in ("href", "src", "action", "formaction") and value.strip().lower().startswith("javascript:"):
                del el.attrib[name]
            elif low == "srcset":
                del el.attrib[name]
        if tag == "img" and el.get("src"):  # не грузим внешние картинки
            el.set("data-src", el.get("src"))
            del el.attrib["src"]
        # инструментируем безопасной метаданностью для picker
        el.set("data-forit-idx", str(idx))
        idx += 1
    return root


def sanitize_html(html: str, base_url: str = "") -> str:
    """Возвращает санитизированный HTML (без picker/CSP) — для тестов и повторного использования."""
    from lxml import etree

    return etree.tostring(_sanitize_root(html, base_url), encoding="unicode", method="html")


def _body_inner(root) -> str:
    from lxml import etree

    body = root.find(".//body")
    target = body if body is not None else root
    parts = []
    if target.text:
        parts.append(target.text)
    for child in target:
        if isinstance(child.tag, str):
            parts.append(etree.tostring(child, encoding="unicode", method="html"))
    return "".join(parts)


def build_picker_document(html: str, base_url: str = "") -> str:
    """Полный HTML для srcdoc: санитизированное тело + строгий CSP + наш picker (nonce)."""
    root = _sanitize_root(html, base_url)
    body_inner = _body_inner(root)
    nonce = secrets.token_hex(8)
    csp = (
        "default-src 'none'; "
        f"script-src 'nonce-{nonce}'; "
        "style-src 'unsafe-inline'; "
        "img-src data:; "
        "base-uri 'none'; "
        "form-action 'none'"
    )
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<meta http-equiv='Content-Security-Policy' content=\"{csp}\">"
        f"<style>{_STYLE}</style></head><body>"
        f"{body_inner}"
        f"<script nonce='{nonce}'>{_PICKER_JS}</script>"
        "</body></html>"
    )
