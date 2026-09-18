"""Движок раскрытия информации.

Заголовки, выдающие ПО/версии/стек (Server, X-Powered-By, X-AspNet-Version,
X-Runtime, X-Generator, X-Drupal-Cache …) и <meta name=generator> в теле.
Уровни в основном LOW/INFO — это не дыра, а лишняя подсказка атакующему.
"""

from __future__ import annotations

import re

from .models import finding, lower_headers

_TECH_HEADERS = ("x-aspnet-version", "x-aspnetmvc-version", "x-runtime", "x-generator", "x-drupal-cache")
_GENERATOR_META = re.compile(
    r"""<meta\b[^>]*\bname\s*=\s*["']generator["'][^>]*\bcontent\s*=\s*["']([^"']+)""",
    re.I,
)


def check_disclosure(headers, text: str = "") -> list[dict]:
    h = lower_headers(headers)
    out: list[dict] = []

    server = h.get("server")
    if server and any(ch.isdigit() for ch in str(server)):
        out.append(finding(
            "server_version", "low", "Заголовок Server раскрывает версию",
            f"Server: {server}", "Точная версия ПО помогает подобрать известные уязвимости.",
            "Скройте версию (server_tokens off у nginx, ServerTokens Prod у Apache).", "disclosure"))
    elif server:
        out.append(finding(
            "server_header", "info", "Присутствует заголовок Server",
            f"Server: {server}", "Раскрывает используемое серверное ПО.",
            "По возможности уберите или обезличьте заголовок.", "disclosure"))

    if h.get("x-powered-by"):
        out.append(finding(
            "powered_by", "low", "Заголовок X-Powered-By раскрывает стек",
            f"X-Powered-By: {h.get('x-powered-by')}", "Раскрывает технологию/версию бэкенда.",
            "Отключите X-Powered-By (например, app.disable('x-powered-by') в Express).", "disclosure"))

    for extra in _TECH_HEADERS:
        if h.get(extra):
            out.append(finding(
                "tech_header_" + extra, "info", f"Технологический заголовок {extra}",
                f"{extra}: {h.get(extra)}", "Раскрывает детали используемого стека.",
                f"Уберите заголовок {extra}, если он не нужен.", "disclosure"))

    if text:
        m = _GENERATOR_META.search(text)
        if m:
            out.append(finding(
                "generator_meta", "info", "Meta generator раскрывает CMS/движок",
                f"<meta name=generator content=\"{m.group(1)[:80]}\">",
                "Указывает CMS/генератор и часто версию — помогает подобрать эксплойты.",
                "Уберите тег <meta name=generator>, если он не нужен.", "disclosure"))

    return out
