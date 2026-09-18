"""Три РАЗДЕЛЬНЫЕ операции над текстом: clean_copy, normalize, escape.

Они намеренно не смешиваются:
  - clean_copy — безопасная бытовая очистка «чистой копии» (главное действие);
  - normalize  — только форма нормализации Unicode, ничего лишнего;
  - escape/unescape — сделать невидимое видимым и обратно, без потерь.
"""

from __future__ import annotations

import re
import unicodedata

from .inspect import KEEP, REMOVE, REPLACE, classify_char

VALID_FORMS = ("NFC", "NFD", "NFKC", "NFKD")


def clean_copy(text: str) -> tuple[str, list[dict]]:
    """Безопасная очистка «чистой копии». Возвращает ``(cleaned, changes)``.

    Что делает:
      - удаляет zero-width / BOM / soft-hyphen / bidi / control-мусор;
      - приводит NBSP и прочие необычные пробелы к обычному пробелу U+0020;
      - обрезает висящие пробелы по краям строк (trailing) и пустые края;
      - приводит результат к NFC.

    Что НЕ делает: не трогает обычные буквы и смысл — типографские кавычки и
    тире (action=keep) остаются на месте.

    ``changes`` — список изменений для preview «что изменится». Каждый элемент:
    ``{index, kind, codepoint, from, to, action}`` с ``action`` ∈
    {``removed``, ``replaced``}; плюс, если NFC изменил текст, агрегатная запись
    ``{kind: "nfc", action: "normalized"}``.
    """
    out: list[str] = []
    changes: list[dict] = []

    for index, char in enumerate(text):
        info = classify_char(char)
        if info is None or info.action == KEEP:
            out.append(char)
            continue
        if info.action == REMOVE:
            changes.append(
                {
                    "index": index,
                    "kind": info.kind,
                    "codepoint": f"U+{ord(char):04X}",
                    "from": char,
                    "to": None,
                    "action": "removed",
                }
            )
            continue
        if info.action == REPLACE:
            replacement = info.replacement or ""
            out.append(replacement)
            changes.append(
                {
                    "index": index,
                    "kind": info.kind,
                    "codepoint": f"U+{ord(char):04X}",
                    "from": char,
                    "to": replacement,
                    "action": "replaced",
                }
            )

    cleaned = "".join(out)

    # Обрезаем висящие пробелы/табуляции в конце каждой строки и пустые края.
    cleaned = _trim_line_edges(cleaned)

    # Финальная нормализация в NFC — не меняет видимые буквы, только форму.
    normalized = unicodedata.normalize("NFC", cleaned)
    if normalized != cleaned:
        changes.append({"kind": "nfc", "action": "normalized"})
    cleaned = normalized

    return cleaned, changes


def _trim_line_edges(text: str) -> str:
    """Срезать trailing-пробелы в каждой строке и пустые строки по краям.

    Ведущий отступ строк не трогаем — это может быть значимо (код, списки).
    """
    lines = [line.rstrip(" \t") for line in text.split("\n")]
    return "\n".join(lines).strip("\n")


def normalize(text: str, form: str) -> str:
    """Нормализовать текст в одну из форм ``NFC|NFD|NFKC|NFKD``.

    :raises ValueError: если форма неизвестна.
    """
    if form not in VALID_FORMS:
        raise ValueError(f"Неизвестная форма нормализации: {form!r}. Допустимо: {', '.join(VALID_FORMS)}")
    return unicodedata.normalize(form, text)


# --- escape / unescape --------------------------------------------------------

_UNESCAPE_RE = re.compile(r"\\(\\|u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8})")


def escape(text: str) -> str:
    """Экранировать невидимое/непечатное в ``\\uXXXX`` / ``\\UXXXXXXXX``.

    Обычные печатные ASCII (U+0020..U+007E) остаются читаемыми; обратный слэш
    удваивается, чтобы :func:`unescape` был однозначным и обратимым.
    """
    out: list[str] = []
    for char in text:
        code = ord(char)
        if char == "\\":
            out.append("\\\\")
        elif 0x20 <= code <= 0x7E:
            out.append(char)
        elif code <= 0xFFFF:
            out.append(f"\\u{code:04x}")
        else:
            out.append(f"\\U{code:08x}")
    return "".join(out)


def unescape(text: str) -> str:
    """Обратная операция к :func:`escape`."""

    def _replace(match: re.Match[str]) -> str:
        token = match.group(1)
        if token == "\\":
            return "\\"
        return chr(int(token[1:], 16))

    return _UNESCAPE_RE.sub(_replace, text)
