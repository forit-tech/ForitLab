"""ChunkedCursorExecutor: порционное исполнение, идемпотентность, персистентность."""

from __future__ import annotations

import pytest

from app.errors import NotFoundError
from app.exec.base import AdvanceResult, JobPlan, JobStatus, StepBudget
from app.exec.chunked import ChunkedCursorExecutor
from app.exec.store import FileJobStore, JobStoreLimits


class CounterHandler:
    """Считает до target по budget.max_units за шаг."""

    def advance(self, params, internal_state, budget):
        count = internal_state.get("count", 0)
        target = params["target"]
        count = min(target, count + budget.max_units)
        return AdvanceResult(
            partial={"count": count},
            internal_state={"count": count},
            progress=count / target,
            done=count >= target,
        )


class HugeHandler:
    def advance(self, params, internal_state, budget):
        return AdvanceResult(partial={"blob": "x" * 100000}, internal_state={}, progress=1.0, done=True)


def _store(tmp_path, **overrides):
    limits = JobStoreLimits(
        max_jobs=overrides.get("max_jobs", 100),
        max_job_bytes=overrides.get("max_job_bytes", 2_000_000),
        max_total_bytes=overrides.get("max_total_bytes", 64_000_000),
        ttl_seconds=overrides.get("ttl_seconds", 3600),
    )
    return FileJobStore(tmp_path / "jobs", limits)


def _executor(store):
    ex = ChunkedCursorExecutor(store)
    ex.register("counter", CounterHandler())
    return ex


def test_runs_to_completion(tmp_path):
    ex = _executor(_store(tmp_path))
    state = ex.start(JobPlan(kind="counter", params={"target": 25}))
    assert state.status == JobStatus.QUEUED
    cursor = state.cursor
    seen_progress = []
    for _ in range(10):
        state = ex.step(state.id, cursor=cursor, budget=StepBudget(max_units=10))
        seen_progress.append(state.progress)
        cursor = state.cursor
        if state.status == JobStatus.COMPLETED:
            break
    assert state.status == JobStatus.COMPLETED
    assert state.partial == {"count": 25}
    assert state.progress == 1.0
    assert state.cursor is None
    assert seen_progress == sorted(seen_progress)  # монотонный прогресс


def test_stale_cursor_is_idempotent(tmp_path):
    ex = _executor(_store(tmp_path))
    state = ex.start(JobPlan(kind="counter", params={"target": 100}))
    c0 = state.cursor
    s1 = ex.step(state.id, cursor=c0, budget=StepBudget(max_units=10))
    assert s1.partial == {"count": 10}
    # повтор с УСТАРЕВШИМ курсором не двигает задачу
    s_dup = ex.step(state.id, cursor=c0, budget=StepBudget(max_units=10))
    assert s_dup.partial == {"count": 10}
    assert s_dup.cursor == s1.cursor


def test_state_survives_new_executor_instance(tmp_path):
    store = _store(tmp_path)
    ex1 = _executor(store)
    state = ex1.start(JobPlan(kind="counter", params={"target": 30}))
    state = ex1.step(state.id, cursor=state.cursor, budget=StepBudget(max_units=10))
    # другой воркер = другой инстанс, тот же каталог
    ex2 = _executor(_store(tmp_path))
    loaded = ex2.status(state.id)
    assert loaded.partial == {"count": 10}
    loaded = ex2.step(loaded.id, cursor=loaded.cursor, budget=StepBudget(max_units=20))
    assert loaded.partial == {"count": 30}
    assert loaded.status == JobStatus.COMPLETED


def test_cancel_persists(tmp_path):
    store = _store(tmp_path)
    ex = _executor(store)
    state = ex.start(JobPlan(kind="counter", params={"target": 100}))
    ex.cancel(state.id)
    reloaded = _executor(_store(tmp_path)).status(state.id)
    assert reloaded.status == JobStatus.CANCELLED
    # шаг после отмены — no-op
    after = ex.step(state.id, cursor=state.cursor)
    assert after.status == JobStatus.CANCELLED


def test_secrets_rejected_in_params(tmp_path):
    ex = _executor(_store(tmp_path))
    for key in ("authorization", "Cookie", "api_key", "password"):
        with pytest.raises(ValueError):
            ex.start(JobPlan(kind="counter", params={key: "x", "target": 1}))


def test_corrupt_state_is_not_found(tmp_path):
    store = _store(tmp_path)
    ex = _executor(store)
    state = ex.start(JobPlan(kind="counter", params={"target": 5}))
    (tmp_path / "jobs" / f"{state.id}.json").write_text("{ broken", encoding="utf-8")
    with pytest.raises(NotFoundError):
        ex.status(state.id)


def test_oversized_job_marked_failed(tmp_path):
    store = _store(tmp_path, max_job_bytes=1000)
    ex = ChunkedCursorExecutor(store)
    ex.register("huge", HugeHandler())
    state = ex.start(JobPlan(kind="huge", params={}))
    state = ex.step(state.id, cursor=state.cursor)
    assert state.status == JobStatus.FAILED
    assert state.errors


def test_unknown_kind_rejected(tmp_path):
    ex = _executor(_store(tmp_path))
    with pytest.raises(NotFoundError):
        ex.start(JobPlan(kind="nope", params={}))
