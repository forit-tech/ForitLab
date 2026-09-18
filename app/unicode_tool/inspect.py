"""Анализ текста: что за символы внутри и что с ними делать.

Классификация символов (`classify_char`) — единый источник правды и для
отчёта inspect, и для безопасной очистки в :mod:`clean`. Никаких внешних
зависимостей: только stdlib `unicodedata`.
"""

from __future__ import annotations

import unicodedata
from typing import Optional

# --- Наборы «подозрительных» кодовых точек ------------------------------------

#: Невидимые нулевой ширины: выглядят как ничто, но ломают точное сравнение.
ZERO_WIDTH = {0x200B, 0x200C, 0x200D, 0x2060}  # ZWSP, ZWNJ, ZWJ, WORD JOINER

#: BOM / ZERO WIDTH NO-BREAK SPACE — мусор в начале скопированного текста.
BOM = {0xFEFF}

#: Неразрывный пробел — не U+0020, но выглядит как пробел.
NBSP = {0x00A0}

#: Прочие необычные пробелы: en/em/thin/hair/… и широкие CJK.
UNUSUAL_SPACES = set(range(0x2000, 0x200B))  # U+2000..U+200A
UNUSUAL_SPACES |= {0x202F, 0x205F, 0x3000, 0x1680}  # NNBSP, MMSP, IDEOGRAPHIC, OGHAM

#: Управление направлением текста (bidi): умеет переворачивать отображение.
BIDI = {
    0x202A, 0x202B, 0x202C, 0x202D, 0x202E,  # embeddings / overrides / PDF
    0x2066, 0x2067, 0x2068, 0x2069,          # isolates / PDI
    0x200E, 0x200F,                          # LRM / RLM
}

#: Мягкий перенос — невидим, но участвует в сравнении и поиске.
SOFT_HYPHEN = {0x00AD}

#: Типографские кавычки — легитимны, поэтому только помечаем (action=keep).
SMART_QUOTES = {0x201C, 0x201D, 0x2018, 0x2019}  # “ ” ‘ ’

#: Типографские тире — тоже легитимны, только помечаем.
DASHES = {0x2013, 0x2014}  # – —

# --- Действия -----------------------------------------------------------------

REMOVE = "remove"
REPLACE = "replace"
KEEP = "keep"

#: Чем заменяем всё «пробелоподобное» при безопасной очистке.
SPACE = " "


class CharClass:
    """Результат классификации одного символа."""

    __slots__ = ("kind", "action", "replacement")

    def __init__(self, kind: str, action: str, replacement: Optional[str] = None) -> None:
        self.kind = kind
        self.action = action
        self.replacement = replacement


def classify_char(char: str) -> Optional[CharClass]:
    """Классифицировать символ или вернуть ``None``, если он безобиден.

    Единая точка правды: и inspect, и clean_copy опираются на неё, поэтому
    отчёт и фактическая очистка не расходятся.
    """
    code = ord(char)

    if code in BOM:
        return CharClass("bom", REMOVE)
    if code in ZERO_WIDTH:
        return CharClass("zero_width", REMOVE)
    if code in BIDI:
        return CharClass("bidi", REMOVE)
    if code in SOFT_HYPHEN:
        return CharClass("soft_hyphen", REMOVE)
    if code in NBSP:
        return CharClass("nbsp", REPLACE, SPACE)
    if code in UNUSUAL_SPACES:
        return CharClass("unusual_space", REPLACE, SPACE)
    if code in SMART_QUOTES:
        return CharClass("smart_quote", KEEP)
    if code in DASHES:
        return CharClass("dash", KEEP)

    # Управляющие символы (Cc), кроме привычных \t \n \r.
    if char not in "\t\n\r" and unicodedata.category(char) == "Cc":
        return CharClass("control", REMOVE)

    return None


def char_name(char: str) -> str:
    """Имя символа из UCD или запасной вариант, если имени нет."""
    try:
        return unicodedata.name(char)
    except ValueError:
        return f"U+{ord(char):04X}"


def find_issues(text: str) -> list[dict]:
    """Список проблемных символов с индексом, kind, action и метаданными."""
    issues: list[dict] = []
    for index, char in enumerate(text):
        info = classify_char(char)
        if info is None:
            continue
        issues.append(
            {
                "index": index,
                "char": char,
                "codepoint": f"U+{ord(char):04X}",
                "name": char_name(char),
                "category": unicodedata.category(char),
                "kind": info.kind,
                "action": info.action,
            }
        )
    return issues


# --- mixed_script: простой и честный детект по имени символа ------------------

def _alpha_script(char: str) -> Optional[str]:
    """Письменность буквы по префиксу имени UCD (или ``None`` для не-букв)."""
    if not char.isalpha():
        return None
    name = char_name(char)
    for script in ("LATIN", "CYRILLIC", "GREEK", "ARMENIAN"):
        if name.startswith(script):
            return script.lower()
    return None


def find_mixed_script_words(text: str) -> list[dict]:
    """Слова, где смешаны письменности (напр. кириллица + латиница).

    Намеренно простой детект: разбиваем на слова, у каждой буквы берём
    письменность по имени символа. Никакого homoglyph-движка — только факт
    смешения. Ненадёжные случаи (символы без внятной письменности) не трогаем.
    """
    findings: list[dict] = []
    word_chars: list[str] = []
    start = 0

    def flush(chars: list[str], begin: int) -> None:
        if len(chars) < 2:
            return
        scripts = {s for s in (_alpha_script(ch) for ch in chars) if s}
        if len(scripts) > 1:
            findings.append(
                {
                    "word": "".join(chars),
                    "index": begin,
                    "scripts": sorted(scripts),
                }
            )

    for index, char in enumerate(text):
        if char.isalpha():
            if not word_chars:
                start = index
            word_chars.append(char)
        else:
            flush(word_chars, start)
            word_chars = []
    flush(word_chars, start)

    return findings


def normalization_report(text: str) -> dict:
    """Длины во всех формах нормализации и флаг is_nfc."""
    nfc = unicodedata.normalize("NFC", text)
    return {
        "is_nfc": text == nfc,
        "nfc_len": len(nfc),
        "nfd_len": len(unicodedata.normalize("NFD", text)),
        "nfkc_len": len(unicodedata.normalize("NFKC", text)),
        "nfkd_len": len(unicodedata.normalize("NFKD", text)),
    }


def inspect_text(text: str) -> dict:
    """Полный отчёт по тексту (UnicodeReport).

    Ключи:
      - length: длина в кодовых точках;
      - bytes: длина в байтах UTF-8;
      - issues: список проблемных символов (см. :func:`find_issues`);
      - issues_by_kind: сводка по kind;
      - normalization: длины форм + is_nfc;
      - mixed_script: слова со смешанными письменностями;
      - suggested_clean: {text, changed, changes} — результат безопасной очистки.
    """
    # Импорт здесь, чтобы избежать циклической зависимости на уровне модуля.
    from .clean import clean_copy

    issues = find_issues(text)
    by_kind: dict[str, int] = {}
    for issue in issues:
        by_kind[issue["kind"]] = by_kind.get(issue["kind"], 0) + 1

    cleaned, changes = clean_copy(text)

    return {
        "length": len(text),
        "bytes": len(text.encode("utf-8")),
        "issues": issues,
        "issues_by_kind": by_kind,
        "normalization": normalization_report(text),
        "mixed_script": find_mixed_script_words(text),
        "suggested_clean": {
            "text": cleaned,
            "changed": cleaned != text,
            "changes": changes,
        },
    }
