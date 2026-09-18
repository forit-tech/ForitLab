"""Движок схемы и редиректов.

`check_scheme` — базовый вывод по итоговой схеме и по тому, редиректит ли http://
на https:// (использует отдельный http-пробник). `check_redirect_chain` — разбор
цепочки редиректов (loop, downgrade https→http, cross-origin, слишком длинная).
Оба безопасны при пустых входных данных.
"""

from __future__ import annotations

from urllib.parse import urlparse

from .models import finding

_MAX_REDIRECTS = 8


def _origin(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.hostname}:{p.port or ''}"


def check_scheme(https: bool, scheme: str, http_probe) -> list[dict]:
    """https — итог https; scheme — итоговая схема; http_probe — ответ на http:// (или None)."""
    out: list[dict] = []
    if not https:
        out.append(finding(
            "no_https", "high", "Сайт доступен без HTTPS",
            f"Итоговая схема: {scheme}://",
            "Трафик передаётся в открытом виде — его можно перехватить и подменить.",
            "Включите HTTPS (валидный TLS-сертификат) и переведите сайт на него.", "https"))
    elif http_probe is not None and urlparse(http_probe.final_url).scheme != "https":
        out.append(finding(
            "no_http_redirect", "medium", "HTTP не редиректит на HTTPS",
            f"http:// отвечает {http_probe.status}, остаётся на {urlparse(http_probe.final_url).scheme}://",
            "Пользователь, зашедший по http://, останется на незащищённом соединении.",
            "Настройте постоянный редирект 301 c http:// на https://.", "https"))
    return out


def check_redirect_chain(chain, requested_url: str, final_url: str) -> list[dict]:
    """chain — список hop'ов с полями .url/.status/.location (или dict). Пустой → нет findings."""
    out: list[dict] = []
    hops = list(chain or [])

    def _get(hop, key):
        return getattr(hop, key, None) if not isinstance(hop, dict) else hop.get(key)

    if not hops:
        return out

    # downgrade https -> http на любом хопе
    for hop in hops:
        src = _get(hop, "url") or ""
        loc = _get(hop, "location") or ""
        target = urlparse(loc)
        if urlparse(src).scheme == "https" and target.scheme == "http":
            out.append(finding(
                "redirect_downgrade", "high", "Редирект понижает HTTPS → HTTP",
                f"{src} → {loc}",
                "Редирект с защищённой на незащищённую схему выкидывает пользователя в открытый канал.",
                "Не редиректьте с https:// на http://; держите весь путь на HTTPS.", "redirects"))
            break

    # loop: повтор одного и того же url в цепочке
    seen = set()
    for hop in hops:
        src = _get(hop, "url") or ""
        if src in seen:
            out.append(finding(
                "redirect_loop", "high", "Цикл редиректов",
                f"URL повторяется в цепочке: {src}",
                "Циклический редирект делает страницу недоступной и указывает на ошибку конфигурации.",
                "Исправьте правила редиректов, чтобы цепочка сходилась к одному финальному URL.", "redirects"))
            break
        seen.add(src)

    if len(hops) >= _MAX_REDIRECTS:
        out.append(finding(
            "redirect_too_many", "low", "Слишком длинная цепочка редиректов",
            f"Хопов: {len(hops)}",
            "Длинные цепочки редиректов замедляют загрузку и усложняют аудит поведения.",
            "Сократите число редиректов до 1–2.", "redirects"))

    if _origin(requested_url) != _origin(final_url) and urlparse(requested_url).hostname:
        out.append(finding(
            "redirect_cross_origin", "info", "Редирект на другой origin",
            f"{_origin(requested_url)} → {_origin(final_url)}",
            "Итоговый origin отличается от запрошенного — важно понимать, кому в итоге доверяет пользователь.",
            "Убедитесь, что финальный origin ожидаем и доверенный.", "redirects"))

    return out
