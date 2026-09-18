"""Модели и классификация File Inspector.

Держим здесь dataclass'ы отчёта и единый справочник категорий метаданных,
чтобы domain-логика (metadata/inspect/sanitize) не дублировала правила
«что считать чувствительным».
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Человекочитаемые подписи для частых ключей (иначе показываем сам ключ).
_LABELS = {
    "Make": "Производитель камеры",
    "Model": "Модель камеры",
    "Software": "Программа",
    "DateTime": "Дата изменения",
    "DateTimeOriginal": "Дата съёмки",
    "DateTimeDigitized": "Дата оцифровки",
    "Artist": "Автор",
    "Copyright": "Копирайт",
    "GPSLatitude": "Широта (GPS)",
    "GPSLongitude": "Долгота (GPS)",
    "GPSPosition": "Полушария GPS",
    "Author": "Автор",
    "Creator": "Создано в",
    "Producer": "Обработано в",
    "CreationDate": "Дата создания",
    "ModDate": "Дата изменения",
    "Title": "Заголовок",
    "Subject": "Тема",
    "Keywords": "Ключевые слова",
    "creator": "Автор",
    "lastModifiedBy": "Последний редактор",
    "created": "Дата создания",
    "modified": "Дата изменения",
    "lastPrinted": "Последняя печать",
    "revision": "Ревизия",
    "Company": "Компания",
    "Manager": "Руководитель",
    "Application": "Приложение",
    "AppVersion": "Версия приложения",
    "hasComments": "Есть комментарии",
    "hasRevisions": "Есть история правок",
    "XMP": "XMP-метаданные",
}

_PREVIEW_CHARS = 160


def _detect_kind(value: str) -> str:
    """Грубое определение типа значения, чтобы не вываливать простыню в UI."""
    v = value.strip()
    if not v:
        return "empty"
    head = v[:80].lower()
    if head.startswith("%3c"):
        return "encoded-xml"  # URL-encoded XML (напр. draw.io mxfile)
    if v[0] == "<":
        return "xml"
    if v[0] in "{[":
        return "json"
    if re.fullmatch(r"-?\d+(?:\.\d+)?", v):
        return "number"
    if v.count("%") > 4 and re.search(r"%[0-9A-Fa-f]{2}", v):
        return "encoded"
    return "text"


def _type_label(key: str, value: str, kind: str) -> str:
    """Короткая подпись для крупного значения вместо самого значения."""
    kb = max(1, round(len(value) / 1024))
    if "diagrams.net" in value[:400] or key.lower() == "mxfile":
        return f"Встроенная диаграмма draw.io · XML · ~{kb} KB"
    names = {
        "encoded-xml": "URL-encoded XML",
        "xml": "XML",
        "json": "JSON",
        "encoded": "URL-encoded данные",
        "text": "текст",
    }
    return f"{names.get(kind, 'данные')} · ~{kb} KB"

# --------------------------------------------------------------------------
# Категории метаданных. Всё, что в SENSITIVE_CATEGORIES, деанонимизирует
# автора/устройство/место/время создания файла → sensitive=True.
# GPS (location) — самый важный: точные координаты съёмки.
# --------------------------------------------------------------------------
CAT_LOCATION = "location"      # GPS-координаты
CAT_DEVICE = "device"          # производитель/модель камеры
CAT_SOFTWARE = "software"      # чем создан/обработан файл
CAT_AUTHOR = "author"          # автор/владелец/копирайт
CAT_TIMESTAMPS = "timestamps"  # даты съёмки/создания/изменения
CAT_DOCUMENT = "document"      # идентичность документа (title, revision, keywords)
CAT_OTHER = "other"            # прочее, не деанонимизирующее

SENSITIVE_CATEGORIES = frozenset(
    {CAT_LOCATION, CAT_DEVICE, CAT_SOFTWARE, CAT_AUTHOR, CAT_TIMESTAMPS, CAT_DOCUMENT}
)


@dataclass
class MetadataItem:
    """Одно извлечённое поле метаданных."""

    key: str
    value: str
    category: str
    sensitive: bool = False

    def as_dict(self) -> dict:
        value = self.value
        kind = _detect_kind(value)
        large = len(value) > _PREVIEW_CHARS or kind in ("xml", "json", "encoded", "encoded-xml")
        return {
            "key": self.key,
            "label": _LABELS.get(self.key, self.key),
            "value": value,
            "value_length": len(value),
            "value_kind": kind,
            "preview": value[:_PREVIEW_CHARS],
            "large": large,
            # подпись-заменитель для крупных значений (draw.io XML и т.п.)
            "type_label": _type_label(self.key, value, kind) if large else "",
            "category": self.category,
            "sensitive": self.sensitive,
        }


def make_item(key: str, value: object, category: str) -> MetadataItem:
    """Собрать MetadataItem, выведя sensitive из категории."""
    return MetadataItem(
        key=key,
        value="" if value is None else str(value),
        category=category,
        sensitive=category in SENSITIVE_CATEGORIES,
    )


@dataclass
class FileReport:
    """Отчёт inspect_file. as_dict() — ровно то, что уходит в UI."""

    name: str
    size_bytes: int
    sha256: str
    mime: str
    format: str
    metadata: list[MetadataItem] = field(default_factory=list)
    width: int | None = None
    height: int | None = None
    can_sanitize: bool = False

    def as_dict(self) -> dict:
        meta = [m.as_dict() for m in self.metadata]
        return {
            "name": self.name,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "mime": self.mime,
            # type — синоним mime, удобный для фронта
            "type": self.mime,
            "format": self.format,
            "width": self.width,
            "height": self.height,
            "metadata": meta,
            "sensitive_metadata": [m for m in meta if m["sensitive"]],
            "can_sanitize": self.can_sanitize,
        }
