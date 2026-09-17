"""Reproduce/codegen (1f MVP): RequestSpec + схема → воспроизводимый код.

Два варианта: curl (запрос) и Python (requests + lxml — тот же движок, что у нас,
поэтому CSS и XPath воспроизводятся один в один). Секреты в код НЕ попадают —
подставляются плейсхолдеры из окружения.
"""

from __future__ import annotations

import shlex

from .models import ExtractionSchema, FieldSource, RequestSpec, SelectorType, SourceKind

_SECRET_HEADERS = {"authorization", "proxy-authorization", "cookie", "x-api-key", "api-key", "x-auth-token"}


def _placeholder(name: str) -> str:
    low = name.lower()
    if "authorization" in low:
        return "$AUTH_TOKEN"
    if "cookie" in low:
        return "$COOKIE"
    if "key" in low:
        return "$API_KEY"
    return "$SECRET"


def _is_secret(name: str) -> bool:
    return name.lower() in _SECRET_HEADERS or "key" in name.lower() or "token" in name.lower()


def to_curl(spec: RequestSpec) -> str:
    parts = ["curl"]
    if spec.method and spec.method != "GET":
        parts += ["-X", spec.method]
    for k, v in spec.headers.items():
        value = _placeholder(k) if _is_secret(k) else v
        parts += ["-H", shlex.quote(f"{k}: {value}")]
    if spec.cookies:
        cookie = "; ".join(f"{k}=$COOKIE" for k in spec.cookies)
        parts += ["-b", shlex.quote(cookie)]
    if spec.body:
        parts += ["--data", shlex.quote(spec.body)]
    parts.append(shlex.quote(spec.url))
    return " ".join(parts)


def _py_headers(spec: RequestSpec) -> str:
    if not spec.headers and not spec.cookies:
        return "{}"
    lines = []
    for k, v in spec.headers.items():
        if _is_secret(k):
            env = _placeholder(k).lstrip("$")
            lines.append(f'    {k!r}: os.environ["{env}"],')
        else:
            lines.append(f"    {k!r}: {v!r},")
    if spec.cookies:
        lines.append('    "Cookie": os.environ["COOKIE"],')
    return "{\n" + "\n".join(lines) + "\n}"


def _extract_snippet(schema: ExtractionSchema) -> str:
    if schema.source_kind != SourceKind.REPEATED_DOM:
        return (
            "records = data if isinstance(data, list) else data.get('items', [])\n"
            "rows = [{k: r.get(k) for k in " + repr([f.name for f in schema.fields]) + "} for r in records]\n"
        )
    lines = [
        "doc = html.fromstring(resp.text)",
        "doc.make_links_absolute(resp.url)",
        "rows = []",
        f"for card in doc.cssselect({schema.container_selector!r}):",
        "    row = {}",
    ]
    for f in schema.fields:
        if not f.selector:
            pick = "card"
        elif f.selector_type == SelectorType.XPATH:
            pick = f"(card.xpath({f.selector!r}) or [None])[0]"
        else:
            pick = f"(card.cssselect({f.selector!r}) or [None])[0]"
        lines.append(f"    el = {pick}")
        if f.source == FieldSource.TEXT:
            get = "el.text_content().strip() if el is not None else ''"
        elif f.source == FieldSource.HTML:
            get = "html.tostring(el, encoding='unicode') if el is not None else ''"
        elif f.source == FieldSource.ATTR:
            get = f"(el.get({f.attr_name!r}) if el is not None else '') or ''"
        elif f.source in (FieldSource.URL, FieldSource.FILE_URL):
            get = "(el.get('href') or el.get('src') or '') if el is not None else ''"
        elif f.source == FieldSource.IMAGE:
            get = "(el.get('src') or '') if el is not None else ''"
        else:
            get = "''"
        # для XPath, вернувшего строку (атрибут/text()), el уже строка
        lines.append(f"    row[{f.name!r}] = el if isinstance(el, str) else ({get})")
        if f.transform:
            lines.append(f"    # transform: {f.transform.value}" + (f" {f.transform_arg}" if f.transform_arg else ""))
    lines.append("    rows.append(row)")
    return "\n".join(lines) + "\n"


def to_python(spec: RequestSpec, schema: ExtractionSchema | None = None) -> str:
    method = (spec.method or "GET").lower()
    head = [
        "import os",
        "import requests",
    ]
    if schema is not None:
        head.append("from lxml import html")
    head.append("")
    head.append(f"URL = {spec.url!r}")
    head.append(f"HEADERS = {_py_headers(spec)}")
    head.append("")
    if spec.body:
        head.append(f"resp = requests.{method}(URL, headers=HEADERS, data={spec.body!r}, timeout=15)")
    else:
        head.append(f"resp = requests.{method}(URL, headers=HEADERS, timeout=15)")
    head.append("resp.raise_for_status()")
    head.append("")
    body = ""
    if schema is not None:
        if schema.source_kind != SourceKind.REPEATED_DOM:
            head.append("data = resp.json()")
        body = _extract_snippet(schema)
        body += "\nprint(len(rows), 'строк')\nfor r in rows[:5]:\n    print(r)\n"
        body += "# Пагинация: пройдите все страницы (rel=next / ?page=N) и объедините rows.\n"
    else:
        body = "print(resp.status_code)\nprint(resp.text[:2000])\n"
    return "\n".join(head) + "\n" + body


def reproduce(spec: RequestSpec, schema: ExtractionSchema | None = None) -> dict:
    return {"curl": to_curl(spec), "python": to_python(spec, schema)}
