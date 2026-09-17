"""Web Parser 1e: Crawl / Audit. Обход сайта → технические факты. Офлайн."""

from __future__ import annotations

import pathlib

import pytest

from app.exec import ChunkedCursorExecutor, FileJobStore, JobStatus, JobStoreLimits, StepBudget
from app.parser.crawl_audit import CrawlHandler, build_plan
from app.parser.results import ResultFile


# фикстура-граф с 200/301/404 и циклом
SITE = {
    "/": '<html><head><title>Home</title></head><body><a href="/a">a</a><a href="/b">b</a><a href="/missing">m</a><a href="/redir">r</a><a href="https://external.example/x">ext</a></body></html>',
    "/a": '<html><head><title>A</title></head><body><a href="/b">b</a><a href="/">home</a></body></html>',
    "/b": '<html><head><title>B</title></head><body><a href="/a">a</a></body></html>',  # цикл a<->b
}


class Resp:
    def __init__(self, url, status, final, text, ctype="text/html"):
        self.url = url
        self.status = status
        self.final_url = final
        self.text = text
        self.body = text.encode()
        self.content_type = ctype
        self.redirect_chain = []
        self.headers = {}


class FakeClient:
    def request(self, method, url, **kw):
        path = url.split("http://site")[1] if "http://site" in url else "/"
        if path == "/missing":
            return Resp(url, 404, url, "<html><body>404</body></html>")
        if path == "/redir":
            return Resp(url, 200, "http://site/a", '<html><body><a href="/b">b</a></body></html>')
        if path in SITE:
            return Resp(url, 200, url, SITE[path])
        return Resp(url, 200, url, "<html></html>")


def _run(tmp_path, seed="http://site/", **opts):
    store = FileJobStore(tmp_path / "jobs", JobStoreLimits(100, 2_000_000, 64_000_000, 3600))
    ex = ChunkedCursorExecutor(store)
    ex.register("parser.crawl", CrawlHandler(client_factory=FakeClient))
    st = ex.start(build_plan(seed, {"max_pages": 50, "max_depth": 5, **opts}))
    cur = st.cursor
    for _ in range(30):
        st = ex.step(st.id, cursor=cur, budget=StepBudget(max_units=999, max_ms=9000))
        cur = st.cursor
        if st.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            break
    rows = list(ResultFile(store.directory, st.id).read())
    return st, rows


def test_crawl_completes_and_finds_pages(tmp_path):
    st, rows = _run(tmp_path)
    assert st.status == JobStatus.COMPLETED
    paths = sorted({r["url"].split("site")[1] for r in rows})
    assert paths == ["/", "/a", "/b", "/missing", "/redir"]


def test_finds_404_as_broken(tmp_path):
    _, rows = _run(tmp_path)
    m = [r for r in rows if r["url"].endswith("/missing")][0]
    assert m["status"] == 404 and m["broken"] is True


def test_cycle_does_not_loop(tmp_path):
    _, rows = _run(tmp_path)
    urls = [r["url"] for r in rows]
    assert len(urls) == len(set(urls))  # каждый URL посещён один раз


def test_records_redirect(tmp_path):
    _, rows = _run(tmp_path)
    r = [x for x in rows if x["url"].endswith("/redir")][0]
    assert r["redirected"] is True
    assert r["final_url"].endswith("/a")


def test_stays_same_origin(tmp_path):
    _, rows = _run(tmp_path)
    assert all("external.example" not in r["url"] for r in rows)


def test_records_title_depth_source(tmp_path):
    _, rows = _run(tmp_path)
    home = [r for r in rows if r["url"].rstrip("/").endswith("site")][0]
    assert home["title"] == "Home"
    assert home["depth"] == 0 and home["source"] is None
    a = [r for r in rows if r["url"].endswith("/a")][0]
    assert a["depth"] == 1


def test_max_pages_limit_partial(tmp_path):
    st, rows = _run(tmp_path, max_pages=2)
    assert st.partial["pages"] == 2
    assert st.partial["partial"] is True


def test_seed_must_be_url():
    with pytest.raises(ValueError):
        build_plan("not-a-url", {})


# ---------- API ----------
@pytest.fixture()
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import create_app
    import app.tools.parser.router as pr

    store = FileJobStore(tmp_path / "jobs", JobStoreLimits(100, 2_000_000, 64_000_000, 3600))
    ex = ChunkedCursorExecutor(store)
    ex.register("parser.crawl", CrawlHandler(client_factory=FakeClient))
    monkeypatch.setattr(pr, "_get_executor", lambda: ex)
    return TestClient(create_app())


def test_crawl_endpoints_flow(client):
    start = client.post("/api/parser/crawl", json={"input": "http://site/", "max_pages": 50}).json()
    jid, cursor = start["id"], start["cursor"]
    status = start
    for _ in range(20):
        status = client.post(f"/api/parser/crawl/{jid}/step", json={"cursor": cursor}).json()
        cursor = status["cursor"]
        if status["status"] in ("completed", "failed", "cancelled"):
            break
    assert status["status"] == "completed"
    assert status["partial"]["broken"] == 1
    csv_resp = client.get(f"/api/parser/crawl/{jid}/export?format=csv")
    assert csv_resp.status_code == 200
    assert "status" in csv_resp.text.splitlines()[0]


def test_crawl_rejects_non_url(client):
    r = client.post("/api/parser/crawl", json={"input": "<html>x</html>"}).json()
    assert "error" in r
