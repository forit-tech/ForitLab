"""Модель находок и доказательств — фундамент будущего Chaos.

Три РАЗНЫЕ оси (их нельзя смешивать):
* severity — насколько плохо, ЕСЛИ проблема настоящая (INFO…CRITICAL);
* confidence — насколько уверен детектор в своём выводе (LOW/MEDIUM/HIGH);
* verification_status — как далеко зашло доказательство (POTENTIAL/INDICATED/CONFIRMED).

Пример: подозрение на SQLi может быть severity=HIGH, confidence=LOW,
verification=POTENTIAL, а после безопасного подтверждения стать HIGH/HIGH/CONFIRMED.

Инвариант: любой снимок запроса/ответа маскирует секреты ДО сериализации —
Authorization/Cookie/ключи не попадают ни в evidence, ни в отчёт, ни в логи.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_MASK = "***"

# Заголовки, значения которых маскируются целиком.
_SECRET_HEADERS = {
    "authorization",
    "proxy-authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "api-key",
    "x-auth-token",
    "x-amz-security-token",
}
# Параметры запроса, которые маскируются.
_SECRET_QUERY = re.compile(r"(token|api[_-]?key|access[_-]?key|secret|password|passwd|pwd|sig|signature)", re.I)


class Severity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Confidence(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class VerificationStatus(str, Enum):
    POTENTIAL = "potential"
    INDICATED = "indicated"
    CONFIRMED = "confirmed"


def mask_headers(headers: dict[str, str] | None) -> dict[str, str]:
    if not headers:
        return {}
    return {k: (_MASK if k.lower() in _SECRET_HEADERS else v) for k, v in headers.items()}


def mask_url(url: str) -> str:
    """Маскирует userinfo и секретные query-параметры, структуру URL сохраняет."""
    try:
        p = urlparse(url)
    except ValueError:
        return url
    netloc = p.netloc
    if "@" in netloc:  # user:pass@host
        netloc = _MASK + "@" + netloc.rsplit("@", 1)[1]
    query = urlencode(
        [(k, _MASK if _SECRET_QUERY.search(k) else v) for k, v in parse_qsl(p.query, keep_blank_values=True)]
    )
    return urlunparse((p.scheme, netloc, p.path, p.params, query, p.fragment))


@dataclass
class HttpSnapshot:
    method: str
    url: str
    status: int | None = None
    request_headers: dict[str, str] = field(default_factory=dict)
    response_headers: dict[str, str] = field(default_factory=dict)
    body_preview: str = ""
    size: int = 0
    elapsed_ms: float = 0.0

    @classmethod
    def capture(
        cls,
        *,
        method: str,
        url: str,
        status: int | None = None,
        request_headers: dict[str, str] | None = None,
        response_headers: dict[str, str] | None = None,
        body: str = "",
        size: int = 0,
        elapsed_ms: float = 0.0,
        preview_limit: int = 2000,
    ) -> "HttpSnapshot":
        return cls(
            method=method.upper(),
            url=mask_url(url),
            status=status,
            request_headers=mask_headers(request_headers),
            response_headers=mask_headers(response_headers),
            body_preview=body[:preview_limit],
            size=size,
            elapsed_ms=elapsed_ms,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "url": self.url,
            "status": self.status,
            "request_headers": self.request_headers,
            "response_headers": self.response_headers,
            "body_preview": self.body_preview,
            "size": self.size,
            "elapsed_ms": self.elapsed_ms,
        }


@dataclass
class Evidence:
    baseline: HttpSnapshot | None = None
    probe: HttpSnapshot | None = None
    diff: dict[str, Any] | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline": self.baseline.to_dict() if self.baseline else None,
            "probe": self.probe.to_dict() if self.probe else None,
            "diff": self.diff,
            "notes": self.notes,
        }


@dataclass
class Remediation:
    summary: str = ""
    stack_fixes: dict[str, str] = field(default_factory=dict)  # {"nginx": "...", "fastapi": "..."}

    def to_dict(self) -> dict[str, Any]:
        return {"summary": self.summary, "stack_fixes": self.stack_fixes}


@dataclass
class RetestResult:
    status: str  # open | fixed | changed | inconclusive
    checked_at: float = 0.0
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "checked_at": self.checked_at, "notes": self.notes}


@dataclass
class Finding:
    id: str
    title: str
    category: str
    severity: Severity
    confidence: Confidence
    verification_status: VerificationStatus
    target: str = ""
    endpoint: str = ""
    parameter: str = ""
    why: str = ""
    evidence: Evidence = field(default_factory=Evidence)
    reproduction: str = ""
    remediation: Remediation = field(default_factory=Remediation)
    retest: RetestResult | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "category": self.category,
            "severity": self.severity.value,
            "confidence": self.confidence.value,
            "verification_status": self.verification_status.value,
            "target": mask_url(self.target) if self.target else "",
            "endpoint": self.endpoint,
            "parameter": self.parameter,
            "why": self.why,
            "evidence": self.evidence.to_dict(),
            "reproduction": self.reproduction,
            "remediation": self.remediation.to_dict(),
            "retest": self.retest.to_dict() if self.retest else None,
        }
