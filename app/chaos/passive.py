"""Chaos 1a — Passive Security Check.

Отвечает на простой вопрос: «Я дал URL. Какие очевидные проблемы безопасности
видны БЕЗ атаки на сайт?». Только чтение ответа: заголовки, куки, схема, HTML.

Никаких активных проверок (порт-скан, SQLi, XSS, fuzzing, brute) — это MVP
пассивной диагностики. Честные findings, без магического Security Score.

`run_checks` — чистая функция над ответами (тестируется офлайн); сеть делает
роутер через общий HttpClient (SSRF/pinning).
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

_SUBRESOURCE_HTTP = re.compile(
    r"<(?:img|script|link|iframe|audio|video|source)\b[^>]*?\b(?:src|href)\s*=\s*[\"']http://",
    re.I,
)

# severity: high | medium | low | info
_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}


def _f(fid, severity, title, evidence, why, recommendation, category="misc"):
    return {
        "id": fid,
        "severity": severity,
        "category": category,
        "title": title,
        "evidence": evidence,
        "why": why,
        "recommendation": recommendation,
    }


def _cookie_attrs(raw: str):
    parts = [p.strip() for p in raw.split(";")]
    name = parts[0].split("=", 1)[0].strip() if parts else "cookie"
    attrs = {p.split("=", 1)[0].strip().lower() for p in parts[1:]}
    return name, attrs


def run_checks(primary, http_probe, requested_url: str) -> dict:
    """primary/http_probe — объекты с .final_url/.status/.headers/.cookies/.text (или None)."""
    findings: list[dict] = []
    h = {k.lower(): v for k, v in (primary.headers or {}).items()}
    scheme = urlparse(primary.final_url).scheme
    https = scheme == "https"

    # ---- HTTPS ----
    if not https:
        findings.append(_f("no_https", "high", "Сайт доступен без HTTPS",
                           f"Итоговая схема: {scheme}://", "Трафик передаётся в открытом виде — его можно перехватить и подменить.",
                           "Включите HTTPS (валидный TLS-сертификат) и переведите сайт на него.", "https"))
    elif http_probe is not None and urlparse(http_probe.final_url).scheme != "https":
        findings.append(_f("no_http_redirect", "medium", "HTTP не редиректит на HTTPS",
                           f"http:// отвечает {http_probe.status}, остаётся на {urlparse(http_probe.final_url).scheme}://",
                           "Пользователь, зашедший по http://, останется на незащищённом соединении.",
                           "Настройте постоянный редирект 301 c http:// на https://.", "https"))

    # ---- Security headers ----
    if https and not h.get("strict-transport-security"):
        findings.append(_f("missing_hsts", "medium", "Нет Strict-Transport-Security (HSTS)",
                           "Заголовок отсутствует", "Без HSTS браузер может согласиться на понижение до http:// при первом визите.",
                           "Добавьте: Strict-Transport-Security: max-age=31536000; includeSubDomains.", "headers"))
    if not h.get("content-security-policy"):
        findings.append(_f("missing_csp", "medium", "Отсутствует Content-Security-Policy",
                           "Заголовок отсутствует", "CSP — ключевая защита от XSS и внедрения стороннего кода.",
                           "Добавьте политику CSP, начав с отчётного режима (Content-Security-Policy-Report-Only).", "headers"))
    if (h.get("x-content-type-options") or "").lower() != "nosniff":
        findings.append(_f("missing_nosniff", "low", "Нет X-Content-Type-Options: nosniff",
                           f"Значение: {h.get('x-content-type-options') or '(нет)'}",
                           "Браузер может «угадывать» тип содержимого и исполнить файл как скрипт.",
                           "Добавьте: X-Content-Type-Options: nosniff.", "headers"))
    if not h.get("referrer-policy"):
        findings.append(_f("missing_referrer_policy", "low", "Нет Referrer-Policy",
                           "Заголовок отсутствует", "Полный URL страницы может утекать во внешние сервисы через Referer.",
                           "Добавьте, например: Referrer-Policy: strict-origin-when-cross-origin.", "headers"))
    if not h.get("permissions-policy"):
        findings.append(_f("missing_permissions_policy", "info", "Нет Permissions-Policy",
                           "Заголовок отсутствует", "Не ограничены доступы к камере/микрофону/геолокации для страницы и её фреймов.",
                           "Задайте Permissions-Policy, отключив ненужные возможности (camera=(), microphone=() …).", "headers"))
    csp = (h.get("content-security-policy") or "").lower()
    if not h.get("x-frame-options") and "frame-ancestors" not in csp:
        findings.append(_f("missing_frame_protection", "medium", "Нет защиты от clickjacking",
                           "Нет ни X-Frame-Options, ни CSP frame-ancestors",
                           "Сайт можно встроить в чужой <iframe> и обманом заставить пользователя кликать.",
                           "Добавьте X-Frame-Options: DENY или CSP frame-ancestors 'none'.", "headers"))

    # ---- Cookies ----
    for raw in (primary.cookies or []):
        name, attrs = _cookie_attrs(raw)
        if https and "secure" not in attrs:
            findings.append(_f("cookie_no_secure", "medium", f"Cookie «{name}» без Secure",
                               raw[:120], "Кука без Secure может уйти по незащищённому http-соединению.",
                               "Добавьте флаг Secure к cookie.", "cookies"))
        if "httponly" not in attrs:
            findings.append(_f("cookie_no_httponly", "low", f"Cookie «{name}» без HttpOnly",
                               raw[:120], "Куку без HttpOnly можно украсть через XSS (доступна из JavaScript).",
                               "Добавьте флаг HttpOnly, если кука не нужна фронтенду.", "cookies"))
        if "samesite" not in attrs:
            findings.append(_f("cookie_no_samesite", "low", f"Cookie «{name}» без SameSite",
                               raw[:120], "Без SameSite кука отправляется на межсайтовые запросы — риск CSRF.",
                               "Задайте SameSite=Lax или Strict.", "cookies"))

    # ---- CORS ----
    acao = h.get("access-control-allow-origin")
    acac = (h.get("access-control-allow-credentials") or "").lower()
    if acao == "*":
        if acac == "true":
            findings.append(_f("cors_wildcard_credentials", "high", "CORS: wildcard + credentials",
                               "Access-Control-Allow-Origin: * и Allow-Credentials: true",
                               "Опасная (и по спецификации некорректная) комбинация: любой сайт может слать запросы с куками.",
                               "Не используйте '*' вместе с credentials — задавайте конкретный доверенный Origin.", "cors"))
        else:
            findings.append(_f("cors_wildcard", "low", "CORS открыт для всех (*)",
                               "Access-Control-Allow-Origin: *", "Любой сайт может читать ответы этого источника.",
                               "Если это не публичный API — ограничьте Origin списком доверенных.", "cors"))

    # ---- Information disclosure ----
    server = h.get("server")
    if server and any(ch.isdigit() for ch in server):
        findings.append(_f("server_version", "low", "Заголовок Server раскрывает версию",
                           f"Server: {server}", "Точная версия ПО помогает подобрать известные уязвимости.",
                           "Скройте версию (server_tokens off у nginx, ServerTokens Prod у Apache).", "disclosure"))
    elif server:
        findings.append(_f("server_header", "info", "Присутствует заголовок Server",
                           f"Server: {server}", "Раскрывает используемое серверное ПО.",
                           "По возможности уберите или обезличьте заголовок.", "disclosure"))
    if h.get("x-powered-by"):
        findings.append(_f("powered_by", "low", "Заголовок X-Powered-By раскрывает стек",
                           f"X-Powered-By: {h.get('x-powered-by')}", "Раскрывает технологию/версию бэкенда.",
                           "Отключите X-Powered-By (например, app.disable('x-powered-by') в Express).", "disclosure"))
    for extra in ("x-aspnet-version", "x-aspnetmvc-version", "x-runtime", "x-generator", "x-drupal-cache"):
        if h.get(extra):
            findings.append(_f("tech_header_" + extra, "info", f"Технологический заголовок {extra}",
                               f"{extra}: {h.get(extra)}", "Раскрывает детали используемого стека.",
                               f"Уберите заголовок {extra}, если он не нужен.", "disclosure"))

    # ---- Mixed content ----
    if https and primary.text and _SUBRESOURCE_HTTP.search(primary.text):
        count = len(_SUBRESOURCE_HTTP.findall(primary.text))
        findings.append(_f("mixed_content", "medium", "Смешанный контент (http:// на HTTPS-странице)",
                           f"Найдено подгрузок по http://: {count}",
                           "Ресурсы по http:// на защищённой странице можно перехватить/подменить; браузер может их блокировать.",
                           "Переведите все подресурсы (img/script/link) на https:// или относительные пути.", "html"))

    findings.sort(key=lambda x: _ORDER[x["severity"]])
    summary = {sev: sum(1 for f in findings if f["severity"] == sev) for sev in ("high", "medium", "low", "info")}
    return {
        "url": requested_url,
        "final_url": primary.final_url,
        "status": primary.status,
        "https": https,
        "findings": findings,
        "summary": summary,
        "checks_run": ["https", "headers", "cookies", "cors", "disclosure", "mixed_content"],
    }
