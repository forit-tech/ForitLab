"""Классификация адресов и синтаксическая проверка URL — сердце SSRF-защиты.

Здесь нет сети: только правила «куда нельзя». Резолв делает :mod:`app.net.resolver`,
а связывает всё воедино :mod:`app.net.client`. Разделение нужно, чтобы правила
можно было проверить детерминированно, а резолвер подменить в тестах (rebinding).

Инвариант: наружу выпускаем только публичные http/https на портах 80/443.
Всё остальное — приватные сети, loopback, link-local (включая cloud-metadata
169.254.169.254), multicast, зарезервированное, неглобальное, IPv4-mapped IPv6 —
режется. Проверяются РЕЗОЛВНУТЫЕ адреса, а не текст хоста: `internal.example.com`
и `http://2130706433/` (десятичная запись 127.0.0.1) резолвятся во внутренние
адреса и отсекаются именно на этом шаге.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse, urlunparse

ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PORTS = {80, 443, None}


def _candidates(addr: ipaddress._BaseAddress) -> list[ipaddress._BaseAddress]:
    """Сам адрес плюс встроенный IPv4, если это mapped/6to4-обёртка."""
    out: list[ipaddress._BaseAddress] = [addr]
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped is not None:
            out.append(addr.ipv4_mapped)
        if addr.sixtofour is not None:
            out.append(addr.sixtofour)
    return out


def classify_ip(ip: str) -> tuple[bool, str]:
    """(safe, reason). safe=True только для глобально маршрутизируемых адресов."""
    cleaned = ip.split("%", 1)[0]  # убираем zone id вида fe80::1%eth0
    try:
        addr = ipaddress.ip_address(cleaned)
    except ValueError:
        return False, f"непонятный адрес: {ip}"

    for candidate in _candidates(addr):
        if candidate.is_loopback:
            return False, f"адрес {candidate} — loopback"
        if candidate.is_private:
            return False, f"адрес {candidate} принадлежит внутренней сети"
        if candidate.is_link_local:
            return False, f"адрес {candidate} — link-local (в т.ч. cloud metadata)"
        if candidate.is_multicast:
            return False, f"адрес {candidate} — multicast"
        if candidate.is_reserved:
            return False, f"адрес {candidate} зарезервирован"
        if candidate.is_unspecified:
            return False, f"адрес {candidate} — unspecified"
        if not candidate.is_global:
            return False, f"адрес {candidate} не является глобально маршрутизируемым"
    return True, ""


def check_syntax(raw_url: str) -> "tuple[str, object]":
    """Проверяет схему, порт, отсутствие user:pass и наличие хоста.

    Возвращает (нормализованный_url, parsed). Бросает UnsafeUrlError.
    Резолв тут НЕ делается — это отдельный шаг с резолвером.
    """
    from .errors import UnsafeUrlError

    parsed = urlparse(raw_url.strip())
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise UnsafeUrlError("Разрешены только http и https", {"scheme": parsed.scheme or "(пусто)"})
    if not parsed.hostname:
        raise UnsafeUrlError("В ссылке нет имени хоста", {"url": raw_url[:200]})
    try:
        port = parsed.port
    except ValueError as exc:
        raise UnsafeUrlError("Некорректный порт в ссылке", {"url": raw_url[:200]}) from exc
    from ..config import settings

    if port not in ALLOWED_PORTS and port not in settings.scrape_extra_ports:
        raise UnsafeUrlError("Разрешены только стандартные порты 80 и 443", {"port": port})
    if parsed.username or parsed.password:
        raise UnsafeUrlError("Ссылки с логином и паролем не обрабатываются")
    return urlunparse(parsed), parsed
