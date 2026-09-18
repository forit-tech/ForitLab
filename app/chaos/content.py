"""Движок анализа тела страницы (HTML).

Работает только над текстом ответа, срабатывает исключительно на положительное
обнаружение (никогда не «ругается» на отсутствие чего-либо, чтобы чистая
страница оставалась чистой): mixed content, формы/пароли по HTTP, формы,
постящие на http://, внешние скрипты и признаки debug/stacktrace.
"""

from __future__ import annotations

import re

from .models import finding

_SUBRESOURCE_HTTP = re.compile(
    r"<(?:img|script|link|iframe|audio|video|source)\b[^>]*?\b(?:src|href)\s*=\s*[\"']http://",
    re.I,
)
_FORM = re.compile(r"<form\b[^>]*>", re.I)
_ACTION = re.compile(r"""action\s*=\s*["']?([^"'\s>]+)""", re.I)
_PASSWORD_INPUT = re.compile(r"""<input\b[^>]*\btype\s*=\s*["']?password""", re.I)
_EXTERNAL_SCRIPT = re.compile(r"""<script\b[^>]*\bsrc\s*=\s*["']https?://""", re.I)
_DEBUG = re.compile(
    r"traceback \(most recent call last\)|stack trace|<b>\s*(?:warning|fatal error|notice)\s*</b>"
    r"|fatal error:|exception in thread|uncaught exception|DEBUG\s*=\s*True|Whoops, looks like something went wrong",
    re.I,
)

_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


def page_title(text: str) -> str:
    """Достать <title> (диагностическая мета, не Finding)."""
    if not text:
        return ""
    m = _TITLE.search(text)
    return (m.group(1).strip() if m else "")[:200]


def check_content(text: str, https: bool, page_url: str = "") -> list[dict]:
    out: list[dict] = []
    if not text:
        return out

    if https and _SUBRESOURCE_HTTP.search(text):
        count = len(_SUBRESOURCE_HTTP.findall(text))
        out.append(finding(
            "mixed_content", "medium", "Смешанный контент (http:// на HTTPS-странице)",
            f"Найдено подгрузок по http://: {count}",
            "Ресурсы по http:// на защищённой странице можно перехватить/подменить; браузер может их блокировать.",
            "Переведите все подресурсы (img/script/link) на https:// или относительные пути.", "content"))

    forms = _FORM.findall(text)
    posts_http = False
    for form in forms:
        m = _ACTION.search(form)
        if m and m.group(1).lower().startswith("http://"):
            posts_http = True
            break
    if posts_http:
        out.append(finding(
            "form_action_http", "medium", "Форма отправляет данные на http://",
            "У <form> action указывает на http://",
            "Данные формы уйдут по незащищённому каналу — их можно перехватить/подменить.",
            "Отправляйте формы только на https://-эндпоинты.", "content"))

    if not https and forms:
        out.append(finding(
            "form_over_http", "medium", "Форма на HTTP-странице",
            f"Найдено форм: {len(forms)}",
            "Любая форма на http-странице передаёт введённые данные в открытом виде.",
            "Переведите страницу с формой на HTTPS.", "content"))

    if not https and _PASSWORD_INPUT.search(text):
        out.append(finding(
            "password_over_http", "high", "Поле пароля на HTTP-странице",
            "Найден <input type=password> на странице без HTTPS",
            "Пароль отправится по незащищённому каналу — прямая утечка учётных данных.",
            "Обслуживайте страницы ввода пароля только по HTTPS.", "content"))

    ext = _EXTERNAL_SCRIPT.findall(text)
    if ext:
        out.append(finding(
            "external_scripts", "info", "Подключены внешние скрипты",
            f"Внешних <script src>: {len(ext)}",
            "Внешние скрипты выполняются с полными правами страницы — доверие третьей стороне.",
            "Ограничьте источники через CSP script-src и по возможности используйте SRI (integrity).", "content"))

    if _DEBUG.search(text):
        out.append(finding(
            "debug_disclosure", "medium", "Признаки debug/stacktrace в ответе",
            "В теле страницы найдены следы трассировки/отладки",
            "Стек-трейсы и отладочные страницы раскрывают внутренние пути, версии и логику приложения.",
            "Отключите debug-режим в проде и отдавайте пользователю обобщённые страницы ошибок.", "content"))

    return out
