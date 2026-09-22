"""Web Parser 1d: pagination detection + multi-page collection.

Офлайн: HttpClient подменяется фейком, отдающим N страниц каталога с rel=next.
Проверяем сбор в один датасет, chunked-прогресс, отмену, лимиты (partial),
schema drift, отдельное хранение результата, запрет секретов, экспорт.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from app.exec import ChunkedCursorExecutor, FileJobStore, JobStoreLimits, StepBudget, JobStatus
from app.parser.collect import CollectHandler, build_plan, summarize_drift
from app.parser.models import ExtractionSchema, FieldSource, FieldSpec, SourceKind
from app.parser.pagination import detect_next
from app.parser.results import ResultFile


# ---------- фейковый клиент: каталог из `pages` страниц ----------
class FakeResp:
    def __init__(self, text, url, headers=None):
        self.text = text
        self.final_url = url
        self.content_type = "text/html"
        self.body = text.encode()
        self.headers = headers or {}


def make_client(pages=3, per_page=3, drift_at=None):
    class FakeClient:
        def request(self, method, url, **kw):
            n = int(url.split("page=")[1]) if "page=" in url else 1
            if n > pages:
                return FakeResp("<html><body><div class=catalog></div></body></html>", url)
            cards = []
            for i in range(1, per_page + 1):
                price = f"{n}{i}0"
                if drift_at and n >= drift_at:  # ломаем тип цены со страницы drift_at
                    price = "договорная"
                cards.append(f'<div class="product" data-id="{n}{i}"><h3>Товар {n}-{i}</h3><span class="price">{price}</span></div>')
            nxt = f'<link rel="next" href="/cat?page={n + 1}">' if n < pages else ""
            return FakeResp(f'<html><head>{nxt}</head><body><div class="catalog">{"".join(cards)}</div></body></html>', url)

    return FakeClient


def _schema():
    return ExtractionSchema(
        source_kind=SourceKind.REPEATED_DOM,
        container_selector="div.product",
        fields=[
            FieldSpec(name="title", selector="h3", source=FieldSource.TEXT),
            FieldSpec(name="price", selector="span.price", source=FieldSource.TEXT),
        ],
    )


def _executor(tmp_path, client, **limits):
    store = FileJobStore(tmp_path / "jobs", JobStoreLimits(
        limits.get("max_jobs", 100), limits.get("max_job_bytes", 2_000_000),
        limits.get("max_total_bytes", 64_000_000), limits.get("ttl", 3600)))
    ex = ChunkedCursorExecutor(store)
    ex.register("parser.collect", CollectHandler(client_factory=client))
    return ex, store


def _run(ex, plan, steps=30):
    st = ex.start(plan)
    cur = st.cursor
    for _ in range(steps):
        st = ex.step(st.id, cursor=cur, budget=StepBudget(max_units=999, max_ms=9000))
        cur = st.cursor
        if st.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            break
    return st


# ---------- pagination ----------
def test_detect_rel_next_html():
    kind, nxt = detect_next(source_type="html", text='<link rel="next" href="/cat?page=2">', current_url="https://s.ex/cat?page=1")
    assert kind == "rel_next" and nxt.endswith("/cat?page=2")


def test_detect_link_header():
    kind, nxt = detect_next(source_type="html", text="<html></html>", current_url="https://s.ex/x",
                            headers={"link": '</cat?page=2>; rel="next"'})
    assert kind == "link_header" and nxt.endswith("/cat?page=2")


def test_detect_json_next():
    kind, nxt = detect_next(source_type="json", text=json.dumps({"next": "/api?page=2", "data": []}), current_url="https://s.ex/api")
    assert kind == "json_next" and nxt.endswith("/api?page=2")


def test_detect_query_increment():
    kind, nxt = detect_next(source_type="html", text="<html></html>", current_url="https://s.ex/cat?page=2")
    assert kind == "query_page" and nxt.endswith("page=3")


def test_detect_offset_limit():
    kind, nxt = detect_next(source_type="html", text="<html></html>", current_url="https://s.ex/c?offset=20&limit=20")
    assert kind == "offset_limit" and "offset=40" in nxt


# ---------- multi-page collection ----------
def test_collects_all_pages_into_one_dataset(tmp_path):
    ex, store = _executor(tmp_path, make_client(pages=3, per_page=4))
    st = _run(ex, build_plan("https://s.ex/cat?page=1", _schema(), {"max_pages": 20}))
    assert st.status == JobStatus.COMPLETED
    assert st.partial["pages"] == 3
    assert st.partial["rows"] == 12
    result = ResultFile(store.directory, st.id)
    assert result.count() == 12
    rows = list(result.read())
    assert rows[0]["title"] == "Товар 1-1"


def test_tiny_step_budget_does_not_lose_pages(tmp_path):
    """Короткий шаг (по 1 странице) собирает весь каталог без потерь и дублей.

    Регрессия под приёмку №4: уменьшение step budget (до 3.5 с в проде) режет
    работу на больше шагов, но состояние на курсоре+frontier не должно терять
    или пропускать страницы между шагами.
    """
    ex, store = _executor(tmp_path, make_client(pages=6, per_page=2))
    st = ex.start(build_plan("https://s.ex/cat?page=1", _schema(), {"max_pages": 20}))
    cur = st.cursor
    steps = 0
    while st.status not in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED) and steps < 100:
        # max_units=1 → ровно одна страница за шаг (жёстко «нарезанный» бюджет)
        st = ex.step(st.id, cursor=cur, budget=StepBudget(max_units=1, max_ms=1))
        cur = st.cursor
        steps += 1
    assert st.status == JobStatus.COMPLETED
    assert st.partial["pages"] == 6
    assert steps >= 6  # реально прошли многошагово, а не за один проход
    rows = list(ResultFile(store.directory, st.id).read())
    assert len(rows) == 12
    titles = [r["title"] for r in rows]
    assert len(set(titles)) == 12  # без дублей и пропусков — все 6×2 уникальны


def test_cancel_leaves_no_live_job(tmp_path):
    """После отмены задача терминальна и повторный step её не оживляет (нет zombie)."""
    ex, store = _executor(tmp_path, make_client(pages=100, per_page=2))
    st = ex.start(build_plan("https://s.ex/cat?page=1", _schema(), {"max_pages": 100}))
    st = ex.step(st.id, cursor=st.cursor, budget=StepBudget(max_units=1, max_ms=1))
    ex.cancel(st.id)
    after = ex.status(st.id)
    assert after.status == JobStatus.CANCELLED
    pages_at_cancel = after.partial["pages"] if after.partial else 0
    # повторный шаг после отмены не двигает задачу и не меняет счётчик
    again = ex.step(st.id, cursor=after.cursor, budget=StepBudget(max_units=999, max_ms=9000))
    assert again.status == JobStatus.CANCELLED
    assert (again.partial["pages"] if again.partial else 0) == pages_at_cancel


def test_progress_is_chunked(tmp_path):
    # с pages_per_step=3 (по умолчанию) 3 страницы соберутся за 1 шаг; проверим многошаговость на большем каталоге
    ex, store = _executor(tmp_path, make_client(pages=7, per_page=2))
    st = ex.start(build_plan("https://s.ex/cat?page=1", _schema(), {"max_pages": 20}))
    cur = st.cursor
    progresses = []
    steps = 0
    while st.status not in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED) and steps < 20:
        st = ex.step(st.id, cursor=cur, budget=StepBudget(max_units=999, max_ms=9000))
        cur = st.cursor
        progresses.append(st.partial["pages"])
        steps += 1
    assert steps >= 2  # не одним махом
    assert st.partial["pages"] == 7


def test_max_pages_limit_partial(tmp_path):
    ex, store = _executor(tmp_path, make_client(pages=100, per_page=2))
    st = _run(ex, build_plan("https://s.ex/cat?page=1", _schema(), {"max_pages": 5}))
    assert st.partial["pages"] == 5
    assert st.partial["partial"] is True
    assert "лимит страниц" in st.partial["stopped_reason"]


def test_max_rows_limit_partial(tmp_path):
    ex, store = _executor(tmp_path, make_client(pages=100, per_page=10))
    st = _run(ex, build_plan("https://s.ex/cat?page=1", _schema(), {"max_pages": 100, "max_rows": 25}))
    assert st.partial["rows"] == 25
    assert st.partial["partial"] is True
    assert "строк" in st.partial["stopped_reason"]


def test_cancel_stops_collection(tmp_path):
    ex, store = _executor(tmp_path, make_client(pages=100, per_page=2))
    st = ex.start(build_plan("https://s.ex/cat?page=1", _schema(), {"max_pages": 100}))
    st = ex.step(st.id, cursor=st.cursor, budget=StepBudget(max_units=999, max_ms=9000))
    ex.cancel(st.id)
    reloaded = ex.status(st.id)
    assert reloaded.status == JobStatus.CANCELLED


def test_schema_drift_detected(tmp_path):
    ex, store = _executor(tmp_path, make_client(pages=4, per_page=3, drift_at=3))
    st = _run(ex, build_plan("https://s.ex/cat?page=1", _schema(), {"max_pages": 20}))
    price = [d for d in st.partial["schema_drift"] if d["field"] == "price"][0]
    assert price["mixed_types"] is True  # number на 1-2 стр., text на 3-4


def test_empty_page_stops_pagination(tmp_path):
    # каталог 3 страницы; query-increment не должен бесконечно листать за конец
    ex, store = _executor(tmp_path, make_client(pages=3, per_page=2))
    st = _run(ex, build_plan("https://s.ex/cat?page=1", _schema(), {"max_pages": 50}))
    assert st.partial["pages"] == 3
    assert st.status == JobStatus.COMPLETED


def test_result_separate_from_state(tmp_path):
    ex, store = _executor(tmp_path, make_client(pages=3, per_page=3))
    st = _run(ex, build_plan("https://s.ex/cat?page=1", _schema(), {"max_pages": 20}))
    import os
    state_size = os.path.getsize(store.directory / f"{st.id}.json")
    assert state_size < 50_000  # состояние маленькое
    assert (store.directory / f"{st.id}.result.jsonl").exists()  # датасет отдельно


def test_seed_must_be_url():
    with pytest.raises(ValueError):
        build_plan("<html>not a url</html>", _schema(), {})


def test_secrets_rejected_in_collect(tmp_path):
    ex, store = _executor(tmp_path, make_client())
    plan = build_plan("https://s.ex/cat", _schema(), {})
    plan.params["authorization"] = "Bearer X"  # секрет пробрался в params
    with pytest.raises(ValueError):
        ex.start(plan)


def test_summarize_drift_percentages():
    drift = {"price": {"present": 8, "types": {"number": 6, "text": 2}}}
    summary = summarize_drift(drift, 10)
    assert summary[0]["present_pct"] == 80
    assert summary[0]["dominant_type"] == "number"
    assert summary[0]["mixed_types"] is True


# ---------- API-эндпоинты ----------
@pytest.fixture()
def client(tmp_path, monkeypatch):
    # свой executor с фейковым клиентом на изолированном каталоге
    from fastapi.testclient import TestClient
    from app.main import create_app
    import app.tools.parser.router as pr

    ex, store = _executor(tmp_path, make_client(pages=3, per_page=3))
    monkeypatch.setattr(pr, "_get_executor", lambda: ex)
    return TestClient(create_app())


def test_collect_endpoints_flow(client):
    schema = {"source_kind": "repeated_dom", "container_selector": "div.product",
              "fields": [{"name": "title", "selector": "h3"}, {"name": "price", "selector": "span.price"}]}
    start = client.post("/api/parser/collect", json={"input": "https://s.ex/cat?page=1", "schema": schema, "max_pages": 20}).json()
    assert "id" in start
    job_id, cursor = start["id"], start["cursor"]
    status = start
    for _ in range(10):
        status = client.post(f"/api/parser/collect/{job_id}/step", json={"cursor": cursor}).json()
        cursor = status["cursor"]
        if status["status"] in ("completed", "failed", "cancelled"):
            break
    assert status["status"] == "completed"
    assert status["partial"]["rows"] == 9
    # экспорт собранного датасета
    csv_resp = client.get(f"/api/parser/collect/{job_id}/export?format=csv")
    assert csv_resp.status_code == 200
    assert "title" in csv_resp.text.splitlines()[0]
    assert len(csv_resp.text.strip().splitlines()) == 10  # заголовок + 9 строк


def test_collect_rejects_non_url(client):
    r = client.post("/api/parser/collect", json={"input": "<html>x</html>", "schema": {"source_kind": "repeated_dom", "container_selector": "div", "fields": [{"name": "a", "selector": "h3"}]}}).json()
    assert "error" in r
