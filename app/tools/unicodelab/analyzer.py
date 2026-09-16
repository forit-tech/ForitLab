"""Разбор строки по символам: что там прячется и почему это опасно."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

#: Невидимые управляющие символы форматирования.
ZERO_WIDTH = {
    "​": "ZERO WIDTH SPACE",
    "‌": "ZERO WIDTH NON-JOINER",
    "‍": "ZERO WIDTH JOINER",
    "⁠": "WORD JOINER",
    "﻿": "BOM / ZERO WIDTH NO-BREAK SPACE",
    "᠎": "MONGOLIAN VOWEL SEPARATOR",
}

#: Пробелы, которые не являются пробелом U+0020.
EXOTIC_SPACES = {
    " ": "NO-BREAK SPACE",
    " ": "FIGURE SPACE",
    " ": "THIN SPACE",
    " ": "HAIR SPACE",
    " ": "NARROW NO-BREAK SPACE",
    "　": "IDEOGRAPHIC SPACE",
    " ": "OGHAM SPACE MARK",
}
EXOTIC_SPACES.update({chr(code): "EN/EM SPACE" for code in range(0x2000, 0x2007)})

#: Управление направлением текста — умеет переворачивать отображение строки.
BIDI_CONTROLS = {
    "‪": "LEFT-TO-RIGHT EMBEDDING",
    "‫": "RIGHT-TO-LEFT EMBEDDING",
    "‬": "POP DIRECTIONAL FORMATTING",
    "‭": "LEFT-TO-RIGHT OVERRIDE",
    "‮": "RIGHT-TO-LEFT OVERRIDE",
    "⁦": "LEFT-TO-RIGHT ISOLATE",
    "⁧": "RIGHT-TO-LEFT ISOLATE",
    "⁨": "FIRST STRONG ISOLATE",
    "⁩": "POP DIRECTIONAL ISOLATE",
}

#: Кириллица, неотличимая от латиницы в большинстве шрифтов.
CYRILLIC_TO_LATIN = {
    "а": "a", "б": "6", "в": "B", "е": "e", "ё": "e", "к": "k", "м": "M", "н": "H",
    "о": "o", "р": "p", "с": "c", "т": "T", "у": "y", "х": "x", "ѕ": "s", "і": "i",
    "ј": "j", "ԁ": "d", "һ": "h", "А": "A", "В": "B", "Е": "E", "Ё": "E", "К": "K",
    "М": "M", "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X",
    "Ѕ": "S", "І": "I", "Ј": "J",
}
LATIN_TO_CYRILLIC = {
    "a": "а", "e": "е", "o": "о", "p": "р", "c": "с", "x": "х", "y": "у",
    "A": "А", "B": "В", "E": "Е", "K": "К", "M": "М", "H": "Н", "O": "О",
    "P": "Р", "C": "С", "T": "Т", "X": "Х",
}

SOFT_HYPHEN = "­"
REPLACEMENT_CHAR = "�"

SEVERITY_ORDER = {"info": 0, "warn": 1, "alert": 2}


@dataclass
class CharIssue:
    index: int
    char: str
    codepoint: str
    name: str
    category: str
    kind: str
    severity: str
    note: str

    def as_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "codepoint": self.codepoint,
            "name": self.name,
            "category": self.category,
            "kind": self.kind,
            "severity": self.severity,
            "note": self.note,
            "visible": self.char if self.char.isprintable() else "",
        }


@dataclass
class Report:
    issues: list[CharIssue] = field(default_factory=list)
    findings: list[dict[str, object]] = field(default_factory=list)


def _char_name(char: str) -> str:
    try:
        return unicodedata.name(char)
    except ValueError:
        return f"UNNAMED (U+{ord(char):04X})"


def _script_of(char: str) -> str:
    """Грубое определение письменности по имени символа.

    Полноценные таблицы Script из UCD в stdlib не входят, но для задачи
    «латиница или кириллица» хватает имени символа.
    """
    if not char.isalpha():
        return "common"
    name = _char_name(char)
    if name.startswith("CYRILLIC"):
        return "cyrillic"
    if name.startswith("LATIN"):
        return "latin"
    if name.startswith("GREEK"):
        return "greek"
    return "other"


def inspect_characters(text: str) -> list[CharIssue]:
    issues: list[CharIssue] = []

    for index, char in enumerate(text):
        category = unicodedata.category(char)
        common = {
            "index": index,
            "char": char,
            "codepoint": f"U+{ord(char):04X}",
            "name": _char_name(char),
            "category": category,
        }

        if char in ZERO_WIDTH:
            issues.append(
                CharIssue(
                    **common,
                    kind="zero_width",
                    severity="alert",
                    note="Невидимый символ: строки выглядят одинаково, но не равны",
                )
            )
        elif char in BIDI_CONTROLS:
            issues.append(
                CharIssue(
                    **common,
                    kind="bidi_control",
                    severity="alert",
                    note="Управление направлением текста: отображение может не совпадать с содержимым",
                )
            )
        elif char in EXOTIC_SPACES:
            issues.append(
                CharIssue(
                    **common,
                    kind="exotic_space",
                    severity="warn",
                    note="Это не обычный пробел: strip() и сравнение строк ведут себя не так, как ожидается",
                )
            )
        elif char == SOFT_HYPHEN:
            issues.append(
                CharIssue(
                    **common,
                    kind="soft_hyphen",
                    severity="warn",
                    note="Мягкий перенос: невидим, но участвует в сравнении",
                )
            )
        elif char == REPLACEMENT_CHAR:
            issues.append(
                CharIssue(
                    **common,
                    kind="replacement_char",
                    severity="alert",
                    note="Следы неудачной перекодировки — исходный символ уже потерян",
                )
            )
        elif category == "Cc" and char not in "\n\r\t":
            issues.append(
                CharIssue(
                    **common,
                    kind="control",
                    severity="alert",
                    note="Управляющий символ в данных",
                )
            )
        elif category == "Cf":
            issues.append(
                CharIssue(
                    **common,
                    kind="format_control",
                    severity="warn",
                    note="Символ форматирования: невидим при выводе",
                )
            )
        elif category == "Co":
            issues.append(
                CharIssue(
                    **common,
                    kind="private_use",
                    severity="warn",
                    note="Область частного использования: отображается по-разному в разных системах",
                )
            )
        elif unicodedata.combining(char):
            issues.append(
                CharIssue(
                    **common,
                    kind="combining_mark",
                    severity="info",
                    note="Комбинирующий знак: один видимый символ состоит из нескольких кодовых точек",
                )
            )

    return issues


def find_mixed_script_words(text: str) -> list[dict[str, object]]:
    """Слова, в которых смешаны письменности, — почти всегда подделка или опечатка."""
    findings: list[dict[str, object]] = []
    word = ""
    start = 0

    def flush(word: str, start: int) -> None:
        if len(word) < 2:
            return
        scripts = {_script_of(ch) for ch in word if ch.isalpha()} - {"common"}
        if len(scripts) > 1:
            suspicious = [
                {
                    "index": start + offset,
                    "char": ch,
                    "codepoint": f"U+{ord(ch):04X}",
                    "script": _script_of(ch),
                    "looks_like": CYRILLIC_TO_LATIN.get(ch) or LATIN_TO_CYRILLIC.get(ch),
                }
                for offset, ch in enumerate(word)
                if ch in CYRILLIC_TO_LATIN or ch in LATIN_TO_CYRILLIC
            ]
            findings.append(
                {
                    "word": word,
                    "index": start,
                    "scripts": sorted(scripts),
                    "characters": suspicious,
                }
            )

    for index, char in enumerate(text):
        if char.isalnum():
            if not word:
                start = index
            word += char
        else:
            flush(word, start)
            word = ""
    flush(word, start)

    return findings


def normalization_report(text: str) -> dict[str, object]:
    forms = {form: unicodedata.normalize(form, text) for form in ("NFC", "NFD", "NFKC", "NFKD")}
    return {
        "is_nfc": text == forms["NFC"],
        "is_nfd": text == forms["NFD"],
        "forms": {
            form: {
                "length": len(value),
                "bytes": len(value.encode("utf-8")),
                "changes_text": value != text,
                "preview": value[:120],
            }
            for form, value in forms.items()
        },
        "nfc_vs_nfd_length": len(forms["NFC"]) - len(forms["NFD"]),
    }


def clean(text: str) -> str:
    """Безопасная версия строки.

    Ровно то, что стоит делать на входе в хранилище: нормализовать в NFC,
    выбросить невидимое, экзотические пробелы привести к обычному.
    """
    without_invisible = "".join(
        ch
        for ch in text
        if ch not in ZERO_WIDTH and ch not in BIDI_CONTROLS and ch != SOFT_HYPHEN
    )
    spaces_fixed = "".join(" " if ch in EXOTIC_SPACES else ch for ch in without_invisible)
    return unicodedata.normalize("NFC", spaces_fixed).strip()


def analyze(text: str) -> dict[str, object]:
    issues = inspect_characters(text)
    mixed = find_mixed_script_words(text)
    normalization = normalization_report(text)
    cleaned = clean(text)

    findings: list[dict[str, str]] = []
    by_kind: dict[str, int] = {}
    for issue in issues:
        by_kind[issue.kind] = by_kind.get(issue.kind, 0) + 1

    if by_kind.get("zero_width"):
        findings.append(
            {
                "severity": "alert",
                "message": f"Найдено невидимых символов: {by_kind['zero_width']}. "
                "Две визуально одинаковые строки не будут равны.",
            }
        )
    if by_kind.get("exotic_space"):
        findings.append(
            {
                "severity": "warn",
                "message": f"Необычных пробелов: {by_kind['exotic_space']}. "
                "strip() их не уберёт, GROUP BY даст лишние группы.",
            }
        )
    if by_kind.get("bidi_control"):
        findings.append(
            {
                "severity": "alert",
                "message": "Есть управление направлением текста: отображаемое не совпадает с хранимым.",
            }
        )
    if by_kind.get("replacement_char"):
        findings.append(
            {
                "severity": "alert",
                "message": "Символ U+FFFD означает, что перекодировка уже прошла с потерями.",
            }
        )
    if by_kind.get("soft_hyphen"):
        findings.append(
            {
                "severity": "warn",
                "message": f"Мягких переносов: {by_kind['soft_hyphen']}. "
                "Они невидимы, но ломают точное сравнение и поиск.",
            }
        )
    if by_kind.get("control") or by_kind.get("format_control"):
        findings.append(
            {
                "severity": "alert" if by_kind.get("control") else "warn",
                "message": "В строке есть управляющие или форматирующие символы.",
            }
        )
    if mixed:
        findings.append(
            {
                "severity": "alert",
                "message": f"Слов со смешанными письменностями: {len(mixed)}. "
                "Классическая причина, по которой JOIN молча теряет строки.",
            }
        )
    if not normalization["is_nfc"]:
        findings.append(
            {
                "severity": "warn",
                "message": "Текст не в NFC. Одно и то же имя в NFC и NFD — это разные строки для БД.",
            }
        )
    if cleaned != text and not findings:
        findings.append(
            {"severity": "info", "message": "Строка изменится при нормализации и очистке краёв."}
        )

    # Статус — это максимум серьёзности по всему: и по сводным находкам, и по
    # отдельным символам. Иначе одинокий мягкий перенос (issue есть, а finding
    # для него не формируется) молча оставит вердикт «ok».
    status = "ok"
    severities = [finding["severity"] for finding in findings]
    severities += [issue.severity for issue in issues]
    for severity in severities:
        if SEVERITY_ORDER[severity] > SEVERITY_ORDER.get(status, 0):
            status = severity

    return {
        "status": status,
        "length": {
            "characters": len(text),
            "bytes": len(text.encode("utf-8")),
            "visible_characters": len([ch for ch in text if not unicodedata.combining(ch)]),
        },
        "issues": [issue.as_dict() for issue in issues],
        "issues_by_kind": by_kind,
        "mixed_script_words": mixed,
        "normalization": normalization,
        "cleaned": {
            "text": cleaned,
            "changed": cleaned != text,
            "length": len(cleaned),
        },
        "findings": findings,
    }
