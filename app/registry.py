"""Каталог инструментов Forit Lab (витрина).

Шесть инструментов верхнего уровня. Старые технические названия
(Scrape / Harvester / Drift / Burner / API Finder / Unicode Crime Lab) наружу
не выводятся — их эндпоинты остаются смонтированными для совместимости, но в
витрине их нет. Web Parser поглотил Scrape/Harvester; новый Unicode — старый
Unicode Crime Lab.
"""

from __future__ import annotations

from .schemas import ToolInfo
from .parser import TOOL_ID as PARSER_ID, TOOL_SUMMARY as PARSER_SUMMARY, TOOL_TITLE as PARSER_TITLE
from .chaos import TOOL_ID as CHAOS_ID, TOOL_SUMMARY as CHAOS_SUMMARY, TOOL_TITLE as CHAOS_TITLE
from .file_inspector import TOOL_ID as FILE_ID, TOOL_SUMMARY as FILE_SUMMARY, TOOL_TITLE as FILE_TITLE
from .unicode_tool import TOOL_ID as UNI_ID, TOOL_SUMMARY as UNI_SUMMARY, TOOL_TITLE as UNI_TITLE
from .batch_rename import TOOL_TITLE as RENAME_TITLE

TOOLS: list[ToolInfo] = [
    ToolInfo(
        id=PARSER_ID,
        title=PARSER_TITLE,
        summary=PARSER_SUMMARY,
        status="available",
        base_path="/api/parser",
        docs_anchor="/docs#/Web%20Parser",
    ),
    ToolInfo(
        id="chaos",
        title=CHAOS_TITLE,
        summary=CHAOS_SUMMARY,
        status="available",
        base_path="/api/chaos/v2",
        docs_anchor="/docs#/Chaos",
    ),
    ToolInfo(
        id=FILE_ID,
        title=FILE_TITLE,
        summary=FILE_SUMMARY,
        status="available",
        base_path="/api/file",
        docs_anchor="/docs#/File%20Inspector",
    ),
    ToolInfo(
        id=UNI_ID,
        title=UNI_TITLE,
        summary=UNI_SUMMARY,
        status="available",
        base_path="/api/unicode2",
        docs_anchor="/docs#/Unicode",
    ),
    ToolInfo(
        id="rename",
        title=RENAME_TITLE,
        summary="Массовое переименование файлов: правила, превью old→new, проверка конфликтов, выгрузка ZIP.",
        status="available",
        base_path="/api/rename",
        docs_anchor="/docs#/Batch%20Rename",
    ),
    ToolInfo(
        id="print",
        title="Print",
        summary="Подготовка текста к печати: A4/Letter, поля, колонтитулы, предпросмотр и печать через браузер.",
        status="available",
        base_path="",
    ),
]
