"""Определение вида ввода и разбор cURL.

Пользователь вставляет что угодно: ссылку, HTML, JSON или строку `curl …`.
Определяем вид и приводим к :class:`InputSpec`. cURL ТОЛЬКО разбирается —
никакого shell-выполнения; секреты не логируются, маскируются на выводе.
"""

from __future__ import annotations

import json
import re
import shlex
from urllib.parse import urlparse

from .models import InputKind, InputSpec, RequestSpec

_URL_RE = re.compile(r"^https?://\S+$", re.I)
_HTML_HINT = re.compile(r"<(!doctype|html|head|body|div|table|ul|ol|section|article|main|a|span|p)\b", re.I)


def detect_input(raw: str) -> InputSpec:
    text = (raw or "").strip()
    if not text:
        return InputSpec(kind=InputKind.UNKNOWN, raw=raw)

    # cURL
    if text.startswith("curl ") or text.startswith("curl\t") or text == "curl":
        return InputSpec(kind=InputKind.CURL, raw=raw, request=parse_curl(text))

    # одиночная ссылка
    if _URL_RE.match(text) and len(text.split()) == 1:
        return InputSpec(kind=InputKind.URL, raw=raw, url=text)

    # JSON
    if text[0] in "{[":
        try:
            json.loads(text)
            return InputSpec(kind=InputKind.JSON, raw=raw, body=text)
        except json.JSONDecodeError:
            pass

    # HTML
    if _HTML_HINT.search(text):
        return InputSpec(kind=InputKind.HTML, raw=raw, body=text)

    return InputSpec(kind=InputKind.UNKNOWN, raw=raw)


def parse_curl(command: str) -> RequestSpec:
    """Разбор строки curl в RequestSpec. Ничего не выполняет."""
    # На Windows пути с обратными слешами ломают shlex(posix=True) — но URL и
    # заголовки curl всегда в кавычках, поэтому posix-режим корректен.
    tokens = shlex.split(command.replace("\\\n", " "), posix=True)
    if tokens and tokens[0] == "curl":
        tokens = tokens[1:]

    spec = RequestSpec()
    explicit_method: str | None = None
    i = 0
    while i < len(tokens):
        tok = tokens[i]

        def value() -> str:
            nonlocal i
            if "=" in tok and tok.startswith("--") and tok.split("=", 1)[1]:
                return tok.split("=", 1)[1]
            i += 1
            return tokens[i] if i < len(tokens) else ""

        if tok in ("-X", "--request"):
            explicit_method = value().upper()
        elif tok in ("-H", "--header"):
            raw = value()
            if ":" in raw:
                name, val = raw.split(":", 1)
                spec.headers[name.strip()] = val.strip()
        elif tok in ("-b", "--cookie"):
            raw = value()
            for part in raw.split(";"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    spec.cookies[k.strip()] = v.strip()
        elif tok in ("-d", "--data", "--data-raw", "--data-binary", "--data-ascii", "--data-urlencode"):
            spec.body = (spec.body + "&" + value()) if spec.body else value()
        elif tok in ("-u", "--user"):
            spec.headers.setdefault("Authorization", "Basic <из --user>")
            value()  # значение не сохраняем в открытом виде
        elif tok in ("-A", "--user-agent"):
            spec.headers["User-Agent"] = value()
        elif tok in ("-e", "--referer"):
            spec.headers["Referer"] = value()
        elif tok == "--url":
            spec.url = value()
        elif tok in ("--compressed", "-L", "--location", "-s", "--silent", "-k", "--insecure", "-i", "--include", "-v", "--verbose"):
            pass  # флаги без значения — игнорируем
        elif tok.startswith("http://") or tok.startswith("https://"):
            spec.url = tok
        # прочие незнакомые опции со значением пропускаем мягко
        i += 1

    spec.method = explicit_method or ("POST" if spec.body is not None else "GET")
    ct = next((v for k, v in spec.headers.items() if k.lower() == "content-type"), None)
    spec.content_type = ct or (("application/x-www-form-urlencoded") if spec.body is not None else None)
    if spec.url:
        parsed = urlparse(spec.url)
        if parsed.query:
            from urllib.parse import parse_qsl

            spec.query.update(dict(parse_qsl(parsed.query)))
    return spec
