"""Chaos — быстрая первичная диагностика безопасности сайта.

Chaos 1a: пассивная проверка одного URL (без атаки на сайт) — HTTPS, security
headers, cookies, CORS, раскрытие технологий, mixed content → честные findings.
Активные проверки, TLS-глубина и обход сайта — следующие субфазы.
"""

TOOL_ID = "chaos"
TOOL_TITLE = "Chaos"
TOOL_SUMMARY = "Быстрая проверка безопасности сайта по URL: HTTPS, заголовки, cookies, CORS, раскрытие данных."
