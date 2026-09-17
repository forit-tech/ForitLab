"""Базовые модели Web Parser.

Здесь только данные и их сериализация. Сеть — через :mod:`app.net`, разбор HTML —
через :mod:`app.parser.dom`. `RequestSpec` намеренно переносимый: позже его же
получит Chaos («Send to Chaos») без переписывания Parser.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from ..findings import mask_headers, mask_url


class InputKind(str, Enum):
    URL = "url"
    HTML = "html"
    JSON = "json"
    CURL = "curl"
    UNKNOWN = "unknown"


class SourceType(str, Enum):
    HTML = "html"
    JSON = "json"
    JSONL = "jsonl"
    XML = "xml"
    CSV = "csv"
    TEXT = "text"
    BINARY = "binary"
    UNKNOWN = "unknown"


@dataclass
class RequestSpec:
    """Переносимое описание HTTP-запроса (роднит Parser и будущий Chaos)."""

    method: str = "GET"
    url: str = ""
    query: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    cookies: dict[str, str] = field(default_factory=dict)
    body: str | None = None
    content_type: str | None = None

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "url": self.url,
            "query": self.query,
            "headers": self.headers,
            "cookies": self.cookies,
            "body": self.body,
            "content_type": self.content_type,
        }

    def to_masked(self) -> dict:
        """Безопасно для UI/логов: секреты в заголовках, куках и URL скрыты."""
        return {
            "method": self.method,
            "url": mask_url(self.url),
            "query": self.query,
            "headers": mask_headers(self.headers),
            "cookies": {k: "***" for k in self.cookies},
            "has_body": self.body is not None,
            "body_size": len(self.body) if self.body else 0,
            "content_type": self.content_type,
        }


@dataclass
class InputSpec:
    kind: InputKind
    raw: str
    url: str | None = None
    body: str | None = None
    request: RequestSpec | None = None

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.value,
            "url": self.url,
            "has_body": self.body is not None,
            "request": self.request.to_masked() if self.request else None,
        }


@dataclass
class RedirectHopView:
    url: str
    status: int
    location: str


@dataclass
class ResponseView:
    """Наблюдаемый ответ. Строится из :class:`app.net.HttpResponse`."""

    url: str
    final_url: str
    method: str
    status: int
    content_type: str
    charset: str
    source_type: SourceType
    size: int
    elapsed_ms: float
    resolved_ip: str
    truncated: bool
    headers: dict[str, str] = field(default_factory=dict)  # set-cookie маскируется
    cookie_count: int = 0
    redirect_chain: list[RedirectHopView] = field(default_factory=list)
    body_preview: str = ""

    def to_dict(self) -> dict:
        return {
            "url": mask_url(self.url),
            "final_url": mask_url(self.final_url),
            "method": self.method,
            "status": self.status,
            "content_type": self.content_type,
            "charset": self.charset,
            "source_type": self.source_type.value,
            "size": self.size,
            "elapsed_ms": self.elapsed_ms,
            "resolved_ip": self.resolved_ip,
            "truncated": self.truncated,
            "headers": self.headers,
            "cookie_count": self.cookie_count,
            "redirect_chain": [{"url": mask_url(h.url), "status": h.status, "location": mask_url(h.location)} for h in self.redirect_chain],
            "body_preview": self.body_preview,
        }
