"""Multi-page collection: каталог из N страниц → один датасет.

Обработчик для ChunkedCursorExecutor: каждый step() обходит порцию страниц
(в рамках бюджета времени/страниц), применяет схему извлечения 1b к каждой,
дописывает строки в отдельный append-only датасет (не в состояние джобы),
определяет следующую страницу и копит schema drift между страницами.

Всё наружу — через общий HttpClient (SSRF/pinning/robots). Секреты в состояние
джобы не пишутся (аутентифицированный многостраничный сбор в текущем окружении
недоступен — это отдельная capability). При достижении лимитов Host-0 —
partial=true и точная причина остановки, без фейкового «успеха».
"""

from __future__ import annotations

import json
import re
import shutil
import time

from ..config import settings
from ..exec.base import AdvanceResult, JobContext, JobPlan, StepBudget
from ..net import HttpClient
from ..net.errors import FetchError, RobotsDisallowedError, UnsafeUrlError
from ..crawl import CrawlScope
from .detect import source_type_from
from .models import ExtractionSchema, SourceKind
from .results import ResultFile

KIND = "parser.collect"

_NUM = re.compile(r"^-?\d[\d\s.,]*$")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}|\d{2}[./]\d{2}[./]\d{4}")


# --------------------------------------------------------------------------
# план
# --------------------------------------------------------------------------
def build_plan(seed: str, schema: ExtractionSchema, options: dict | None = None) -> JobPlan:
    from . import extract as extract_mod

    if not seed.lower().startswith(("http://", "https://")):
        raise ValueError("Многостраничный сбор требует URL-источника (не вставленный HTML/JSON)")
    extract_mod.validate_schema(schema)
    options = options or {}
    params = {
        "seed": seed,
        "schema": schema.to_dict(),
        "max_pages": int(options.get("max_pages", settings.collect_max_pages)),
        "max_rows": int(options.get("max_rows", settings.collect_max_rows)),
        "allow_subdomains": bool(options.get("allow_subdomains", False)),
        "respect_robots": bool(options.get("respect_robots", True)),
        "pagination": options.get("pagination", "auto"),
    }
    return JobPlan(kind=KIND, params=params)


# --------------------------------------------------------------------------
# извлечение одной страницы
# --------------------------------------------------------------------------
def _extract_page(resp, schema: ExtractionSchema, stype: str, remaining: int) -> list[dict]:
    from . import extract as extract_mod
    from . import sources as sources_mod

    if schema.source_kind == SourceKind.REPEATED_DOM:
        res = extract_mod.apply_schema(resp.text, schema, resp.final_url, limit=remaining)
        return res["rows"]
    # json-источники
    if stype in ("json", "jsonl"):
        try:
            data = json.loads(resp.text)
        except (json.JSONDecodeError, ValueError):
            data = None
        records = sources_mod._largest_record_array(data) if data is not None else []
    else:
        records = sources_mod.json_records(resp.text, resp.final_url, schema.source_kind)
    fields = [f.name for f in schema.fields] or None
    return extract_mod.project_json(records, fields, limit=remaining)["rows"]


# --------------------------------------------------------------------------
# schema drift между страницами
# --------------------------------------------------------------------------
def _guess_type(v: str) -> str:
    s = str(v).strip()
    if not s:
        return "empty"
    if s.startswith(("http://", "https://")):
        return "url"
    if _NUM.match(s):
        return "number"
    if _DATE.search(s):
        return "date"
    return "text"


def _update_drift(drift: dict, rows: list[dict]) -> None:
    for row in rows:
        for k, v in row.items():
            d = drift.setdefault(k, {"present": 0, "types": {}})
            if v not in (None, ""):
                d["present"] += 1
                t = _guess_type(v)
                d["types"][t] = d["types"].get(t, 0) + 1


def summarize_drift(drift: dict, total_rows: int) -> list[dict]:
    out = []
    for field, d in drift.items():
        types = d.get("types", {})
        dominant = max(types, key=types.get) if types else "empty"
        mixed = len([t for t in types if t not in ("empty",)]) > 1
        present_pct = round(100 * d.get("present", 0) / total_rows) if total_rows else 0
        out.append({
            "field": field,
            "present_pct": present_pct,
            "dominant_type": dominant,
            "mixed_types": mixed,
            "types": types,
        })
    return out


# --------------------------------------------------------------------------
# обработчик step
# --------------------------------------------------------------------------
class CollectHandler:
    def __init__(self, client_factory=HttpClient) -> None:
        self._client_factory = client_factory  # подменяется в тестах

    def advance(self, params: dict, state: dict, budget: StepBudget, ctx: JobContext) -> AdvanceResult:
        if "frontier" not in state:
            state.update(frontier=[params["seed"]], visited=[], pages=0, rows=0, drift={}, stopped="", columns=[])

        schema = ExtractionSchema.from_dict(params["schema"])
        scope = CrawlScope.single_origin(
            params["seed"],
            allow_subdomains=params.get("allow_subdomains", False),
            max_pages=params.get("max_pages", settings.collect_max_pages),
            respect_robots=params.get("respect_robots", True),
        )
        result = ResultFile(ctx.result_dir, ctx.job_id)
        max_pages = min(int(params.get("max_pages", settings.collect_max_pages)), settings.collect_max_pages)
        max_rows = min(int(params.get("max_rows", settings.collect_max_rows)), settings.collect_max_rows)
        paginate = params.get("pagination", "auto") != "none"
        pages_per_step = min(budget.max_units or settings.collect_pages_per_step, settings.collect_pages_per_step)
        deadline = time.monotonic() + min(budget.max_ms, settings.collect_step_max_ms) / 1000
        client = self._client_factory()
        errors: list[str] = []
        units = 0

        while state["frontier"] and units < pages_per_step and not state["stopped"]:
            if time.monotonic() > deadline:
                break
            if state["pages"] >= max_pages:
                state["stopped"] = "достигнут лимит страниц"
                break
            if state["rows"] >= max_rows:
                state["stopped"] = "достигнут лимит строк"
                break
            if not self._disk_ok(ctx):
                state["stopped"] = "недостаточно места на диске (Host-0)"
                break
            if result.size() >= settings.collect_result_max_bytes:
                state["stopped"] = "достигнут лимит размера датасета"
                break

            url = state["frontier"].pop(0)
            if url in state["visited"]:
                continue
            if not scope.allows_navigation(url).allowed:
                continue
            state["visited"].append(url)

            try:
                resp = client.request("GET", url)
            except (UnsafeUrlError, FetchError, RobotsDisallowedError) as exc:
                errors.append(f"{url}: {exc.message}")
                continue

            stype = source_type_from(resp.content_type, resp.body)
            remaining = max_rows - state["rows"]
            try:
                rows = _extract_page(resp, schema, stype, remaining)
            except Exception as exc:  # noqa: BLE001 — плохая страница не роняет весь сбор
                errors.append(f"{url}: извлечение не удалось ({type(exc).__name__})")
                rows = []

            # пустая НЕ первая страница = ушли за конец каталога: не считаем её
            if not rows and state["pages"] > 0:
                break

            if len(rows) > remaining:
                rows = rows[:remaining]
                state["stopped"] = "достигнут лимит строк"
            result.append(rows)
            _update_drift(state["drift"], rows)
            state["rows"] += len(rows)
            state["pages"] += 1
            units += 1
            if state["rows"] >= max_rows:
                state["stopped"] = state["stopped"] or "достигнут лимит строк"
            if state["pages"] >= max_pages:
                state["stopped"] = state["stopped"] or "достигнут лимит страниц"
            if rows and not state["columns"]:
                # порядок колонок фиксируем по первой странице
                state["columns"] = [f.name for f in schema.fields] or list(rows[0].keys())

            if result.size() >= settings.collect_result_max_bytes:
                state["stopped"] = "достигнут лимит размера датасета"
                break
            # пустая страница = конец каталога: не продолжаем инкремент ?page бесконечно
            if paginate and not state["stopped"] and rows:
                from .pagination import detect_next

                _, nxt = detect_next(source_type=stype, text=resp.text, current_url=resp.final_url, headers=resp.headers)
                if nxt and nxt not in state["visited"] and scope.allows_navigation(nxt).allowed:
                    if nxt not in state["frontier"]:
                        state["frontier"].append(nxt)
            if settings.collect_delay_ms:
                time.sleep(min(settings.collect_delay_ms, 1000) / 1000)

        done = (not state["frontier"]) or bool(state["stopped"]) or state["pages"] >= max_pages or state["rows"] >= max_rows
        progress = min(1.0, state["pages"] / max_pages) if max_pages else 1.0
        partial = {
            "pages": state["pages"],
            "rows": state["rows"],
            "columns": state["columns"],
            "stopped_reason": state["stopped"] or (None if not done else "все страницы обойдены"),
            "partial": bool(state["stopped"]),
            "schema_drift": summarize_drift(state["drift"], state["rows"]),
            "sample": list(result.read(limit=3)),
            "queued": len(state["frontier"]),
        }
        return AdvanceResult(partial=partial, internal_state=state, progress=progress, done=done, errors=errors)

    @staticmethod
    def _disk_ok(ctx: JobContext) -> bool:
        try:
            return shutil.disk_usage(str(ctx.result_dir)).free > settings.collect_min_free_bytes
        except OSError:
            return True  # не смогли измерить — не блокируем
