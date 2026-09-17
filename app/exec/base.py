"""Интерфейс исполнения долгих задач (crawl, scan) — без привязки к реализации.

Сегодня на Passenger/Host-0 работает только :class:`ChunkedCursorExecutor`
(порционно, состояние на диске). Интерфейс намеренно оставляет место под
`BackgroundWorkerExecutor` или отдельный Chaos-executor в другом окружении —
Parser и Chaos Core не должны знать, где и как исполняется задача.

`Executor` НЕ знает про диск: хранение — деталь конкретной реализации.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}


@dataclass
class JobPlan:
    """Описание задачи. НЕ должен содержать секретов (Authorization/Cookie/ключи).

    Секреты (если они нужны исполнению) передаются в executor отдельно и не
    сериализуются в состояние джобы.
    """

    kind: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class StepBudget:
    """Сколько работы разрешено сделать за один вызов step()."""

    max_units: int = 10
    max_ms: int = 8000
    max_bytes: int = 8 * 1024 * 1024


@dataclass
class JobContext:
    """Идентичность задачи + куда писать побочный результат (датасет).

    Нужен обработчикам, которые копят большой результат: он пишется в отдельный
    файл (result_dir/<job_id>.result.jsonl), а НЕ в состояние джобы (там лимит).
    """

    job_id: str
    result_dir: "object"  # pathlib.Path; тип нестрогий, чтобы base не тянул импорт


@dataclass
class AdvanceResult:
    """Что вернул обработчик за один шаг."""

    partial: Any
    internal_state: dict[str, Any]
    progress: float
    done: bool
    errors: list[str] = field(default_factory=list)


class StepHandler(Protocol):
    """Логика конкретного вида задачи (crawl, collect, scan…). Регистрируется в executor."""

    def advance(
        self, params: dict[str, Any], internal_state: dict[str, Any], budget: StepBudget, ctx: JobContext
    ) -> AdvanceResult:  # pragma: no cover - протокол
        ...


@dataclass
class JobState:
    id: str
    kind: str
    status: JobStatus
    progress: float = 0.0
    cursor: str | None = None  # opaque-токен для фронтенда (идемпотентность step)
    partial: Any = None
    errors: list[str] = field(default_factory=list)
    created_at: float = 0.0
    updated_at: float = 0.0
    version: int = 0
    internal_state: dict[str, Any] = field(default_factory=dict)  # НЕ отдаётся наружу

    def to_public(self) -> dict[str, Any]:
        """Представление для клиента: без internal_state, cursor — как есть (opaque)."""
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status.value,
            "progress": round(self.progress, 4),
            "cursor": self.cursor,
            "partial": self.partial,
            "errors": self.errors,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class Executor(Protocol):
    def start(self, plan: JobPlan) -> JobState: ...  # pragma: no cover - протокол
    def step(self, job_id: str, *, cursor: str | None = None, budget: StepBudget | None = None) -> JobState: ...
    def cancel(self, job_id: str) -> JobState: ...
    def status(self, job_id: str) -> JobState: ...
