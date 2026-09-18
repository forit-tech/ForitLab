"""Unicode — бытовой инструмент для чистой копии текста.

Главное действие — Clean Copy: безопасно убрать невидимый мусор, привести
экзотические пробелы к обычному, нормализовать в NFC — не трогая смысл текста.
Рядом — раздельные операции inspect / normalize / escape.

Новый пакет (prefix `/api/unicode2`), строится с нуля и заменит старый
`app/tools/unicodelab/` в навигации/реестре на уровне оркестратора.
"""

from __future__ import annotations

TOOL_ID = "unicode2"
TOOL_TITLE = "Unicode"
TOOL_SUMMARY = (
    "Чистая копия текста: убирает невидимые символы и BOM, приводит NBSP и "
    "экзотические пробелы к обычному, нормализует в NFC. Плюс inspect, "
    "normalize (NFC/NFD/NFKC/NFKD) и escape/unescape."
)

#: Потолок длины входного текста (в кодовых точках). Защита воркера от
#: разбора мегабайтных строк символ за символом.
MAX_TEXT_CHARS = 200_000

__all__ = ["TOOL_ID", "TOOL_TITLE", "TOOL_SUMMARY", "MAX_TEXT_CHARS"]
