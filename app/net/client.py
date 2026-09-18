"""HTTP-клиент с SSRF-защитой и IP-pinning.

Ключевой инвариант против DNS rebinding / TOCTOU: имя резолвится ОДИН раз,
все полученные адреса проверяются, и соединение открывается ИМЕННО к тому IP,
который прошёл проверку. Второго независимого резолва (как было в urllib) нет.

При этом TLS не ослабляется: коннектимся к запиненному IP, но `server_hostname`
для SNI и проверки сертификата остаётся исходным доменом, а заголовок Host
формирует http.client из домена. То есть pinning не отключает hostname
verification.

Каждый redirect-hop проходит полную проверку заново (схема/порт/резолв/адреса).
"""

from __future__ import annotations

import codecs
import gzip
import http.client
import socket
import ssl
import time
import zlib
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

from ..config import settings
from .errors import FetchError, RobotsDisallowedError, UnsafeUrlError
from .resolver import Resolver, ResolvedAddr, SystemResolver
from .ssrf import check_syntax, classify_ip

_REDIRECT_CODES = {301, 302, 303, 307, 308}


@dataclass
class Hop:
    url: str
    status: int
    location: str


@dataclass
class HttpResponse:
    url: str
    final_url: str
    status: int
    method: str
    content_type: str
    charset: str
    body: bytes
    text: str
    elapsed_ms: float
    resolved_ip: str
    headers: dict[str, str] = field(default_factory=dict)
    cookies: list[str] = field(default_factory=list)
    redirect_chain: list[Hop] = field(default_factory=list)
    truncated: bool = False


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


def _valid_charset(name: str) -> str | None:
    """Вернуть имя кодировки, если Python её знает, иначе None."""
    name = name.strip().strip("\"'")[:40]
    if not name:
        return None
    try:
        codecs.lookup(name)
        return name
    except (LookupError, ValueError):
        return None


def _charset_from(content_type: str, body: bytes) -> str:
    """Определить кодировку из Content-Type или <meta>. Всегда валидный кодек.

    Важно: значение читаем ДО первого разделителя, а не фильтруем весь буфер —
    иначе на странице без charset в заголовке (напр. python http.server) в имя
    кодировки попадал весь текст и .decode() падал LookupError.
    """
    if "charset=" in content_type:
        raw = content_type.split("charset=", 1)[1].split(";")[0]
        valid = _valid_charset(raw)
        if valid:
            return valid
    head = body[:2048].lower()
    for marker in (b'charset="', b"charset='", b"charset="):
        position = head.find(marker)
        if position == -1:
            continue
        tail = head[position + len(marker) :]
        end = 0
        while end < len(tail) and tail[end] not in b"\"' >/;":
            end += 1
        valid = _valid_charset(tail[:end].decode("ascii", "ignore"))
        if valid:
            return valid
    return "utf-8"


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """HTTP-соединение, которое коннектится к заранее выбранному IP."""

    def __init__(self, host: str, ip: str, port: int, timeout: float) -> None:
        super().__init__(host, port=port, timeout=timeout)
        self._pinned_ip = ip

    def connect(self) -> None:  # noqa: D102
        self.sock = socket.create_connection((self._pinned_ip, self.port), self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS-соединение к запиненному IP с сохранением SNI и проверки сертификата."""

    def __init__(self, host: str, ip: str, port: int, timeout: float, context: ssl.SSLContext) -> None:
        super().__init__(host, port=port, timeout=timeout, context=context)
        self._pinned_ip = ip

    def connect(self) -> None:  # noqa: D102
        sock = socket.create_connection((self._pinned_ip, self.port), self.timeout)
        # server_hostname = self.host (домен), НЕ IP: SNI и проверка сертификата
        # идут по имени. Контекст создан create_default_context() → verify включён.
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class HttpClient:
    """Единственная дверь наружу. Инструменты не должны ходить в сеть мимо неё."""

    def __init__(
        self,
        *,
        resolver: Resolver | None = None,
        allow_private: bool | None = None,
        user_agent: str | None = None,
        timeout: float | None = None,
        max_bytes: int | None = None,
        max_redirects: int | None = None,
        respect_robots: bool | None = None,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self._resolver = resolver or SystemResolver()
        self._allow_private = settings.scrape_allow_private if allow_private is None else allow_private
        self._user_agent = user_agent or settings.scrape_user_agent
        self._timeout = settings.scrape_timeout_s if timeout is None else timeout
        self._max_bytes = settings.scrape_max_bytes if max_bytes is None else max_bytes
        self._max_redirects = settings.scrape_max_redirects if max_redirects is None else max_redirects
        self._respect_robots_default = (
            settings.scrape_respect_robots if respect_robots is None else respect_robots
        )
        self._ssl_context = ssl_context or ssl.create_default_context()

    # -- защита адреса --------------------------------------------------
    def _resolve_and_pin(self, host: str, port: int | None) -> ResolvedAddr:
        try:
            addrs = self._resolver.resolve(host, port)
        except LookupError as exc:
            raise UnsafeUrlError(f"Не удалось разрезолвить имя: {exc}", {"host": host}) from exc
        if not addrs:
            raise UnsafeUrlError("Имя не резолвится ни в один адрес", {"host": host})
        if not self._allow_private:
            for addr in addrs:
                safe, reason = classify_ip(addr.ip)
                if not safe:
                    raise UnsafeUrlError(
                        f"Адрес отклонён: {reason}",
                        {"host": host, "hint": "Защита от SSRF; локально — FORIT_SCRAPE_ALLOW_PRIVATE."},
                    )
        return addrs[0]

    def _open(self, scheme: str, host: str, port: int | None, ip: str) -> http.client.HTTPConnection:
        if scheme == "https":
            return _PinnedHTTPSConnection(host, ip, port or 443, self._timeout, self._ssl_context)
        return _PinnedHTTPConnection(host, ip, port or 80, self._timeout)

    # -- robots ---------------------------------------------------------
    def robots_allows(self, url: str) -> tuple[bool, str]:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        try:
            resp = self.request("GET", robots_url, respect_robots=False, max_bytes=512 * 1024)
        except (UnsafeUrlError, FetchError):
            return True, "robots.txt недоступен, считаем что ограничений нет"
        if resp.status >= 400:
            return True, "robots.txt недоступен, считаем что ограничений нет"
        parser = RobotFileParser()
        parser.parse(resp.text.splitlines())
        allowed = parser.can_fetch(self._user_agent, url)
        return allowed, "robots.txt разрешает" if allowed else "robots.txt запрещает этот путь"

    # -- основной запрос ------------------------------------------------
    def request(
        self,
        method: str = "GET",
        url: str = "",
        *,
        headers: dict[str, str] | None = None,
        body: bytes | str | None = None,
        respect_robots: bool | None = None,
        timeout: float | None = None,
        max_bytes: int | None = None,
    ) -> HttpResponse:
        method = method.upper()
        max_bytes = self._max_bytes if max_bytes is None else max_bytes
        respect = self._respect_robots_default if respect_robots is None else respect_robots

        normalized, _ = check_syntax(url)
        if respect:
            allowed, reason = self.robots_allows(normalized)
            if not allowed:
                raise RobotsDisallowedError(
                    f"Страница закрыта для роботов: {reason}",
                    {"url": normalized, "hint": "Это правило сайта, а не наше ограничение."},
                )

        started = time.perf_counter()
        current = normalized
        redirects: list[Hop] = []
        last_ip = ""

        for _ in range(self._max_redirects + 1):
            # Каждый hop (в т.ч. редиректный urljoin) проходит ту же нормализацию:
            # хост → IDNA, path/query → percent-encoded. current обновляем, чтобы
            # final_url и redirect_chain тоже были ASCII-безопасны.
            current, parsed = check_syntax(current)
            pinned = self._resolve_and_pin(parsed.hostname, parsed.port)
            last_ip = pinned.ip
            conn = self._open(parsed.scheme, parsed.hostname, parsed.port, pinned.ip)

            request_headers = self._build_headers(headers)
            path = parsed.path or "/"
            if parsed.query:
                path = f"{path}?{parsed.query}"
            try:
                conn.request(method, path, body=body, headers=request_headers)
                response = conn.getresponse()
                status = response.status
                raw_headers = response.getheaders()
                if status in _REDIRECT_CODES and method not in {"HEAD", "OPTIONS"}:
                    location = response.getheader("Location")
                    response.read()
                    conn.close()
                    if location and len(redirects) < self._max_redirects:
                        redirects.append(Hop(url=current, status=status, location=location))
                        current = urljoin(current, location)
                        continue
                    # редирект без Location или лимит исчерпан — отдаём как финал
                    return self._build_response(
                        url, current, method, status, raw_headers, b"", started, last_ip, redirects, False
                    )
                if method == "HEAD":
                    response.read()
                    conn.close()
                    return self._build_response(
                        url, current, method, status, raw_headers, b"", started, last_ip, redirects, False
                    )
                raw = response.read(max_bytes + 1)
                conn.close()
                truncated = len(raw) > max_bytes
                raw = raw[:max_bytes]
                return self._build_response(
                    url, current, method, status, raw_headers, raw, started, last_ip, redirects, truncated
                )
            except (UnsafeUrlError, RobotsDisallowedError):
                conn.close()
                raise
            except (TimeoutError, socket.timeout) as exc:
                conn.close()
                raise FetchError(f"Таймаут {self._timeout:g} с", {"url": current}) from exc
            except (ssl.SSLError, OSError, http.client.HTTPException) as exc:
                conn.close()
                raise FetchError(
                    f"Не удалось соединиться: {exc}",
                    {
                        "url": current,
                        "hint": "На shared hosting исходящие соединения часто закрыты.",
                    },
                ) from exc

        raise FetchError(
            f"Слишком много редиректов (больше {self._max_redirects})",
            {"chain": [h.url for h in redirects]},
        )

    def _build_headers(self, extra: dict[str, str] | None) -> dict[str, str]:
        base = {
            "User-Agent": self._user_agent,
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "ru,en;q=0.8",
        }
        if extra:
            base.update(extra)
        return base

    def _build_response(
        self,
        url: str,
        final_url: str,
        method: str,
        status: int,
        raw_headers: list[tuple[str, str]],
        raw: bytes,
        started: float,
        ip: str,
        redirects: list[Hop],
        truncated: bool,
    ) -> HttpResponse:
        headers = {key.lower(): value for key, value in raw_headers}
        cookies = [value for key, value in raw_headers if key.lower() == "set-cookie"]
        body = _decompress(raw, headers.get("content-encoding", "").lower())
        content_type = headers.get("content-type", "")
        charset = _charset_from(content_type, body)
        return HttpResponse(
            url=url,
            final_url=final_url,
            status=status,
            method=method,
            content_type=content_type.split(";")[0].strip() or "unknown",
            charset=charset,
            body=body,
            text=body.decode(charset, "replace"),
            elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
            resolved_ip=ip,
            headers=headers,
            cookies=cookies,
            redirect_chain=redirects,
            truncated=truncated,
        )
