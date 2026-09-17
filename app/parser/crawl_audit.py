"""Crawl / Audit (1e MVP): пройти сайт и собрать технические факты о страницах.

Переиспользует ту же машинерию, что и Collect (CrawlScope/Frontier-логика,
ChunkedCursorExecutor, HttpClient, ResultFile). Отличие: вместо извлечения данных
по схеме — обход ВСЕХ same-origin ссылок (BFS с глубиной) и запись одной
audit-строки на страницу: url, статус, final_url/redirect, content-type, title,
глубина, страница-источник, broken/ошибка.

MVP: без SEO-правил, Lighthouse, security, external-crawl, sitemap, JS, auth.
"""

from __future__ import annotations

import time
from urllib.parse import urlparse

from ..config import settings
from ..crawl import CrawlScope
from ..exec.base import AdvanceResult, JobContext, JobPlan, StepBudget
from ..net import HttpClient
from ..net.errors import FetchError, RobotsDisallowedError, UnsafeUrlError
from .detect import source_type_from
from .results import ResultFile

KIND = "parser.crawl"


def build_plan(seed: str, options: dict | None = None) -> JobPlan:
    if not seed.lower().startswith(("http://", "https://")):
        raise ValueError("Обход требует URL")
    options = options or {}
    params = {
        "seed": seed,
        "max_pages": int(options.get("max_pages", settings.crawl_max_pages)),
        "max_depth": int(options.get("max_depth", settings.crawl_max_depth)),
        "allow_subdomains": bool(options.get("allow_subdomains", False)),
        "respect_robots": bool(options.get("respect_robots", True)),
    }
    return JobPlan(kind=KIND, params=params)


def _links_of(text: str, base_url: str) -> tuple[list[str], str]:
    from ..tools.scrape.parser import parse as parse_page

    page = parse_page(text, base_url)
    out: list[str] = []
    seen: set[str] = set()
    for link in page.links:
        href = link.href
        if href.startswith(("http://", "https://")) and href not in seen:
            seen.add(href)
            out.append(href)
    return out, (page.title or "")


class CrawlHandler:
    def __init__(self, client_factory=HttpClient) -> None:
        self._client_factory = client_factory

    def advance(self, params: dict, state: dict, budget: StepBudget, ctx: JobContext) -> AdvanceResult:
        if "frontier" not in state:
            state.update(frontier=[[params["seed"], 0, None]], visited=[], pages=0,
                         broken=0, redirects=0, errors=0, statuses={}, stopped="",
                         columns=["url", "status", "final_url", "redirected", "content_type", "title", "depth", "source", "broken", "error"])

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

        while state["frontier"] and units < per_step and not state["stopped"]:
            if time.monotonic() > deadline:
                break
            if state["pages"] >= max_pages:
                state["stopped"] = "достигнут лимит страниц"
                break

            url, depth, source = state["frontier"].pop(0)
            if url in state["visited"]:
                continue
            state["visited"].append(url)

            row = {"url": url, "depth": depth, "source": source, "status": None,
                   "final_url": url, "redirected": False, "content_type": "", "title": "",
                   "broken": False, "error": ""}
            try:
                resp = client.request("GET", url)
            except RobotsDisallowedError:
                row["error"] = "robots.txt запрещает"
                result.append([row]); state["pages"] += 1; units += 1; continue
            except (UnsafeUrlError, FetchError) as exc:
                row["error"] = exc.message
                row["broken"] = True
                errors.append(f"{url}: {exc.message}")
                result.append([row]); state["pages"] += 1; state["broken"] += 1; state["errors"] += 1; units += 1
                continue

            stype = source_type_from(resp.content_type, resp.body)
            row["status"] = resp.status
            row["final_url"] = resp.final_url
            row["redirected"] = bool(resp.redirect_chain) or (resp.final_url != url)
            row["content_type"] = resp.content_type
            row["broken"] = resp.status >= 400
            is_html = stype == "html"
            links, title = ([], "")
            if is_html:
                links, title = _links_of(resp.text, resp.final_url)
            row["title"] = title

            result.append([row])
            state["pages"] += 1
            units += 1
            state["statuses"][str(resp.status)] = state["statuses"].get(str(resp.status), 0) + 1
            if row["broken"]:
                state["broken"] += 1
            if row["redirected"]:
                state["redirects"] += 1

            # обход дальше: только html, успешный статус, в пределах глубины и scope
            if is_html and resp.status < 400 and depth < max_depth:
                for link in links:
                    if not scope.allows_navigation(link).allowed:
                        continue
                    if link in state["visited"]:
                        continue
                    if any(link == f[0] for f in state["frontier"]):
                        continue
                    state["frontier"].append([link, depth + 1, resp.final_url])

            if settings.collect_delay_ms:
                time.sleep(min(settings.collect_delay_ms, 1000) / 1000)

        if state["pages"] >= max_pages:
            state["stopped"] = state["stopped"] or "достигнут лимит страниц"
        done = (not state["frontier"]) or bool(state["stopped"]) or state["pages"] >= max_pages
        progress = min(1.0, state["pages"] / max_pages) if max_pages else 1.0
        partial = {
            "pages": state["pages"],
            "broken": state["broken"],
            "redirects": state["redirects"],
            "errors": state["errors"],
            "statuses": state["statuses"],
            "columns": state["columns"],
            "queued": len(state["frontier"]),
            "stopped_reason": state["stopped"] or (None if not done else "весь сайт обойдён"),
            "partial": bool(state["stopped"]),
            "sample": list(result.read(limit=8)),
        }
        return AdvanceResult(partial=partial, internal_state=state, progress=progress, done=done, errors=errors)
