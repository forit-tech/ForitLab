"""Общая инспекция файла: формат по magic bytes, sha256, размер, метаданные.

Domain-функция работает над `bytes` (не над путями/загрузками) — так её просто
юнит-тестировать и переиспользовать в sanitize (before/after).
"""

from __future__ import annotations

import hashlib
import io
import mimetypes
import zipfile

from .metadata import extract_metadata
from .models import FileReport

# format → mime по magic bytes (расширение — только запасной вариант).
_FORMAT_MIME = {
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

# Форматы, для которых умеем делать безопасную очищенную копию.
SANITIZABLE_FORMATS = frozenset({"jpeg", "png", "webp"})


def _classify_zip(data: bytes) -> str:
    """PK-контейнер → docx/xlsx/pptx по внутренней структуре, иначе 'unknown'."""
    try:
        names = set(zipfile.ZipFile(io.BytesIO(data)).namelist())
    except (zipfile.BadZipFile, OSError):
        return "unknown"
    if any(n.startswith("word/") for n in names):
        return "docx"
    if any(n.startswith("xl/") for n in names):
        return "xlsx"
    if any(n.startswith("ppt/") for n in names):
        return "pptx"
    return "unknown"


def detect_format(name: str, data: bytes) -> str:
    """Определить формат по magic bytes; для zip — заглянуть внутрь."""
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:5] == b"%PDF-":
        return "pdf"
    if data[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"):
        return _classify_zip(data)
    return "unknown"


def guess_mime(name: str, fmt: str) -> str:
    """MIME по формату (magic), иначе mimetypes по расширению имени файла."""
    if fmt in _FORMAT_MIME:
        return _FORMAT_MIME[fmt]
    guessed, _ = mimetypes.guess_type(name)
    return guessed or "application/octet-stream"


def inspect_file(name: str, data: bytes) -> FileReport:
    """Собрать FileReport по имени и байтам файла. Не бросает на битом вводе."""
    fmt = detect_format(name, data)
    metadata = extract_metadata(fmt, data)
    return FileReport(
        name=name or "file",
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        mime=guess_mime(name, fmt),
        format=fmt,
        metadata=metadata,
        can_sanitize=fmt in SANITIZABLE_FORMATS,
    )
