"""HTTP-слой нового Chaos (Passive Security Check). Namespace /api/chaos/v2.

Старый /api/chaos/respond (генератор плохих ответов) не трогаем — он остаётся
на прежнем месте. Новый Chaos живёт в отдельном namespace.
"""

from __future__ import annotations

from urllib.parse import urlparse, urlunparse

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..net import HttpClient
from ..net.errors import FetchError, UnsafeUrlError
from .passive import run_checks

router = APIRouter(prefix="/api/chaos/v2", tags=["Chaos"])


class CheckRequest(BaseModel):
    url: str = Field(examples=["https://example.com"])


@router.post("/check", summary="Пассивная проверка безопасности по URL (Chaos 1a)")
def check(payload: CheckRequest) -> dict:
    url = payload.url.strip()
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url  # по умолчанию пробуем https
    try:
        primary = HttpClient().request("GET", url, respect_robots=False)
    except (UnsafeUrlError, FetchError) as exc:
        return {"error": exc.message, "detail": exc.detail}

    # если итог https — отдельно проверяем, редиректит ли http:// на https
    http_probe = None
    parsed = urlparse(primary.final_url)
    if parsed.scheme == "https":
        http_url = urlunparse(("http", parsed.netloc, parsed.path or "/", "", "", ""))
        try:
            http_probe = HttpClient().request("GET", http_url, respect_robots=False)
        except (UnsafeUrlError, FetchError):
            http_probe = None

    return run_checks(primary, http_probe, url)
