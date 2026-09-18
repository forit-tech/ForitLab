"""Общая инспекция файла: формат по magic bytes, sha256, размер, метаданные.

Domain-функция работает над `bytes` (не над путями/загрузками) — так её просто
юнит-тестировать и переиспользовать в sanitize (before/after).
"""

from __future__ import annotations

import hashlib
import io
import mimetypes
import struct
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


def image_dimensions(fmt: str, data: bytes) -> tuple[int, int] | None:
    """(width, height) для растровых форматов; None, если не изображение/не читается."""
    try:
        if fmt == "png" and data[12:16] == b"IHDR":
            w, h = struct.unpack(">II", data[16:24])
            return int(w), int(h)
        if fmt == "webp":
            # VP8X (расширенный) хранит размеры-1 в 3 байтах LE
            idx = data.find(b"VP8X")
            if idx != -1 and idx + 14 <= len(data):
                b = data[idx + 8 : idx + 14]
                w = (b[3] | (b[4] << 8) | (b[5] << 16)) + 1
                h = 0  # для простого VP8/VP8L ниже
            idx = data.find(b"VP8 ")
            if idx != -1 and idx + 14 <= len(data):
                w, h = struct.unpack("<HH", data[idx + 14 : idx + 18][:4])
                return int(w & 0x3FFF), int(h & 0x3FFF)
            idx = data.find(b"VP8L")
            if idx != -1 and idx + 9 <= len(data):
                b = data[idx + 9 : idx + 14]
                bits = b[0] | (b[1] << 8) | (b[2] << 16) | (b[3] << 24)
                return int((bits & 0x3FFF) + 1), int(((bits >> 14) & 0x3FFF) + 1)
            return None
        if fmt == "jpeg":
            i, n = 2, len(data)
            while i + 9 < n:
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker = data[i + 1]
                if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                    h, w = struct.unpack(">HH", data[i + 5 : i + 9])
                    return int(w), int(h)
                if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
                    i += 2
                    continue
                (length,) = struct.unpack(">H", data[i + 2 : i + 4])
                i = i + 2 + length
    except (struct.error, IndexError):
        return None
    return None


def inspect_file(name: str, data: bytes) -> FileReport:
    """Собрать FileReport по имени и байтам файла. Не бросает на битом вводе."""
    fmt = detect_format(name, data)
    metadata = extract_metadata(fmt, data)
    dims = image_dimensions(fmt, data)
    return FileReport(
        name=name or "file",
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        mime=guess_mime(name, fmt),
        format=fmt,
        metadata=metadata,
        width=dims[0] if dims else None,
        height=dims[1] if dims else None,
        can_sanitize=fmt in SANITIZABLE_FORMATS,
    )
