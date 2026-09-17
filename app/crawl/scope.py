"""Область обхода (scope) и бюджет — общие для Web Parser и будущего Chaos.

Scope НЕ список строк с неявной семантикой. Он однозначно различает:
схему, хост, порт, разрешение поддоменов, отдельно навигацию (страницы/ссылки),
внешние обнаруженные ресурсы (ассеты) и редиректы.

Строгий пример (нужен Chaos): правило `https://example.com:443` НЕ означает
`http://example.com`, `https://api.example.com`, `https://evil.example.com`
или другой порт. Parser может задать более мягкую политику
(`allow_subdomains=True`, `allow_external_resources=True`) — но примитив по
умолчанию строгий.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

_DEFAULT_PORTS = {"http": 80, "https": 443}


def _port_of(scheme: str, port: int | None) -> int:
    return port if port is not None else _DEFAULT_PORTS.get(scheme, 0)


@dataclass(frozen=True)
class Origin:
    scheme: str
    host: str
    port: int

    @classmethod
    def parse(cls, url: str) -> "Origin | None":
        p = urlparse(url)
        if not p.scheme or not p.hostname:
            return None
        return cls(scheme=p.scheme.lower(), host=p.hostname.lower(), port=_port_of(p.scheme.lower(), p.port))


@dataclass(frozen=True)
class HostRule:
    """Разрешённый источник. По умолчанию — точное совпадение всех трёх осей."""

    scheme: str
    host: str
    port: int
    allow_subdomains: bool = False

    @classmethod
    def from_url(cls, url: str, *, allow_subdomains: bool = False) -> "HostRule":
        origin = Origin.parse(url)
        if origin is None:
            raise ValueError(f"не удалось разобрать origin из {url!r}")
        return cls(origin.scheme, origin.host, origin.port, allow_subdomains)

    def matches(self, origin: Origin) -> bool:
        if origin.scheme != self.scheme or origin.port != self.port:
            return False
        if origin.host == self.host:
            return True
        if self.allow_subdomains and origin.host.endswith("." + self.host):
            return True
        return False


@dataclass(frozen=True)
class ScopeDecision:
    allowed: bool
    reason: str


@dataclass
class CrawlScope:
    seeds: list[str]
    allowed: list[HostRule]
    follow_redirects: bool = True
    allow_external_resources: bool = False
    max_depth: int = 2
    max_pages: int = 50
    max_requests: int = 200
    max_bytes: int = 32 * 1024 * 1024
    delay_ms: int = 200
    respect_robots: bool = True

    @classmethod
    def single_origin(cls, url: str, *, allow_subdomains: bool = False, **kwargs: object) -> "CrawlScope":
        rule = HostRule.from_url(url, allow_subdomains=allow_subdomains)
        return cls(seeds=[url], allowed=[rule], **kwargs)  # type: ignore[arg-type]

    def _match(self, url: str) -> tuple[Origin | None, bool]:
        origin = Origin.parse(url)
        if origin is None:
            return None, False
        return origin, any(rule.matches(origin) for rule in self.allowed)

    def allows_navigation(self, url: str) -> ScopeDecision:
        origin, ok = self._match(url)
        if origin is None:
            return ScopeDecision(False, "не удалось разобрать URL")
        if ok:
            return ScopeDecision(True, "в области обхода")
        return ScopeDecision(False, f"origin {origin.scheme}://{origin.host}:{origin.port} вне scope")

    def allows_resource(self, url: str) -> ScopeDecision:
        decision = self.allows_navigation(url)
        if decision.allowed:
            return decision
        if self.allow_external_resources:
            return ScopeDecision(True, "внешний ресурс разрешён политикой")
        return ScopeDecision(False, "внешний ресурс запрещён (allow_external_resources=False)")

    def allows_redirect(self, from_url: str, to_url: str) -> ScopeDecision:
        if not self.follow_redirects:
            return ScopeDecision(False, "редиректы отключены для этого scope")
        return self.allows_navigation(to_url)


@dataclass
class CrawlBudget:
    """Жёсткие потолки. Превысить нельзя — краул останавливается."""

    max_pages: int
    max_requests: int
    max_bytes: int
    pages: int = 0
    requests: int = 0
    bytes: int = 0
    stopped_reason: str = ""

    @classmethod
    def from_scope(cls, scope: CrawlScope) -> "CrawlBudget":
        return cls(max_pages=scope.max_pages, max_requests=scope.max_requests, max_bytes=scope.max_bytes)

    @property
    def exhausted(self) -> bool:
        return bool(self.stopped_reason)

    def can_request(self) -> bool:
        if self.requests >= self.max_requests:
            self.stopped_reason = "исчерпан лимит запросов"
            return False
        if self.bytes >= self.max_bytes:
            self.stopped_reason = "исчерпан лимит объёма"
            return False
        if self.pages >= self.max_pages:
            self.stopped_reason = "исчерпан лимит страниц"
            return False
        return True

    def spend_request(self, byte_count: int = 0) -> None:
        self.requests += 1
        self.bytes += max(0, byte_count)

    def spend_page(self) -> None:
        self.pages += 1
