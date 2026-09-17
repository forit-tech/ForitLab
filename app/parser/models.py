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


# =====================================================================
# 1b — Extraction Engine
# =====================================================================
class SelectorType(str, Enum):
    CSS = "css"
    XPATH = "xpath"


class FieldSource(str, Enum):
    TEXT = "text"
    ATTR = "attr"
    HTML = "html"
    URL = "url"
    IMAGE = "image"
    FILE_URL = "file_url"


class Transform(str, Enum):
    TRIM = "trim"
    NORMALIZE_WS = "normalize_ws"
    REGEX = "regex"
    NUMBER = "number"
    DATE = "date"


class SourceKind(str, Enum):
    REPEATED_DOM = "repeated_dom"
    JSON_LD = "json_ld"
    EMBEDDED_JSON = "embedded_json"
    API = "api"


class Confidence(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class FieldSpec:
    name: str
    selector: str = ""
    selector_type: SelectorType = SelectorType.CSS
    source: FieldSource = FieldSource.TEXT
    attr_name: str | None = None
    transform: Transform | None = None
    transform_arg: str | None = None

    @classmethod
    def from_dict(cls, d: dict) -> "FieldSpec":
        return cls(
            name=str(d.get("name", "")).strip(),
            selector=str(d.get("selector", "")),
            selector_type=SelectorType(d.get("selector_type", "css")),
            source=FieldSource(d.get("source", "text")),
            attr_name=d.get("attr_name"),
            transform=Transform(d["transform"]) if d.get("transform") else None,
            transform_arg=d.get("transform_arg"),
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "selector": self.selector,
            "selector_type": self.selector_type.value,
            "source": self.source.value,
            "attr_name": self.attr_name,
            "transform": self.transform.value if self.transform else None,
            "transform_arg": self.transform_arg,
        }


@dataclass
class ExtractionSchema:
    source_kind: SourceKind
    fields: list[FieldSpec] = field(default_factory=list)
    container_selector: str = ""
    container_type: SelectorType = SelectorType.CSS
    json_pointer: str | None = None  # для json_ld / embedded_json

    @classmethod
    def from_dict(cls, d: dict) -> "ExtractionSchema":
        return cls(
            source_kind=SourceKind(d.get("source_kind", "repeated_dom")),
            fields=[FieldSpec.from_dict(f) for f in d.get("fields", [])],
            container_selector=d.get("container_selector", ""),
            container_type=SelectorType(d.get("container_type", "css")),
            json_pointer=d.get("json_pointer"),
        )

    def to_dict(self) -> dict:
        return {
            "source_kind": self.source_kind.value,
            "container_selector": self.container_selector,
            "container_type": self.container_type.value,
            "json_pointer": self.json_pointer,
            "fields": [f.to_dict() for f in self.fields],
        }


@dataclass
class AssetRef:
    field: str
    url: str

    def to_dict(self) -> dict:
        return {"field": self.field, "url": self.url}


@dataclass
class SourceCandidate:
    kind: SourceKind
    location: str
    record_count: int | None
    fields: list[str]
    structured: bool
    pagination_detected: bool
    stable_ids: bool
    evidence: list[str]
    confidence: Confidence
    limitations: list[str] = field(default_factory=list)
    schema: ExtractionSchema | None = None  # предложенная схема для этого источника

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.value,
            "location": mask_url(self.location) if self.location.startswith("http") else self.location,
            "record_count": self.record_count,
            "fields": self.fields,
            "structured": self.structured,
            "pagination_detected": self.pagination_detected,
            "stable_ids": self.stable_ids,
            "evidence": self.evidence,
            "confidence": self.confidence.value,
            "limitations": self.limitations,
            "schema": self.schema.to_dict() if self.schema else None,
        }


@dataclass
class SourceRecommendation:
    selected: SourceCandidate | None
    reason: str
    confidence: Confidence
    alternatives: list[SourceCandidate] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "selected": self.selected.to_dict() if self.selected else None,
            "reason": self.reason,
            "confidence": self.confidence.value,
            "alternatives": [c.to_dict() for c in self.alternatives],
        }
