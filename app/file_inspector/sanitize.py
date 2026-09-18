"""Создание очищенной КОПИИ файла. Оригинальные bytes никогда не мутируются.

Стратегия — вырезать метаданные, не пересжимая пиксели: для JPEG выкидываем
сегменты APP1(Exif)/APP13(IPTC), для PNG — текстовые/eXIf-чанки, для WEBP —
EXIF/XMP-чанки RIFF. Форматы, которые нельзя вычистить надёжно (PDF/OOXML),
честно возвращают (None, []) — лучше отказать, чем испортить документ.
"""

from __future__ import annotations

import struct

from .inspect import detect_format
from .metadata import extract_metadata


# --------------------------------------------------------------------------
# JPEG: удалить APP1(Exif), APP1(XMP), APP13(IPTC/Photoshop) байт-в-байт
# --------------------------------------------------------------------------
def strip_jpeg(data: bytes) -> bytes | None:
    if data[:2] != b"\xff\xd8":
        return None
    out = bytearray(b"\xff\xd8")
    i, n = 2, len(data)
    while i + 1 < n:
        if data[i] != 0xFF:
            out += data[i:]
            break
        marker = data[i + 1]
        if marker == 0xDA:  # SOS — дальше entropy-coded данные, копируем как есть
            out += data[i:]
            break
        if marker == 0xD9:  # EOI
            out += data[i : i + 2]
            i += 2
            continue
        if 0xD0 <= marker <= 0xD7 or marker == 0x01:  # standalone маркеры
            out += data[i : i + 2]
            i += 2
            continue
        if i + 4 > n:
            out += data[i:]
            break
        (length,) = struct.unpack(">H", data[i + 2 : i + 4])
        seg_end = i + 2 + length
        payload = data[i + 4 : seg_end]
        drop = (
            (marker == 0xE1 and payload[:6] == b"Exif\x00\x00")
            or (marker == 0xE1 and payload[:4] == b"http")  # XMP в APP1
            or marker == 0xED  # APP13: IPTC/Photoshop
        )
        if not drop:
            out += data[i:seg_end]
        i = seg_end
    return bytes(out)


# --------------------------------------------------------------------------
# PNG: пересобрать поток чанков без tEXt/iTXt/zTXt/eXIf (CRC уже в каждом чанке)
# --------------------------------------------------------------------------
_PNG_SIG = b"\x89PNG\r\n\x1a\n"
_PNG_DROP = {b"tEXt", b"iTXt", b"zTXt", b"eXIf"}


def strip_png(data: bytes) -> bytes | None:
    if data[:8] != _PNG_SIG:
        return None
    out = bytearray(_PNG_SIG)
    i, n = 8, len(data)
    while i + 8 <= n:
        (length,) = struct.unpack(">I", data[i : i + 4])
        ctype = data[i + 4 : i + 8]
        end = i + 8 + length + 4  # data + CRC
        if ctype not in _PNG_DROP:
            out += data[i:end]  # копируем чанк вместе с его исходным CRC
        i = end
        if ctype == b"IEND":
            break
    return bytes(out)


# --------------------------------------------------------------------------
# WEBP (RIFF): удалить EXIF/XMP чанки и пересчитать размер RIFF
# --------------------------------------------------------------------------
_WEBP_DROP = {b"EXIF", b"XMP "}


def strip_webp(data: bytes) -> bytes | None:
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    kept: list[bytes] = []
    i, n = 12, len(data)
    while i + 8 <= n:
        fourcc = data[i : i + 4]
        (size,) = struct.unpack("<I", data[i + 4 : i + 8])
        end = i + 8 + size + (size & 1)
        if fourcc not in _WEBP_DROP:
            kept.append(data[i:end])
        i = end
    payload = b"WEBP" + b"".join(kept)
    return b"RIFF" + struct.pack("<I", len(payload)) + payload


_STRIPPERS = {
    "jpeg": strip_jpeg,
    "png": strip_png,
    "webp": strip_webp,
}


def sanitize_copy(name: str, data: bytes) -> tuple[bytes | None, list[str]]:
    """Вернуть (cleaned_bytes | None, removed_fields).

    None — если формат чистить надёжно не умеем (PDF/OOXML/unknown).
    removed_fields — ключи метаданных, исчезнувшие после очистки.
    Входные bytes не изменяются.
    """
    fmt = detect_format(name, data)
    stripper = _STRIPPERS.get(fmt)
    if stripper is None:
        return None, []
    cleaned = stripper(data)
    if cleaned is None:
        return None, []
    before = {m.key for m in extract_metadata(fmt, data)}
    after = {m.key for m in extract_metadata(fmt, cleaned)}
    removed = sorted(before - after)
    return cleaned, removed
