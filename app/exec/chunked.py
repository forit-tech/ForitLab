"""ChunkedCursorExecutor — исполнение задач порциями под Passenger/Host-0.

Модель: клиент вызывает step() повторно, каждый раз сервер делает ограниченную
порцию работы (StepBudget), сохраняет прогресс на диск и отдаёт opaque-курсор.
Никаких фоновых воркеров и long-running запросов — только то, что реально
переживает многопроцессный Passenger.

Идемпотентность: клиент возвращает последний полученный `cursor`. step()
двигает задачу только если курсор совпадает с текущим; повтор/дубль запроса
браузера с устаревшим курсором вернёт текущее состояние, не сделав шаг дважды.

Секреты в состоянии не хранятся: JobPlan.params проверяется на секретные ключи.
"""

from __future__ import annotations

import secrets
import time
from typing import Any

from ..errors import NotFoundError
from .base import (
    TERMINAL,
    AdvanceResult,
    Executor,
    JobContext,
    JobPlan,
    JobState,
    JobStatus,
    StepBudget,
    StepHandler,
)
from .store import FileJobStore, JobTooLargeError

# Ключи, которых не должно быть в params джобы (секреты живут вне состояния).
_SECRET_HINTS = ("authorization", "cookie", "api_key", "apikey", "api-key", "token", "password", "secret")


def _reject_secrets(params: dict[str, Any]) -> None:
    for key in params:
        low = str(key).lower()
        if any(hint in low for hint in _SECRET_HINTS):
            raise ValueError(f"секрет не должен попадать в состояние джобы: {key!r}")


def _new_cursor() -> str:
    return secrets.token_hex(8)


class ChunkedCursorExecutor(Executor):
    def __init__(self, store: FileJobStore) -> None:
        self._store = store
        self._handlers: dict[str, StepHandler] = {}

    def register(self, kind: str, handler: StepHandler) -> None:
        self._handlers[kind] = handler

    # -- сериализация состояния <-> dict --------------------------------
    @staticmethod
    def _to_dict(state: JobState) -> dict:
        return {
            "id": state.id,
            "kind": state.kind,
            "status": state.status.value,
            "progress": state.progress,
            "cursor": state.cursor,
            "partial": state.partial,
            "errors": state.errors,
            "created_at": state.created_at,
            "updated_at": state.updated_at,
            "version": state.version,
            "internal_state": state.internal_state,
        }

    @staticmethod
    def _from_dict(data: dict) -> JobState:
        return JobState(
            id=data["id"],
            kind=data["kind"],
            status=JobStatus(data["status"]),
            progress=data.get("progress", 0.0),
            cursor=data.get("cursor"),
            partial=data.get("partial"),
            errors=data.get("errors", []),
            created_at=data.get("created_at", 0.0),
            updated_at=data.get("updated_at", 0.0),
            version=data.get("version", 0),
            internal_state=data.get("internal_state", {}),
        )

    def _load(self, job_id: str) -> JobState:
        data = self._store.load(job_id)
        if data is None:
            raise NotFoundError("Задача не найдена", {"job_id": job_id})
        return self._from_dict(data)

    def _persist(self, state: JobState) -> None:
        state.updated_at = time.time()
        try:
            self._store.save(state.id, self._to_dict(state))
        except JobTooLargeError as exc:
            # не роняем запрос: помечаем джобу FAILED и сохраняем компактную версию
            state.status = JobStatus.FAILED
            state.errors = [str(exc)]
            state.partial = None
            state.internal_state = {}
            self._store.save(state.id, self._to_dict(state))

    # -- API ------------------------------------------------------------
    def start(self, plan: JobPlan) -> JobState:
        _reject_secrets(plan.params)
        if plan.kind not in self._handlers:
            raise NotFoundError("Нет обработчика для такого вида задачи", {"kind": plan.kind})
        self._store.evict()
        now = time.time()
        state = JobState(
            id=self._store.new_id(),
            kind=plan.kind,
            status=JobStatus.QUEUED,
            cursor=_new_cursor(),
            created_at=now,
            updated_at=now,
            internal_state={"params": plan.params},
        )
        self._persist(state)
        return state

    def step(self, job_id: str, *, cursor: str | None = None, budget: StepBudget | None = None) -> JobState:
        budget = budget or StepBudget()
        with self._store.locked(job_id):
            state = self._load(job_id)
            if state.status in TERMINAL:
                return state
            # идемпотентность: устаревший/чужой курсор не двигает задачу
            if cursor is not None and cursor != state.cursor:
                return state

            handler = self._handlers.get(state.kind)
            if handler is None:
                state.status = JobStatus.FAILED
                state.errors = ["обработчик задачи не зарегистрирован"]
                self._persist(state)
                return state

            params = state.internal_state.get("params", {})
            state.status = JobStatus.RUNNING
            ctx = JobContext(job_id=state.id, result_dir=self._store.directory)
            try:
                result: AdvanceResult = handler.advance(params, state.internal_state, budget, ctx)
            except Exception as exc:  # noqa: BLE001 — падение обработчика не роняет запрос
                state.status = JobStatus.FAILED
                state.errors = [f"{type(exc).__name__}: {exc}"]
                state.version += 1
                self._persist(state)
                return state

            state.partial = result.partial
            state.internal_state = result.internal_state
            state.internal_state["params"] = params
            state.progress = max(0.0, min(1.0, result.progress))
            state.errors = result.errors
            state.version += 1
            state.cursor = _new_cursor()
            if result.done:
                state.status = JobStatus.COMPLETED
                state.progress = 1.0
                state.cursor = None
            self._persist(state)
            return state

    def cancel(self, job_id: str) -> JobState:
        with self._store.locked(job_id):
            state = self._load(job_id)
            if state.status not in TERMINAL:
                state.status = JobStatus.CANCELLED
                state.cursor = None
                state.version += 1
                self._persist(state)
            return state

    def status(self, job_id: str) -> JobState:
        return self._load(job_id)
