"""File Inspector — офлайн-инспектор метаданных файлов Forit Lab.

Продуктовый смысл: показать, что файл выдаёт о вас (GPS съёмки, модель
камеры, автор документа, софт, таймстемпы), и отдать очищенную КОПИЮ без
пересжатия пикселей. Всё на stdlib: EXIF/PNG-text/PDF/OOXML разбираются
вручную из байтов, тяжёлых зависимостей (Pillow/piexif) нет.

Domain-логика (inspect/metadata/sanitize) работает над `bytes`, а не над
загрузками — её легко юнит-тестировать. HTTP-слой в router.py тонкий.
"""

TOOL_ID = "file_inspector"
TOOL_TITLE = "File Inspector"
TOOL_SUMMARY = (
    "Загрузите файл (JPEG/PNG/WEBP/PDF/DOCX…) — Lab покажет скрытые метаданные "
    "(GPS, устройство, автор, софт, даты) и отдаст очищенную копию."
)

from .inspect import detect_format, inspect_file  # noqa: E402
from .models import FileReport, MetadataItem  # noqa: E402
from .sanitize import sanitize_copy  # noqa: E402

__all__ = [
    "TOOL_ID",
    "TOOL_TITLE",
    "TOOL_SUMMARY",
    "inspect_file",
    "detect_format",
    "sanitize_copy",
    "FileReport",
    "MetadataItem",
]
