"""Только НЕдеструктивные активные проверки.

Единственное действие — OPTIONS-запрос, из ответа читаем заголовок Allow
(объявленные сервером методы). Никаких PUT/DELETE/PATCH-запросов и никаких
данных — мы лишь ЧИТАЕМ то, что сервер сам про себя объявил. Функция чистая:
принимает строку Allow, возвращает findings.
"""

from __future__ import annotations

from .models import finding

_WRITE_METHODS = {"PUT", "DELETE", "PATCH"}


def parse_allow(allow_header: str | None) -> set[str]:
    return {m.strip().upper() for m in (allow_header or "").split(",") if m.strip()}


def check_http_methods(allow_header: str | None, origin: str = "") -> list[dict]:
    methods = parse_allow(allow_header)
    if not methods:
        return []
    out: list[dict] = [finding(
        "http_methods_allowed", "info", "Объявленные HTTP-методы (OPTIONS)",
        f"Allow: {', '.join(sorted(methods))}",
        "Список методов показывает поверхность API/сервера (наблюдение, не уязвимость).",
        "Оставьте включёнными только реально нужные методы.", "methods", origin=origin)]

    if "TRACE" in methods:
        out.append(finding(
            "http_trace_declared", "low", "Сервер объявляет метод TRACE",
            "Allow содержит TRACE",
            "TRACE может использоваться в Cross-Site Tracing (XST) для кражи данных через отражение запроса.",
            "Отключите метод TRACE на веб-сервере.", "methods", origin=origin))

    write = methods & _WRITE_METHODS
    if write:
        out.append(finding(
            "http_write_methods_declared", "low", "Объявлены методы записи",
            f"Allow содержит: {', '.join(sorted(write))}",
            "Методы PUT/DELETE/PATCH меняют состояние — стоит убедиться, что они защищены авторизацией.",
            "Проверьте, что write-методы закрыты аутентификацией и нужны на этом эндпоинте.", "methods", origin=origin))

    return out
