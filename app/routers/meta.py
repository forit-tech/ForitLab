"""Служебные ручки: корень, healthcheck, диагностика окружения, каталог инструментов."""

from __future__ import annotations

import os
import platform
import sys
import time
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version

from fastapi import APIRouter

from .. import __service__, __version__
from ..config import settings
from ..deps import PROCESS_STARTED_AT, get_store
from ..registry import TOOLS
from ..schemas import HealthResponse, ServiceInfo, StatusResponse, ToolInfo

router = APIRouter(tags=["Service"])
#: Диагностика вынесена отдельно: на проде её можно просто не подключать.
status_router = APIRouter(tags=["Service"])

_TRACKED_PACKAGES = ("fastapi", "starlette", "pydantic", "a2wsgi", "python-multipart")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _docs_url() -> str | None:
    return "/docs" if settings.enable_docs else None


def _openapi_url() -> str | None:
    return "/openapi.json" if settings.enable_docs else None


@router.get(
    "/api",
    response_model=ServiceInfo,
    response_model_exclude_none=True,
    summary="Что это за сервис (машиночитаемо)",
)
async def service_info() -> dict:
    return {
        "service": __service__,
        "version": __version__,
        "description": (
            "Forit Lab — набор небольших data/dev-инструментов. "
            "Сейчас доступен Drift Lab: расследование расхождений между двумя выгрузками."
        ),
        "docs_url": _docs_url(),
        "openapi_url": _openapi_url(),
        "tools": [tool.model_dump(exclude_none=True) for tool in TOOLS],
        "endpoints": {
            "health": "/health",
            "status": "/api/status",
            "tools": "/api/tools",
            "drift_demo": "/api/drift/demo",
            "drift_compare": "POST /api/drift/reports",
            "drift_limits": "/api/drift/limits",
        },
    }


@router.get(
    "/api/tools",
    response_model=list[ToolInfo],
    response_model_exclude_none=True,
    summary="Каталог инструментов",
)
async def tools() -> list[ToolInfo]:
    return TOOLS


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Healthcheck",
    description="Дешёвая проверка живости: ничего тяжёлого не считает, годится для мониторинга.",
)
async def health() -> dict:
    problems: list[str] = []

    store = get_store()
    writable = store.writable()
    if settings.reports_store == "json" and not writable:
        problems.append("Каталог состояния недоступен для записи — отчёты не сохраняются")
    if not settings.data_dir.exists():
        problems.append(f"Не найден каталог данных: {settings.data_dir}")

    return {
        "ok": not problems,
        "status": "degraded" if problems else "healthy",
        "version": __version__,
        "reports_store": store.backend,
        "storage_writable": writable,
        "problems": problems,
        "time": _now(),
    }


@status_router.get(
    "/api/status",
    response_model=StatusResponse,
    summary="Диагностика окружения",
    description=(
        "Где именно мы работаем и обо что упирается хостинг. "
        "Роутер не подключается вовсе при FORIT_ENABLE_STATUS=0."
    ),
)
async def status() -> dict:
    store = get_store()

    dependencies: dict[str, str] = {}
    for package in _TRACKED_PACKAGES:
        try:
            dependencies[package] = version(package)
        except PackageNotFoundError:
            dependencies[package] = "not installed"

    return {
        "service": __service__,
        "version": __version__,
        "python": sys.version.split()[0],
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "pid": os.getpid(),
        # Passenger не выставляет SERVER_SOFTWARE в окружение процесса,
        # поэтому подпись сервера здесь — лучшее приближение, а не истина.
        "server": os.environ.get("SERVER_SOFTWARE", "unknown"),
        "cwd": os.getcwd(),
        "base_dir": str(settings.data_dir.parent),
        "state_dir": str(settings.state_dir),
        "state_dir_writable": store.writable(),
        "reports_store": store.backend,
        "reports_count": store.count(),
        "uptime_seconds": round(time.time() - PROCESS_STARTED_AT, 3),
        "process_started_at": datetime.fromtimestamp(PROCESS_STARTED_AT, timezone.utc).isoformat(),
        "dependencies": dependencies,
        "limits": {
            "max_upload_mb": settings.max_upload_mb,
            "max_rows": settings.max_rows,
            "max_columns": settings.max_columns,
            "max_reports": settings.max_reports,
        },
    }
