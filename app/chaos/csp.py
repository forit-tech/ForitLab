"""Базовый разбор Content-Security-Policy.

Никакого собственного браузерного интерпретатора — только структурный разбор
директив и поиск заведомо опасных паттернов: отсутствие CSP, 'unsafe-inline',
'unsafe-eval', wildcard-источники, http:-источники. Наличие защитных директив
(frame-ancestors / object-src / base-uri) отдаётся как данные через
:func:`parse_csp`, но НЕ превращается в findings (чтобы строгий `default-src
'self'` считался чистым).
"""

from __future__ import annotations

from .models import finding

# fetch-директивы, где источник реально исполняется/загружается
_FETCH_DIRECTIVES = (
    "default-src", "script-src", "script-src-elem", "script-src-attr",
    "style-src", "style-src-elem", "img-src", "connect-src", "font-src",
    "frame-src", "child-src", "object-src", "media-src", "worker-src",
)


def parse_csp(raw: str) -> dict[str, list[str]]:
    """CSP-строка → {directive: [sources...]} (имена директив в нижнем регистре)."""
    directives: dict[str, list[str]] = {}
    for part in (raw or "").split(";"):
        tokens = part.split()
        if not tokens:
            continue
        name = tokens[0].lower()
        directives[name] = tokens[1:]
    return directives


def check_csp(raw: str | None) -> list[dict]:
    """raw — значение заголовка Content-Security-Policy (или None/'' если его нет)."""
    if not raw or not raw.strip():
        return [finding(
            "missing_csp", "medium", "Отсутствует Content-Security-Policy",
            "Заголовок отсутствует",
            "CSP — ключевая защита от XSS и внедрения стороннего кода.",
            "Добавьте политику CSP, начав с отчётного режима (Content-Security-Policy-Report-Only).", "csp")]

    directives = parse_csp(raw)
    low = raw.lower()
    out: list[dict] = []

    if "'unsafe-inline'" in low:
        out.append(finding(
            "csp_unsafe_inline", "medium", "CSP разрешает 'unsafe-inline'",
            "В политике присутствует 'unsafe-inline'",
            "'unsafe-inline' фактически снимает защиту CSP от инлайновых скриптов/стилей (XSS).",
            "Уберите 'unsafe-inline'; используйте nonce или hash для нужных инлайнов.", "csp"))

    if "'unsafe-eval'" in low:
        out.append(finding(
            "csp_unsafe_eval", "medium", "CSP разрешает 'unsafe-eval'",
            "В политике присутствует 'unsafe-eval'",
            "'unsafe-eval' допускает eval()/new Function() — расширяет поверхность атаки XSS.",
            "Уберите 'unsafe-eval' и откажитесь от eval-подобных конструкций.", "csp"))

    wildcard_dirs = [d for d in _FETCH_DIRECTIVES if d in directives and "*" in directives[d]]
    if wildcard_dirs:
        out.append(finding(
            "csp_wildcard_source", "medium", "CSP содержит wildcard-источник (*)",
            f"Директивы с '*': {', '.join(wildcard_dirs)}",
            "Источник '*' разрешает загрузку/выполнение кода с любого домена — CSP почти не защищает.",
            "Замените '*' на явный список доверенных источников.", "csp"))

    if "http://" in low:
        out.append(finding(
            "csp_insecure_scheme", "medium", "CSP разрешает http:-источники",
            "В политике присутствует источник по http://",
            "Ресурсы по http:// можно перехватить/подменить, что обходит защиту CSP.",
            "Используйте только https:-источники в CSP.", "csp"))

    return out
