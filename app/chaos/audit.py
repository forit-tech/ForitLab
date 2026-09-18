"""Chaos 1b — Site-wide Passive Audit.

Склейка: тот же same-origin Crawl (robots, dedup, глубина, progress/cancel,
лимит страниц) + те же проверки passive.run_checks на КАЖДОЙ HTML-странице,
а затем агрегация findings по id: «Missing CSP — 18/20 страниц, примеры: …».

Никаких новых правил безопасности — только «много response → много findings →
агрегировать». passive.py не меняется.
"""

from __future__ import annotations

import time

from urllib.parse import urlparse, urlunparse

from ..config import settings
from ..crawl import CrawlScope
from ..exec.base import AdvanceResult, JobContext, JobPlan, StepBudget
from ..net import HttpClient
from ..net.errors import FetchError, RobotsDisallowedError, UnsafeUrlError
from ..parser.detect import source_type_from
from ..parser.results import ResultFile
from . import aggregate
from .active_safe import check_http_methods
from .metadata import check_robots, check_security_txt
from .passive import run_checks
from .tls import check_tls_origin

KIND = "chaos.audit"
_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}


def build_plan(seed: str, options: dict | None = None) -> JobPlan:
    if not seed.lower().startswith(("http://", "https://")):
        raise ValueError("Проверка сайта требует URL")
    options = options or {}
    return JobPlan(kind=KIND, params={
        "seed": seed,
        "max_pages": int(options.get("max_pages", settings.crawl_max_pages)),
        "max_depth": int(options.get("max_depth", settings.crawl_max_depth)),
        "allow_subdomains": bool(options.get("allow_subdomains", False)),
        "respect_robots": bool(options.get("respect_robots", True)),
    })


def _links_and_title(text: str, base_url: str):
    from ..tools.scrape.parser import parse as parse_page

    page = parse_page(text, base_url)
    links = [l.href for l in page.links if l.href.startswith(("http://", "https://"))]
    return links, (page.title or "")


class SecurityAuditHandler:
    def __init__(self, client_factory=HttpClient) -> None:
        self._client_factory = client_factory

    def advance(self, params: dict, state: dict, budget: StepBudget, ctx: JobContext) -> AdvanceResult:
        if "frontier" not in state:
            state.update(frontier=[[params["seed"], 0]], visited=[], checked=0, failed=0,
                         agg={}, stopped="", columns=["url", "status", "content_type", "findings", "ids"],
                         origin_done=False, origin_findings=[])

        scope = CrawlScope.single_origin(
            params["seed"],
            allow_subdomains=params.get("allow_subdomains", False),
            max_pages=params.get("max_pages", settings.crawl_max_pages),
            respect_robots=params.get("respect_robots", True),
        )
        result = ResultFile(ctx.result_dir, ctx.job_id)
        max_pages = min(int(params.get("max_pages", settings.crawl_max_pages)), settings.crawl_max_pages)
        max_depth = int(params.get("max_depth", settings.crawl_max_depth))
        per_step = min(budget.max_units or settings.collect_pages_per_step, settings.collect_pages_per_step)
        deadline = time.monotonic() + min(budget.max_ms, settings.collect_step_max_ms) / 1000
        client = self._client_factory()
        errors: list[str] = []
        units = 0

        # origin-level проверки (TLS/security.txt/robots/OPTIONS) — ОДИН раз на весь аудит
        if not state["origin_done"]:
            state["origin_findings"] = self._origin_probe(params["seed"], client)
            state["origin_done"] = True

        while state["frontier"] and units < per_step and not state["stopped"]:
            if time.monotonic() > deadline:
                break
            if state["checked"] + state["failed"] >= max_pages:
                state["stopped"] = "достигнут лимит страниц"
                break

            url, depth = state["frontier"].pop(0)
            if url in state["visited"]:
                continue
            state["visited"].append(url)

            try:
                resp = client.request("GET", url)
            except (UnsafeUrlError, FetchError, RobotsDisallowedError) as exc:
                state["failed"] += 1
                errors.append(f"{url}: {exc.message}")
                units += 1
                continue

            stype = source_type_from(resp.content_type, resp.body)
            is_html = stype == "html"
            if not is_html or resp.status >= 400:
                # не HTML или ошибка — не аудируем, но ссылки не тянем
                state["failed"] += 1 if resp.status >= 400 else 0
                units += 1
                continue

            findings = run_checks(resp, None, url)["findings"]
            aggregate.update_agg(state["agg"], url, findings)
            ids = sorted({f["id"] for f in findings})

            result.append([{"url": url, "status": resp.status, "content_type": resp.content_type,
                            "findings": len(ids), "ids": ";".join(ids)}])
            state["checked"] += 1
            units += 1

            links, _title = _links_and_title(resp.text, resp.final_url)
            if depth < max_depth:
                for link in links:
                    if not scope.allows_navigation(link).allowed:
                        continue
                    if link in state["visited"] or any(link == f[0] for f in state["frontier"]):
                        continue
                    state["frontier"].append([link, depth + 1])

            if settings.collect_delay_ms:
                time.sleep(min(settings.collect_delay_ms, 1000) / 1000)

        if state["checked"] + state["failed"] >= max_pages:
            state["stopped"] = state["stopped"] or "достигнут лимит страниц"
        done = (not state["frontier"]) or bool(state["stopped"])
        checked = state["checked"]
        aggregated = aggregate.finalize_pages(state["agg"], checked)
        origin_findings = aggregate.dedupe_origin(state["origin_findings"])
        # severity counts = число РАЗНЫХ page-проблем сайта по уровню (origin считаем отдельно)
        sev = {s: sum(1 for a in aggregated if a["severity"] == s) for s in ("high", "medium", "low", "info")}
        progress = min(1.0, (checked + state["failed"]) / max_pages) if max_pages else 1.0
        partial = {
            "pages_checked": checked,
            "pages_failed": state["failed"],
            "queued": len(state["frontier"]),
            "summary": sev,
            "aggregated_findings": aggregated,
            "origin_findings": origin_findings,
            "stopped_reason": state["stopped"] or (None if not done else "весь сайт проверен"),
            "partial": bool(state["stopped"]),
        }
        return AdvanceResult(partial=partial, internal_state=state, progress=progress, done=done, errors=errors)

    # ------------------------------------------------------------------
    def _origin_probe(self, seed: str, client) -> list[dict]:
        """Origin-level проверки ОДИН раз: TLS (если https), security.txt, robots, OPTIONS."""
        parsed = urlparse(seed)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        findings: list[dict] = []

        def _fetch(path: str, method: str = "GET"):
            try:
                return client.request(method, urlunparse((parsed.scheme, parsed.netloc, path, "", "", "")),
                                      respect_robots=False)
            except (UnsafeUrlError, FetchError, RobotsDisallowedError):
                return None

        st_resp = _fetch("/.well-known/security.txt")
        if st_resp is not None:
            findings += check_security_txt(st_resp.status, st_resp.text,
                                           getattr(st_resp, "content_type", ""), origin=origin)
        else:
            findings += check_security_txt(None, "", origin=origin)

        rb_resp = _fetch("/robots.txt")
        findings += check_robots(rb_resp.status if rb_resp else None,
                                 rb_resp.text if rb_resp else None, origin=origin)

        opt = _fetch("/", method="OPTIONS")
        if opt is not None:
            allow = {k.lower(): v for k, v in (opt.headers or {}).items()}.get("allow")
            findings += check_http_methods(allow, origin=origin)

        if parsed.scheme == "https" and parsed.hostname:
            try:
                findings += check_tls_origin(parsed.hostname, parsed.port or 443)
            except Exception:  # noqa: BLE001 — origin-проба не должна ронять аудит
                pass

        return findings
