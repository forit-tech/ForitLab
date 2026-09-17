"""CrawlScope: строгая семантика host/scheme/port/subdomain/redirect/resource + бюджет."""

from __future__ import annotations

from app.crawl.scope import CrawlBudget, CrawlScope, HostRule


def test_strict_rule_distinguishes_scheme_port_host():
    scope = CrawlScope.single_origin("https://example.com:443")
    assert scope.allows_navigation("https://example.com/page").allowed
    # другая схема
    assert not scope.allows_navigation("http://example.com/page").allowed
    # другой порт
    assert not scope.allows_navigation("https://example.com:8443/page").allowed
    # поддомен по умолчанию запрещён
    assert not scope.allows_navigation("https://api.example.com/page").allowed
    # чужой хост
    assert not scope.allows_navigation("https://evil.example.com/page").allowed


def test_subdomains_opt_in():
    scope = CrawlScope.single_origin("https://example.com", allow_subdomains=True)
    assert scope.allows_navigation("https://api.example.com/x").allowed
    # похожий, но чужой домен не проходит
    assert not scope.allows_navigation("https://example.com.evil.com/x").allowed


def test_external_resources_policy():
    scope = CrawlScope.single_origin("https://example.com")
    assert not scope.allows_resource("https://cdn.other.com/a.js").allowed
    scope.allow_external_resources = True
    assert scope.allows_resource("https://cdn.other.com/a.js").allowed
    # навигация при этом всё равно строгая
    assert not scope.allows_navigation("https://cdn.other.com/a.js").allowed


def test_redirect_policy():
    scope = CrawlScope.single_origin("https://example.com")
    assert scope.allows_redirect("https://example.com/a", "https://example.com/b").allowed
    assert not scope.allows_redirect("https://example.com/a", "https://evil.com/b").allowed
    scope.follow_redirects = False
    assert not scope.allows_redirect("https://example.com/a", "https://example.com/b").allowed


def test_multiple_rules():
    scope = CrawlScope(
        seeds=["https://a.example"],
        allowed=[HostRule.from_url("https://a.example"), HostRule.from_url("https://b.example")],
    )
    assert scope.allows_navigation("https://a.example/x").allowed
    assert scope.allows_navigation("https://b.example/y").allowed
    assert not scope.allows_navigation("https://c.example/z").allowed


def test_budget_hard_stops():
    scope = CrawlScope.single_origin("https://example.com", max_pages=2, max_requests=3, max_bytes=1000)
    budget = CrawlBudget.from_scope(scope)
    assert budget.can_request()
    budget.spend_request(400)
    budget.spend_page()
    assert budget.can_request()
    budget.spend_request(400)
    budget.spend_page()
    assert not budget.can_request()  # достигнут max_pages
    assert budget.exhausted and budget.stopped_reason
