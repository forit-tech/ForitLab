"""Юнит-тесты движков Chaos (Passive Security Check). Всё офлайн, без сети.

Каждый движок — чистая функция над разобранными данными. TLS проверяется на
разобранных данных сертификата (не на живом сокете).
"""

from __future__ import annotations

import datetime as dt

import pytest

from app.chaos import aggregate
from app.chaos.active_safe import check_http_methods, parse_allow
from app.chaos.content import check_content, page_title
from app.chaos.cookies import check_cookies, parse_cookie
from app.chaos.cors import check_cors
from app.chaos.csp import check_csp, parse_csp
from app.chaos.disclosure import check_disclosure
from app.chaos.headers import check_security_headers
from app.chaos.metadata import check_robots, check_security_txt, parse_security_txt
from app.chaos.models import finding, sort_findings, summarize
from app.chaos.redirects import check_redirect_chain, check_scheme
from app.chaos.tls import analyze_certificate, hostname_matches


def _ids(findings):
    return {f["id"] for f in findings}


def _by_id(findings, fid):
    return next(f for f in findings if f["id"] == fid)


# --------------------------------------------------------------------------
# models
# --------------------------------------------------------------------------
def test_finding_shape_and_extra():
    f = finding("x", "high", "t", "e", "w", "r", "cat", origin="https://a")
    assert {"id", "severity", "category", "title", "evidence", "why", "recommendation"} <= set(f)
    assert f["origin"] == "https://a"


def test_sort_and_summarize():
    fs = [finding("a", "low", *"tewr"), finding("b", "high", *"tewr"), finding("c", "info", *"tewr")]
    assert [f["severity"] for f in sort_findings(fs)] == ["high", "low", "info"]
    assert summarize(fs) == {"high": 1, "medium": 0, "low": 1, "info": 1}


# --------------------------------------------------------------------------
# headers
# --------------------------------------------------------------------------
def test_headers_all_missing():
    ids = _ids(check_security_headers({}, https=True))
    assert {"missing_hsts", "missing_nosniff", "missing_referrer_policy",
            "missing_permissions_policy", "missing_frame_protection",
            "missing_coop", "missing_corp", "missing_coep"} <= ids


def test_headers_good_empty():
    good = {
        "Strict-Transport-Security": "max-age=1", "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "strict-origin", "Permissions-Policy": "camera=()",
        "X-Frame-Options": "DENY", "Cross-Origin-Opener-Policy": "same-origin",
        "Cross-Origin-Resource-Policy": "same-origin", "Cross-Origin-Embedder-Policy": "require-corp",
    }
    assert check_security_headers(good, https=True) == []


def test_headers_hsts_only_when_https():
    assert "missing_hsts" not in _ids(check_security_headers({}, https=False))


def test_headers_frame_protection_via_csp():
    ids = _ids(check_security_headers({}, https=True, csp_raw="frame-ancestors 'none'"))
    assert "missing_frame_protection" not in ids


# --------------------------------------------------------------------------
# csp
# --------------------------------------------------------------------------
def test_csp_missing():
    assert _ids(check_csp(None)) == {"missing_csp"}
    assert _ids(check_csp("")) == {"missing_csp"}


def test_csp_good_strict_empty():
    assert check_csp("default-src 'self'") == []


def test_csp_unsafe_and_wildcard_and_http():
    ids = _ids(check_csp("default-src 'self'; script-src 'unsafe-inline' 'unsafe-eval' *; img-src http://cdn"))
    assert {"csp_unsafe_inline", "csp_unsafe_eval", "csp_wildcard_source", "csp_insecure_scheme"} <= ids


def test_parse_csp_structure():
    d = parse_csp("default-src 'self'; frame-ancestors 'none'; object-src 'none'")
    assert d["default-src"] == ["'self'"]
    assert "frame-ancestors" in d and "object-src" in d


# --------------------------------------------------------------------------
# cookies
# --------------------------------------------------------------------------
def test_cookie_parse():
    name, attrs, flags = parse_cookie("__Host-sid=abc; Path=/; Secure; SameSite=None")
    assert name == "__Host-sid"
    assert attrs["path"] == "/" and attrs["samesite"] == "None"
    assert "secure" in flags


def test_cookie_bad_flags_https():
    ids = _ids(check_cookies(["sid=abc; Path=/"], https=True))
    assert {"cookie_no_secure", "cookie_no_httponly", "cookie_no_samesite"} <= ids


def test_cookie_good_empty():
    assert check_cookies(["sid=1; Secure; HttpOnly; SameSite=Lax"], https=True) == []


def test_cookie_samesite_none_without_secure():
    ids = _ids(check_cookies(["sid=1; SameSite=None; HttpOnly"], https=True))
    assert "cookie_samesite_none_insecure" in ids


def test_cookie_host_prefix_violations():
    ids = _ids(check_cookies(["__Host-s=1; Domain=example.com; Path=/x"], https=True))
    assert {"cookie_host_prefix_insecure", "cookie_host_prefix_domain", "cookie_host_prefix_path"} <= ids


def test_cookie_host_prefix_ok():
    assert check_cookies(["__Host-s=1; Secure; HttpOnly; Path=/; SameSite=Lax"], https=True) == []


def test_cookie_secure_prefix_without_secure():
    ids = _ids(check_cookies(["__Secure-s=1; HttpOnly; SameSite=Lax"], https=True))
    assert "cookie_secure_prefix_insecure" in ids


# --------------------------------------------------------------------------
# cors
# --------------------------------------------------------------------------
def test_cors_wildcard_credentials_high():
    f = check_cors({"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Credentials": "true"})
    assert _by_id(f, "cors_wildcard_credentials")["severity"] == "high"


def test_cors_wildcard_low():
    ids = _ids(check_cors({"Access-Control-Allow-Origin": "*"}))
    assert ids == {"cors_wildcard"}


def test_cors_null_and_reflect():
    assert "cors_null_origin" in _ids(check_cors({"Access-Control-Allow-Origin": "null"}))
    ids = _ids(check_cors({"Access-Control-Allow-Origin": "https://evil.example",
                           "Access-Control-Allow-Credentials": "true"}))
    assert "cors_reflect_no_vary" in ids


def test_cors_none_empty():
    assert check_cors({}) == []


# --------------------------------------------------------------------------
# content
# --------------------------------------------------------------------------
def test_content_mixed_count():
    html = '<img src="http://c/x.png"><script src="http://c/a.js"></script><a href="http://e/p">l</a>'
    f = _by_id(check_content(html, https=True, page_url="https://x/"), "mixed_content")
    assert "2" in f["evidence"]  # img + script, не обычная ссылка


def test_content_forms_and_password_http():
    html = '<form action="http://x/login"><input type="password"></form>'
    ids = _ids(check_content(html, https=False, page_url="http://x/"))
    assert {"form_action_http", "form_over_http", "password_over_http"} <= ids
    assert _by_id(check_content(html, https=False), "password_over_http")["severity"] == "high"


def test_content_external_scripts_and_debug():
    assert "external_scripts" in _ids(check_content('<script src="https://cdn/a.js"></script>', https=True))
    assert "debug_disclosure" in _ids(check_content("Traceback (most recent call last):", https=True))


def test_content_clean_empty():
    assert check_content("<img src='https://cdn/x.png'>", https=True) == []


def test_page_title():
    assert page_title("<title> Hi </title>") == "Hi"


# --------------------------------------------------------------------------
# disclosure
# --------------------------------------------------------------------------
def test_disclosure_headers():
    ids = _ids(check_disclosure({"Server": "nginx/1.18.0", "X-Powered-By": "Express",
                                 "X-Runtime": "0.1"}))
    assert {"server_version", "powered_by", "tech_header_x-runtime"} <= ids


def test_disclosure_server_no_version_info():
    assert _by_id(check_disclosure({"Server": "cloudflare"}), "server_header")["severity"] == "info"


def test_disclosure_generator_meta():
    ids = _ids(check_disclosure({}, '<meta name="generator" content="WordPress 6.1">'))
    assert "generator_meta" in ids


def test_disclosure_clean_empty():
    assert check_disclosure({}, "<html></html>") == []


# --------------------------------------------------------------------------
# redirects
# --------------------------------------------------------------------------
class _Probe:
    def __init__(self, final_url, status=200):
        self.final_url = final_url
        self.status = status


def test_scheme_no_https_high():
    assert _by_id(check_scheme(False, "http", None), "no_https")["severity"] == "high"


def test_scheme_http_not_redirecting():
    assert "no_http_redirect" in _ids(check_scheme(True, "https", _Probe("http://x/")))
    assert check_scheme(True, "https", _Probe("https://x/")) == []


def test_redirect_chain_empty_safe():
    assert check_redirect_chain([], "https://x/", "https://x/") == []


def test_redirect_downgrade_and_cross_origin():
    chain = [{"url": "https://x/", "status": 302, "location": "http://x/insecure"}]
    ids = _ids(check_redirect_chain(chain, "https://x/", "http://x/insecure"))
    assert "redirect_downgrade" in ids


def test_redirect_loop_and_too_many():
    chain = [{"url": f"https://x/{i}", "status": 302, "location": "https://x/next"} for i in range(9)]
    chain.append({"url": "https://x/0", "status": 302, "location": "https://x/next"})  # повтор
    ids = _ids(check_redirect_chain(chain, "https://x/", "https://x/final"))
    assert {"redirect_loop", "redirect_too_many"} <= ids


# --------------------------------------------------------------------------
# tls (на разобранных данных сертификата)
# --------------------------------------------------------------------------
def _now():
    return dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)


def test_tls_expired():
    info = {"hostname": "x.example", "names": ["x.example"], "negotiated_version": "TLSv1.3",
            "not_after": dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc), "trusted": True}
    assert _by_id(analyze_certificate(info, now=_now()), "tls_cert_expired")["severity"] == "high"


def test_tls_expiring_soon():
    info = {"hostname": "x.example", "names": ["x.example"], "negotiated_version": "TLSv1.3",
            "not_after": dt.datetime(2026, 1, 10, tzinfo=dt.timezone.utc), "trusted": True}
    assert "tls_cert_expiring_soon" in _ids(analyze_certificate(info, now=_now()))


def test_tls_hostname_mismatch():
    info = {"hostname": "x.example", "names": ["y.example", "*.other.example"],
            "not_after": dt.datetime(2027, 1, 1, tzinfo=dt.timezone.utc), "trusted": True}
    assert "tls_cert_hostname_mismatch" in _ids(analyze_certificate(info, now=_now()))


def test_tls_obsolete_version_and_untrusted():
    info = {"hostname": "x.example", "names": ["x.example"], "negotiated_version": "TLSv1",
            "not_after": dt.datetime(2027, 1, 1, tzinfo=dt.timezone.utc), "self_signed": True}
    ids = _ids(analyze_certificate(info, now=_now()))
    assert {"tls_version_obsolete", "tls_cert_untrusted"} <= ids


def test_tls_error_reported():
    assert "tls_handshake_failed" in _ids(analyze_certificate({"hostname": "x", "error": "boom"}, now=_now()))


def test_tls_good_cert_clean():
    info = {"hostname": "x.example", "names": ["x.example", "www.x.example"],
            "negotiated_version": "TLSv1.3",
            "not_after": dt.datetime(2027, 1, 1, tzinfo=dt.timezone.utc), "trusted": True}
    assert analyze_certificate(info, now=_now()) == []


def test_hostname_matches_wildcard():
    assert hostname_matches("a.example.com", ["*.example.com"])
    assert not hostname_matches("a.b.example.com", ["*.example.com"])
    assert hostname_matches("x.example", ["X.EXAMPLE"])


# --------------------------------------------------------------------------
# metadata
# --------------------------------------------------------------------------
def test_security_txt_present_and_fields():
    body = "Contact: mailto:sec@x.example\nExpires: 2099-01-01T00:00:00Z\n"
    ids = _ids(check_security_txt(200, body, "text/plain"))
    assert "security_txt_present" in ids and "security_txt_no_contact" not in ids


def test_security_txt_missing_and_no_contact():
    assert "security_txt_missing" in _ids(check_security_txt(404, ""))
    ids = _ids(check_security_txt(200, "Expires: 2099-01-01T00:00:00Z\n", "text/plain"))
    assert "security_txt_no_contact" in ids


def test_security_txt_expired():
    body = "Contact: mailto:s@x\nExpires: 2000-01-01T00:00:00Z\n"
    assert "security_txt_expired" in _ids(check_security_txt(200, body, "text/plain"))


def test_parse_security_txt():
    fields = parse_security_txt("# c\nContact: a\nContact: b\nExpires: z\n")
    assert fields["contact"] == ["a", "b"] and fields["expires"] == ["z"]


def test_robots_present_missing():
    assert "robots_present" in _ids(check_robots(200, "User-agent: *"))
    assert "robots_missing" in _ids(check_robots(404, None))


# --------------------------------------------------------------------------
# active_safe
# --------------------------------------------------------------------------
def test_options_methods_trace_write():
    ids = _ids(check_http_methods("GET, POST, PUT, TRACE, OPTIONS"))
    assert {"http_methods_allowed", "http_trace_declared", "http_write_methods_declared"} <= ids


def test_options_empty():
    assert check_http_methods(None) == []
    assert parse_allow("GET, POST") == {"GET", "POST"}


# --------------------------------------------------------------------------
# aggregate — origin vs page (сертификат один раз)
# --------------------------------------------------------------------------
def test_aggregate_pages_dedup_and_counts():
    pages = [
        {"url": "https://s/a", "findings": [finding("missing_csp", "medium", *"tewr"),
                                            finding("missing_csp", "medium", *"tewr")]},  # дубль на странице
        {"url": "https://s/b", "findings": [finding("missing_csp", "medium", *"tewr")]},
        {"url": "https://s/c", "findings": [finding("powered_by", "low", *"tewr")]},
    ]
    agg = aggregate.aggregate_pages(pages, checked_pages=3)
    csp = _by_id(agg, "missing_csp")
    assert csp["affected_pages"] == 2 and csp["checked_pages"] == 3
    assert len(csp["examples"]) == 2


def test_build_site_report_origin_once():
    agg: dict = {}
    for url in ("https://s/1", "https://s/2", "https://s/3"):
        aggregate.update_agg(agg, url, [finding("missing_csp", "medium", *"tewr")])
    # сертификат «пришёл» origin-уровнем — должен появиться ОДИН раз, не на каждую страницу
    origin = [finding("tls_cert_expired", "high", *"tewr", origin="https://s"),
              finding("tls_cert_expired", "high", *"tewr", origin="https://s")]
    report = aggregate.build_site_report(agg, checked_pages=3, origin_findings=origin)
    assert _by_id(report["aggregated_findings"], "missing_csp")["affected_pages"] == 3
    tls = [f for f in report["origin_findings"] if f["id"] == "tls_cert_expired"]
    assert len(tls) == 1  # ОДИН раз, не 3
    assert all(a["id"] != "tls_cert_expired" for a in report["aggregated_findings"])
