"""Chaos 1a — Passive Security Check. Проверки над ответами, офлайн."""

from __future__ import annotations

import pytest

from app.chaos.passive import run_checks
import app.chaos.router as cr


class Resp:
    def __init__(self, final, status=200, headers=None, cookies=None, text=""):
        self.final_url = final
        self.status = status
        self.headers = headers or {}
        self.cookies = cookies or []
        self.text = text


def _ids(rep):
    return {f["id"] for f in rep["findings"]}


def test_no_https_is_high():
    rep = run_checks(Resp("http://x.example/"), None, "http://x.example/")
    assert "no_https" in _ids(rep)
    assert [f for f in rep["findings"] if f["id"] == "no_https"][0]["severity"] == "high"


def test_http_not_redirecting_is_medium():
    primary = Resp("https://x.example/")
    http_probe = Resp("http://x.example/")  # остался на http
    rep = run_checks(primary, http_probe, "https://x.example/")
    assert "no_http_redirect" in _ids(rep)


def test_missing_security_headers():
    rep = run_checks(Resp("https://x.example/"), Resp("https://x.example/"), "https://x.example/")
    ids = _ids(rep)
    assert {"missing_hsts", "missing_csp", "missing_nosniff", "missing_referrer_policy",
            "missing_permissions_policy", "missing_frame_protection"} <= ids


def test_good_headers_no_findings():
    good = Resp("https://x.example/", headers={
        "Strict-Transport-Security": "max-age=31536000",
        "Content-Security-Policy": "default-src 'self'",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "strict-origin",
        "Permissions-Policy": "camera=()",
        "X-Frame-Options": "DENY",
        "Cross-Origin-Opener-Policy": "same-origin",
        "Cross-Origin-Resource-Policy": "same-origin",
        "Cross-Origin-Embedder-Policy": "require-corp",
    }, cookies=["sid=1; Secure; HttpOnly; SameSite=Lax"], text="<img src='https://cdn/x.png'>")
    rep = run_checks(good, Resp("https://x.example/"), "https://x.example/")
    assert rep["findings"] == []
    assert rep["summary"] == {"high": 0, "medium": 0, "low": 0, "info": 0}


def test_frame_protection_via_csp_ok():
    rep = run_checks(Resp("https://x.example/", headers={"Content-Security-Policy": "frame-ancestors 'none'"}),
                     Resp("https://x.example/"), "https://x.example/")
    assert "missing_frame_protection" not in _ids(rep)


def test_cookie_flags():
    rep = run_checks(Resp("https://x.example/", cookies=["sid=abc; Path=/"]),
                     Resp("https://x.example/"), "https://x.example/")
    ids = _ids(rep)
    assert {"cookie_no_secure", "cookie_no_httponly", "cookie_no_samesite"} <= ids


def test_cors_wildcard_with_credentials_is_high():
    rep = run_checks(Resp("https://x.example/", headers={
        "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Credentials": "true"}),
        Resp("https://x.example/"), "https://x.example/")
    f = [x for x in rep["findings"] if x["id"] == "cors_wildcard_credentials"]
    assert f and f[0]["severity"] == "high"


def test_cors_wildcard_only_is_low():
    rep = run_checks(Resp("https://x.example/", headers={"Access-Control-Allow-Origin": "*"}),
                     Resp("https://x.example/"), "https://x.example/")
    assert "cors_wildcard" in _ids(rep)
    assert "cors_wildcard_credentials" not in _ids(rep)


def test_information_disclosure():
    rep = run_checks(Resp("https://x.example/", headers={"Server": "nginx/1.18.0", "X-Powered-By": "Express"}),
                     Resp("https://x.example/"), "https://x.example/")
    ids = _ids(rep)
    assert "server_version" in ids and "powered_by" in ids


def test_mixed_content_detected():
    html = '<img src="http://cdn/x.png"><script src="http://cdn/a.js"></script><a href="http://external/page">link</a>'
    rep = run_checks(Resp("https://x.example/", text=html), Resp("https://x.example/"), "https://x.example/")
    f = [x for x in rep["findings"] if x["id"] == "mixed_content"]
    assert f  # подресурсы по http найдены
    assert "2" in f[0]["evidence"]  # img + script, но НЕ обычная ссылка <a>


def test_findings_sorted_by_severity():
    rep = run_checks(Resp("http://x.example/", headers={"Server": "nginx/1"}), None, "http://x.example/")
    sevs = [f["severity"] for f in rep["findings"]]
    order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    assert sevs == sorted(sevs, key=lambda s: order[s])


def test_finding_shape():
    rep = run_checks(Resp("https://x.example/"), Resp("https://x.example/"), "https://x.example/")
    f = rep["findings"][0]
    assert {"id", "severity", "category", "title", "evidence", "why", "recommendation"} <= set(f)


# ---------- endpoint ----------
@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import create_app

    class FakeClient:
        def request(self, method, url, **kw):
            if url.startswith("http://"):
                return Resp(url.replace("http://", "https://"))  # http редиректит на https
            return Resp("https://site.example/", headers={"Server": "nginx/1.20"},
                        cookies=["sid=x; Path=/"], text="<img src='http://cdn/x.png'>")

    monkeypatch.setattr(cr, "HttpClient", lambda *a, **k: FakeClient())
    return TestClient(create_app())


def test_check_endpoint(client):
    r = client.post("/api/chaos/v2/check", json={"url": "site.example"}).json()  # без схемы → https
    assert r["https"] is True
    ids = {f["id"] for f in r["findings"]}
    assert "server_version" in ids
    assert "mixed_content" in ids
    assert "no_http_redirect" not in ids  # http редиректит на https в фейке


def test_old_chaos_generator_untouched(client):
    # старый /api/chaos/respond остаётся на месте
    assert client.get("/api/chaos/scenarios").status_code == 200
