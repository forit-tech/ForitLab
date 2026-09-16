"""Каталог инструментов Forit Lab.

Витрина заявляет и то, что уже работает, и то, что запланировано: так видно
направление, и не нужно выдумывать отдельную страницу роадмапа.
"""

from __future__ import annotations

from .schemas import ToolInfo
from .tools.burner import TOOL_ID as BURNER_ID, TOOL_SUMMARY as BURNER_SUMMARY, TOOL_TITLE as BURNER_TITLE
from .tools.chaos import TOOL_ID as CHAOS_ID, TOOL_SUMMARY as CHAOS_SUMMARY, TOOL_TITLE as CHAOS_TITLE
from .tools.drift import TOOL_ID, TOOL_SUMMARY, TOOL_TITLE
from .tools.apifinder import TOOL_ID as FINDER_ID, TOOL_SUMMARY as FINDER_SUMMARY, TOOL_TITLE as FINDER_TITLE
from .tools.scrape import TOOL_ID as SCRAPE_ID, TOOL_SUMMARY as SCRAPE_SUMMARY, TOOL_TITLE as SCRAPE_TITLE
from .tools.unicodelab import TOOL_ID as UNICODE_ID, TOOL_SUMMARY as UNICODE_SUMMARY, TOOL_TITLE as UNICODE_TITLE

TOOLS: list[ToolInfo] = [
    ToolInfo(
        id=TOOL_ID,
        title=TOOL_TITLE,
        summary=TOOL_SUMMARY,
        status="available",
        base_path="/api/drift",
        docs_anchor="/docs#/Drift%20Lab",
    ),
    ToolInfo(
        id=CHAOS_ID,
        title=CHAOS_TITLE,
        summary=CHAOS_SUMMARY,
        status="available",
        base_path="/api/chaos",
        docs_anchor="/docs#/Chaos%20API",
    ),
    ToolInfo(
        id=BURNER_ID,
        title=BURNER_TITLE,
        summary=BURNER_SUMMARY,
        status="available",
        base_path="/api/burner",
        docs_anchor="/docs#/Data%20Burner",
    ),
    ToolInfo(
        id=UNICODE_ID,
        title=UNICODE_TITLE,
        summary=UNICODE_SUMMARY,
        status="available",
        base_path="/api/unicode",
        docs_anchor="/docs#/Unicode%20Crime%20Lab",
    ),
    ToolInfo(
        id=SCRAPE_ID,
        title=SCRAPE_TITLE,
        summary=SCRAPE_SUMMARY,
        status="available",
        base_path="/api/scrape",
        docs_anchor="/docs#/Scrape%20Lab",
    ),
    ToolInfo(
        id=FINDER_ID,
        title=FINDER_TITLE,
        summary=FINDER_SUMMARY,
        status="available",
        base_path="/api/apifinder",
        docs_anchor="/docs#/API%20Finder",
    ),
    ToolInfo(
        id="logs",
        title="Log Autopsy",
        summary="Разбор логов: шаблоны сообщений, всплески, аномальные семейства ошибок.",
        status="planned",
    ),
    ToolInfo(
        id="schema",
        title="Schema Watch",
        summary="Слежение за схемой публичного JSON API: added / type changed / nullable appeared.",
        status="planned",
    ),
]
