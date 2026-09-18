"""Модели и классификация File Inspector.

Держим здесь dataclass'ы отчёта и единый справочник категорий метаданных,
чтобы domain-логика (metadata/inspect/sanitize) не дублировала правила
«что считать чувствительным».
"""

from __future__ import annotations

from dataclasses import dataclass, field

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
        return {
            "key": self.key,
            "value": self.value,
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
            "metadata": meta,
            "sensitive_metadata": [m for m in meta if m["sensitive"]],
            "can_sanitize": self.can_sanitize,
        }
