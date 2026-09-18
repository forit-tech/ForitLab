"""Движок security-заголовков.

Проверяет наличие ключевых защитных заголовков ответа. `missing_csp` живёт в
:mod:`app.chaos.csp` (там же разбор политики), а здесь — HSTS, nosniff,
Referrer-Policy, Permissions-Policy, защита от clickjacking и cross-origin
isolation (COOP/COEP/CORP).
"""

from __future__ import annotations

from .models import finding, lower_headers


def check_security_headers(headers, https: bool, csp_raw: str | None = None) -> list[dict]:
    h = lower_headers(headers)
    if csp_raw is None:
        csp_raw = h.get("content-security-policy") or ""
    csp_l = csp_raw.lower()
    out: list[dict] = []

    if https and not h.get("strict-transport-security"):
        out.append(finding(
            "missing_hsts", "medium", "Нет Strict-Transport-Security (HSTS)",
            "Заголовок отсутствует",
            "Без HSTS браузер может согласиться на понижение до http:// при первом визите.",
            "Добавьте: Strict-Transport-Security: max-age=31536000; includeSubDomains.", "headers"))

    if (h.get("x-content-type-options") or "").lower() != "nosniff":
        out.append(finding(
            "missing_nosniff", "low", "Нет X-Content-Type-Options: nosniff",
            f"Значение: {h.get('x-content-type-options') or '(нет)'}",
            "Браузер может «угадывать» тип содержимого и исполнить файл как скрипт.",
            "Добавьте: X-Content-Type-Options: nosniff.", "headers"))

    if not h.get("referrer-policy"):
        out.append(finding(
            "missing_referrer_policy", "low", "Нет Referrer-Policy",
            "Заголовок отсутствует",
            "Полный URL страницы может утекать во внешние сервисы через Referer.",
            "Добавьте, например: Referrer-Policy: strict-origin-when-cross-origin.", "headers"))

    if not h.get("permissions-policy"):
        out.append(finding(
            "missing_permissions_policy", "info", "Нет Permissions-Policy",
            "Заголовок отсутствует",
            "Не ограничены доступы к камере/микрофону/геолокации для страницы и её фреймов.",
            "Задайте Permissions-Policy, отключив ненужные возможности (camera=(), microphone=() …).", "headers"))

    if not h.get("x-frame-options") and "frame-ancestors" not in csp_l:
        out.append(finding(
            "missing_frame_protection", "medium", "Нет защиты от clickjacking",
            "Нет ни X-Frame-Options, ни CSP frame-ancestors",
            "Сайт можно встроить в чужой <iframe> и обманом заставить пользователя кликать.",
            "Добавьте X-Frame-Options: DENY или CSP frame-ancestors 'none'.", "headers"))

    # --- Cross-Origin Isolation (COOP / COEP / CORP) — информационно ---
    if not h.get("cross-origin-opener-policy"):
        out.append(finding(
            "missing_coop", "info", "Нет Cross-Origin-Opener-Policy",
            "Заголовок отсутствует",
            "Без COOP другое окно (opener) может делить browsing context — риск side-channel атак.",
            "Добавьте Cross-Origin-Opener-Policy: same-origin.", "headers"))
    if not h.get("cross-origin-resource-policy"):
        out.append(finding(
            "missing_corp", "info", "Нет Cross-Origin-Resource-Policy",
            "Заголовок отсутствует",
            "Без CORP ресурс могут встраивать сторонние сайты (риск утечки через кэш/спектр атак).",
            "Добавьте Cross-Origin-Resource-Policy: same-origin (или same-site).", "headers"))
    if not h.get("cross-origin-embedder-policy"):
        out.append(finding(
            "missing_coep", "info", "Нет Cross-Origin-Embedder-Policy",
            "Заголовок отсутствует",
            "COEP нужен для полноценной cross-origin isolation (SharedArrayBuffer и точные таймеры).",
            "При необходимости добавьте Cross-Origin-Embedder-Policy: require-corp.", "headers"))

    return out
