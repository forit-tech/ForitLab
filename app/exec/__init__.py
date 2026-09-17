"""Исполнение задач за интерфейсом Executor.

Текущая реализация под Host-0 — ChunkedCursorExecutor (порционно, состояние на
диске). Интерфейс оставляет место под другие исполнители (фоновый воркер,
отдельный Chaos-executor) без переписывания Parser/Chaos.
"""

from __future__ import annotations

from ..config import settings
from .base import (
    AdvanceResult,
    Executor,
    JobContext,
    JobPlan,
    JobState,
    JobStatus,
    StepBudget,
    StepHandler,
    TERMINAL,
)
from .chunked import ChunkedCursorExecutor
from .store import FileJobStore, JobStoreLimits

__all__ = [
    "Executor",
    "JobPlan",
    "JobState",
    "JobStatus",
    "StepBudget",
    "StepHandler",
    "AdvanceResult",
    "JobContext",
    "TERMINAL",
    "ChunkedCursorExecutor",
    "FileJobStore",
    "JobStoreLimits",
    "build_default_executor",
]


def build_default_executor() -> ChunkedCursorExecutor:
    """Дисковый executor с лимитами из настроек — реализация по умолчанию на Host-0."""
    limits = JobStoreLimits(
        max_jobs=settings.jobs_max_count,
        max_job_bytes=settings.jobs_max_job_bytes,
        max_total_bytes=settings.jobs_max_total_bytes,
        ttl_seconds=settings.jobs_ttl_hours * 3600,
    )
    return ChunkedCursorExecutor(FileJobStore(settings.jobs_dir, limits))
