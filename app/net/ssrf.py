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
from urllib.parse import quote, urlsplit, urlunsplit

ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PORTS = {80, 443, None}

# RFC 3986 pchar + "/" + "%": оставляем уже-экранированные %XX как есть (без
# двойного кодирования), а сырой не-ASCII превращаем в percent-encoded UTF-8.
_PATH_SAFE = "/%:@-._~!$&'()*+,;="
# В query дополнительно разрешены "?", "/" и разделители пар "&"/"=".
_QUERY_SAFE = _PATH_SAFE + "?/&="


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


def _idna_host(host: str) -> str:
    """Хост → ASCII: IDNA для доменных имён, IP-литералы и ASCII отдаём как есть.

    SNI и заголовок Host требуют ASCII (A-label), поэтому Unicode-домен
    (`мойсайт.рф`) переводим в `xn--...`. IP-литералы уже ASCII.
    """
    from .errors import UnsafeUrlError

    try:
        host.encode("ascii")
        return host  # уже ASCII (в т.ч. IPv4/IPv6-литералы)
    except UnicodeEncodeError:
        pass
    try:
        # Кодек 'idna' сам разбивает по точкам и делает ToASCII для каждой метки.
        return host.encode("idna").decode("ascii")
    except (UnicodeError, ValueError) as exc:
        raise UnsafeUrlError(
            "Не удалось преобразовать доменное имя (IDNA)",
            {"host": host[:120]},
        ) from exc


def check_syntax(raw_url: str) -> "tuple[str, object]":
    """Проверяет схему/порт/хост и нормализует URL до ASCII-безопасного вида.

    Возвращает (нормализованный_url, parsed). Нормализация:
    - хост → IDNA (ASCII A-label);
    - path/query → percent-encoded UTF-8 без двойного кодирования уже-%XX;
    - fragment отбрасывается (в HTTP-запрос он не уходит);
    - порт и userinfo проверяются как раньше.

    Резолв тут НЕ делается — это отдельный шаг с резолвером. `parsed` в ответе
    получается разбором уже нормализованного URL, поэтому `parsed.hostname`
    гарантированно ASCII (то, что нужно резолверу и SNI).
    Бросает UnsafeUrlError.
    """
    from .errors import UnsafeUrlError

    split = urlsplit(raw_url.strip())
    if split.scheme not in ALLOWED_SCHEMES:
        raise UnsafeUrlError("Разрешены только http и https", {"scheme": split.scheme or "(пусто)"})
    if not split.hostname:
        raise UnsafeUrlError("В ссылке нет имени хоста", {"url": raw_url[:200]})
    try:
        port = split.port
    except ValueError as exc:
        raise UnsafeUrlError("Некорректный порт в ссылке", {"url": raw_url[:200]}) from exc
    from ..config import settings

    if port not in ALLOWED_PORTS and port not in settings.scrape_extra_ports:
        raise UnsafeUrlError("Разрешены только стандартные порты 80 и 443", {"port": port})
    if split.username or split.password:
        raise UnsafeUrlError("Ссылки с логином и паролем не обрабатываются")

    ascii_host = _idna_host(split.hostname)
    netloc = f"[{ascii_host}]" if ":" in ascii_host else ascii_host  # IPv6-литерал в скобках
    if port is not None:
        netloc = f"{netloc}:{port}"

    path = quote(split.path, safe=_PATH_SAFE)
    query = quote(split.query, safe=_QUERY_SAFE) if split.query else ""
    normalized = urlunsplit((split.scheme, netloc, path, query, ""))  # fragment отброшен
    return normalized, urlsplit(normalized)
