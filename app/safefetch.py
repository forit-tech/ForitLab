"""Единый безопасный слой исходящих запросов Forit Lab.

Здесь живут SSRF-защита, лимиты и robots.txt. Слоем пользуются и
Web Harvester, и API Finder, и — в будущем — HTTP Microscope: правила
безопасности должны быть в одном месте, а не копироваться в каждый инструмент.

Исходное назначение — загрузка страницы:

Главное здесь — не скорость, а то, что сервис нельзя использовать как
прокси во внутреннюю сеть хостера. Любой адрес проверяется до соединения,
и каждый редирект проверяется заново.
"""

from __future__ import annotations

import gzip
import ipaddress
import socket
import time
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

from .config import settings
from .errors import AppError

ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PORTS = {80, 443, None}


class UnsafeUrlError(AppError):
    """Адрес не прошёл проверку — запрос даже не отправляется."""

    status_code = 400
    code = "unsafe_url"


class FetchError(AppError):
    status_code = 502
    code = "fetch_failed"


class RobotsDisallowedError(AppError):
    status_code = 403
    code = "robots_disallowed"


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    content_type: str
    charset: str
    body: bytes
    text: str
    elapsed_ms: float
    redirects: list[str] = field(default_factory=list)
    truncated: bool = False
    headers: dict[str, str] = field(default_factory=dict)


def _is_public_address(host: str) -> tuple[bool, str]:
    """Резолвим имя и проверяем каждый полученный адрес.

    Проверять сам текст URL бесполезно: `internal.example.com` спокойно
    указывает на 10.0.0.1, а `http://127.0.0.1.nip.io` — на loopback.
    """
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        return False, f"не удалось разрезолвить имя: {exc.strerror or exc}"

    for info in infos:
        raw = info[4][0]
        try:
            address = ipaddress.ip_address(raw)
        except ValueError:
            return False, f"непонятный адрес: {raw}"
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        ):
            return False, f"адрес {raw} принадлежит внутренней сети"
    return True, ""


def validate_url(raw_url: str) -> str:
    """Проверяет схему, порт и адрес назначения. Возвращает нормализованный URL."""
    parsed = urlparse(raw_url.strip())

    if parsed.scheme not in ALLOWED_SCHEMES:
        raise UnsafeUrlError(
            "Разрешены только http и https",
            {"scheme": parsed.scheme or "(пусто)"},
        )
    if not parsed.hostname:
        raise UnsafeUrlError("В ссылке нет имени хоста", {"url": raw_url[:200]})
    if parsed.port not in ALLOWED_PORTS:
        raise UnsafeUrlError(
            "Разрешены только стандартные порты 80 и 443",
            {"port": parsed.port},
        )
    if parsed.username or parsed.password:
        raise UnsafeUrlError("Ссылки с логином и паролем не обрабатываются")

    if not settings.scrape_allow_private:
        public, reason = _is_public_address(parsed.hostname)
        if not public:
            raise UnsafeUrlError(
                f"Адрес отклонён: {reason}",
                {
                    "host": parsed.hostname,
                    "hint": "Защита от SSRF. Для локальных адресов есть FORIT_SCRAPE_ALLOW_PRIVATE.",
                },
            )

    return urlunparse(parsed)


def robots_allows(url: str) -> tuple[bool, str]:
    """Спрашиваем robots.txt. Недоступный robots.txt трактуем как разрешение."""
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    parser = RobotFileParser()
    request = urllib.request.Request(
        robots_url, headers={"User-Agent": settings.scrape_user_agent}
    )
    try:
        with urllib.request.urlopen(request, timeout=min(settings.scrape_timeout_s, 5.0)) as response:
            content = response.read(512 * 1024).decode("utf-8", "replace")
        parser.parse(content.splitlines())
    except Exception:
        # Нет robots.txt или он недоступен — это не запрет.
        return True, "robots.txt недоступен, считаем что ограничений нет"

    allowed = parser.can_fetch(settings.scrape_user_agent, url)
    return allowed, "robots.txt разрешает" if allowed else "robots.txt запрещает этот путь"


def _decompress(body: bytes, encoding: str) -> bytes:
    if encoding == "gzip":
        try:
            return gzip.decompress(body)
        except (OSError, zlib.error):
            return body
    if encoding == "deflate":
        try:
            return zlib.decompress(body)
        except zlib.error:
            try:
                return zlib.decompress(body, -zlib.MAX_WBITS)
            except zlib.error:
                return body
    return body


def _charset_from(content_type: str, body: bytes) -> str:
    if "charset=" in content_type:
        charset = content_type.split("charset=", 1)[1].split(";")[0].strip().strip('"')
        if charset:
            return charset
    head = body[:2048].lower()
    for marker in (b'charset="', b"charset='", b"charset="):
        position = head.find(marker)
        if position != -1:
            tail = head[position + len(marker) :]
            value = bytes(ch for ch in tail if ch not in b"\"' >/;").decode("ascii", "ignore")
            if value:
                return value[:32]
    return "utf-8"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Редиректы обрабатываем вручную: каждый новый адрес нужно проверить."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N802, D102
        return None


def fetch(url: str, *, respect_robots: bool | None = None) -> FetchResult:
    respect = settings.scrape_respect_robots if respect_robots is None else respect_robots
    current = validate_url(url)

    if respect:
        allowed, reason = robots_allows(current)
        if not allowed:
            raise RobotsDisallowedError(
                f"Страница закрыта для роботов: {reason}",
                {"url": current, "hint": "Это правило сайта, а не наше ограничение."},
            )

    opener = urllib.request.build_opener(_NoRedirect)
    redirects: list[str] = []
    started = time.perf_counter()

    for _ in range(settings.scrape_max_redirects + 1):
        request = urllib.request.Request(
            current,
            headers={
                "User-Agent": settings.scrape_user_agent,
                "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
                "Accept-Encoding": "gzip, deflate",
                "Accept-Language": "ru,en;q=0.8",
            },
        )
        try:
            response = opener.open(request, timeout=settings.scrape_timeout_s)
        except urllib.error.HTTPError as exc:
            # Редирект приходит сюда, потому что обработчик их не выполняет.
            if exc.code in {301, 302, 303, 307, 308}:
                location = exc.headers.get("Location")
                if not location:
                    raise FetchError("Редирект без заголовка Location", {"status": exc.code}) from exc
                current = validate_url(urljoin(current, location))
                redirects.append(current)
                exc.close()
                continue
            raise FetchError(
                f"Сайт ответил {exc.code} {exc.reason}",
                {"status": exc.code, "url": current},
            ) from exc
        except urllib.error.URLError as exc:
            raise FetchError(
                f"Не удалось соединиться: {exc.reason}",
                {
                    "url": current,
                    "hint": (
                        "На бесплатном shared hosting исходящие соединения часто закрыты. "
                        "Проверьте /api/scrape/self-test."
                    ),
                },
            ) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise FetchError(
                f"Таймаут {settings.scrape_timeout_s:g} с", {"url": current}
            ) from exc

        with response:
            limit = settings.scrape_max_bytes
            raw = response.read(limit + 1)
            truncated = len(raw) > limit
            raw = raw[:limit]
            headers = {key.lower(): value for key, value in response.headers.items()}
            body = _decompress(raw, headers.get("content-encoding", "").lower())
            content_type = headers.get("content-type", "")
            charset = _charset_from(content_type, body)

            return FetchResult(
                url=url,
                final_url=current,
                status=response.status,
                content_type=content_type.split(";")[0].strip() or "unknown",
                charset=charset,
                body=body,
                text=body.decode(charset, "replace"),
                elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
                redirects=redirects,
                truncated=truncated,
                headers=headers,
            )

    raise FetchError(
        f"Слишком много редиректов (больше {settings.scrape_max_redirects})",
        {"chain": redirects},
    )
