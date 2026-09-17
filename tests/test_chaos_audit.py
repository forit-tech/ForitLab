"""Chaos 1b — Site-wide Passive Audit: обход + агрегация findings по сайту. Офлайн."""

from __future__ import annotations

import pytest

from app.chaos.audit import SecurityAuditHandler, build_plan
from app.exec import ChunkedCursorExecutor, FileJobStore, JobStatus, JobStoreLimits, StepBudget
from app.parser.results import ResultFile


class Resp:
    def __init__(self, url, status=200, text="", headers=None, cookies=None):
        self.url = url
        self.status = status
        self.final_url = url
        self.text = text
        self.body = text.encode()
        self.content_type = "text/html"
        self.headers = headers or {}
        self.cookies = cookies or []
        self.redirect_chain = []


LINKS = '<a href="/a">a</a><a href="/b">b</a><a href="/c">c</a>'


class FakeClient:
    """Сайт /,/a,/b без CSP; /c с CSP но кука без Secure; X-Powered-By везде; всё http (no_https)."""

    def request(self, method, url, **kw):
        path = url.split("http://site")[1] if "http://site" in url else "/"
        if path in ("/", "/a", "/b"):
            return Resp(url, 200, f"<html><body>{LINKS}</body></html>", {"X-Powered-By": "Express"})
        if path == "/c":
            return Resp(url, 200, f"<html><body>{LINKS}</body></html>",
                        {"X-Powered-By": "Express", "Content-Security-Policy": "default-src 'self'"}, ["sid=1; Path=/"])
        return Resp(url, 200, "<html></html>", {"X-Powered-By": "Express"})


def _run(tmp_path, seed="http://site/", **opts):
    store = FileJobStore(tmp_path / "jobs", JobStoreLimits(100, 2_000_000, 64_000_000, 3600))
    ex = ChunkedCursorExecutor(store)
    ex.register("chaos.audit", SecurityAuditHandler(client_factory=FakeClient))
    st = ex.start(build_plan(seed, {"max_pages": 20, "max_depth": 3, **opts}))
    cur = st.cursor
    for _ in range(20):
        st = ex.step(st.id, cursor=cur, budget=StepBudget(max_units=999, max_ms=9000))
        cur = st.cursor
        if st.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            break
    return st, store


def _agg(st):
    return {a["id"]: a for a in st.partial["aggregated_findings"]}


def test_audits_all_pages(tmp_path):
    st, _ = _run(tmp_path)
    assert st.status == JobStatus.COMPLETED
    assert st.partial["pages_checked"] == 4


def test_aggregates_missing_csp_partial(tmp_path):
    st, _ = _run(tmp_path)
    csp = _agg(st)["missing_csp"]
    assert csp["affected_pages"] == 3  # /,/a,/b (не /c)
    assert csp["checked_pages"] == 4
    assert csp["severity"] == "medium"
    assert len(csp["examples"]) == 3


def test_aggregates_powered_by_all_pages(tmp_path):
    st, _ = _run(tmp_path)
    assert _agg(st)["powered_by"]["affected_pages"] == 4


def test_cookie_finding_single_page(tmp_path):
    st, _ = _run(tmp_path)
    assert _agg(st)["cookie_no_httponly"]["affected_pages"] == 1
    assert _agg(st)["cookie_no_httponly"]["examples"][0].endswith("/c")


def test_summary_counts_distinct_problems(tmp_path):
    st, _ = _run(tmp_path)
    s = st.partial["summary"]
    # summary = число РАЗНЫХ проблем по severity, не сумма по страницам
    assert s["high"] == 1  # no_https
    assert s["medium"] >= 2


def test_findings_sorted_by_severity(tmp_path):
    st, _ = _run(tmp_path)
    sevs = [a["severity"] for a in st.partial["aggregated_findings"]]
    order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    assert sevs == sorted(sevs, key=lambda x: order[x])


def test_result_rows_per_page(tmp_path):
    st, store = _run(tmp_path)
    rows = list(ResultFile(store.directory, st.id).read())
    assert len(rows) == 4
    assert all("ids" in r and "status" in r for r in rows)


def test_max_pages_limit(tmp_path):
    st, _ = _run(tmp_path, max_pages=2)
    assert st.partial["pages_checked"] == 2
    assert st.partial["partial"] is True


def test_seed_must_be_url():
    with pytest.raises(ValueError):
        build_plan("not-a-url", {})


# ---------- API ----------
@pytest.fixture()
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import create_app
    import app.chaos.router as cr

    store = FileJobStore(tmp_path / "jobs", JobStoreLimits(100, 2_000_000, 64_000_000, 3600))
    ex = ChunkedCursorExecutor(store)
    ex.register("chaos.audit", SecurityAuditHandler(client_factory=FakeClient))
    monkeypatch.setattr(cr, "_get_executor", lambda: ex)
    return TestClient(create_app())


def test_audit_endpoints_flow(client):
    start = client.post("/api/chaos/v2/audit", json={"url": "http://site/", "max_pages": 20}).json()
    jid, cursor = start["id"], start["cursor"]
    status = start
    for _ in range(20):
        status = client.post(f"/api/chaos/v2/audit/{jid}/step", json={"cursor": cursor}).json()
        cursor = status["cursor"]
        if status["status"] in ("completed", "failed", "cancelled"):
            break
    assert status["status"] == "completed"
    assert status["partial"]["pages_checked"] == 4
    ids = {a["id"] for a in status["partial"]["aggregated_findings"]}
    assert "missing_csp" in ids
    csv_resp = client.get(f"/api/chaos/v2/audit/{jid}/export?format=csv")
    assert csv_resp.status_code == 200
    assert "ids" in csv_resp.text.splitlines()[0]


def test_audit_rejects_non_url(client):
    r = client.post("/api/chaos/v2/audit", json={"url": "not a url"}).json()
    assert "error" in r
