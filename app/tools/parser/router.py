"""HTTP-слой Web Parser. Субфаза 1a: только INPUT → INSPECT."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ...parser import TOOL_TITLE
from ...parser.dom import backend_info
from ...parser.inspect import inspect as run_inspect

router = APIRouter(prefix="/api/parser", tags=[TOOL_TITLE])


class InspectRequest(BaseModel):
    input: str = Field(description="URL, HTML, JSON или строка cURL", examples=["https://example.com"])


class BackendResponse(BaseModel):
    backend: str
    css: bool
    xpath: bool


@router.get("/backend", response_model=BackendResponse, summary="Активный selector-backend")
def backend() -> BackendResponse:
    return BackendResponse(**backend_info())


@router.post("/inspect", summary="Определить источник и показать сводку")
def inspect(payload: InspectRequest) -> dict:
    return run_inspect(payload.input)
