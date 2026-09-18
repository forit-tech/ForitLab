"""Извлечение метаданных из байтов файла — только stdlib.

EXIF/TIFF, PNG-текст, PDF Info, OOXML docProps разбираем вручную:
никаких Pillow/piexif. Каждая функция работает над `bytes` и возвращает
list[MetadataItem], чтобы её было легко юнит-тестировать без файловой системы
и без сети.
"""

from __future__ import annotations

import io
import re
import struct
import zipfile
import zlib

from .models import (
    CAT_AUTHOR,
    CAT_DEVICE,
    CAT_DOCUMENT,
    CAT_LOCATION,
    CAT_OTHER,
    CAT_SOFTWARE,
    CAT_TIMESTAMPS,
    MetadataItem,
    make_item,
)

# ==========================================================================
# TIFF / EXIF (общий движок для JPEG APP1, PNG eXIf, WEBP EXIF)
# ==========================================================================
_TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8}

# IFD0 (главный каталог) — теги идентичности снимка.
_IFD0_TAGS = {
    0x010F: ("Make", CAT_DEVICE),
    0x0110: ("Model", CAT_DEVICE),
    0x0131: ("Software", CAT_SOFTWARE),
    0x0132: ("DateTime", CAT_TIMESTAMPS),
    0x013B: ("Artist", CAT_AUTHOR),
    0x8298: ("Copyright", CAT_AUTHOR),
}
# Exif sub-IFD — время съёмки.
_EXIF_TAGS = {
    0x9003: ("DateTimeOriginal", CAT_TIMESTAMPS),
    0x9004: ("DateTimeDigitized", CAT_TIMESTAMPS),
}
_EXIF_IFD_PTR = 0x8769
_GPS_IFD_PTR = 0x8825


def _tiff_endian(tiff: bytes) -> str | None:
    if tiff[:2] == b"II":
        return "<"
    if tiff[:2] == b"MM":
        return ">"
    return None


def _read_ifd(tiff: bytes, offset: int, endian: str) -> dict[int, tuple[int, int, bytes]]:
    """Прочитать один IFD → {tag: (type, count, resolved_bytes)}.

    Значение хранится inline (если <=4 байт) либо по смещению внутри TIFF.
    """
    entries: dict[int, tuple[int, int, bytes]] = {}
    if offset < 0 or offset + 2 > len(tiff):
        return entries
    try:
        (count,) = struct.unpack(endian + "H", tiff[offset : offset + 2])
    except struct.error:
        return entries
    pos = offset + 2
    for _ in range(count):
        if pos + 12 > len(tiff):
            break
        tag, typ, cnt = struct.unpack(endian + "HHI", tiff[pos : pos + 8])
        raw = tiff[pos + 8 : pos + 12]
        size = _TYPE_SIZE.get(typ, 1) * cnt
        if size > 4:
            (voff,) = struct.unpack(endian + "I", raw)
            data = tiff[voff : voff + size]
        else:
            data = raw[:size]
        entries[tag] = (typ, cnt, data)
        pos += 12
    return entries


def _val_ascii(data: bytes) -> str:
    return data.split(b"\x00", 1)[0].decode("ascii", "replace").strip()


def _val_rationals(data: bytes, endian: str, count: int) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for i in range(count):
        chunk = data[i * 8 : i * 8 + 8]
        if len(chunk) < 8:
            break
        num, den = struct.unpack(endian + "II", chunk)
        out.append((num, den))
    return out


def _long(entry: tuple[int, int, bytes], endian: str) -> int:
    _, _, data = entry
    if len(data) < 4:
        return -1
    return struct.unpack(endian + "I", data[:4])[0]


def _gps_to_decimal(rationals: list[tuple[int, int]], ref: str) -> float:
    def r(t: tuple[int, int]) -> float:
        num, den = t
        return num / den if den else 0.0

    deg = r(rationals[0]) + r(rationals[1]) / 60 + r(rationals[2]) / 3600
    if ref.upper() in ("S", "W"):
        deg = -deg
    return deg


def _gps_items(gps: dict[int, tuple[int, int, bytes]], endian: str) -> list[MetadataItem]:
    items: list[MetadataItem] = []

    def rats(tag: int) -> list[tuple[int, int]] | None:
        if tag in gps:
            _, cnt, data = gps[tag]
            return _val_rationals(data, endian, cnt)
        return None

    lat = rats(0x0002)
    lon = rats(0x0004)
    lat_ref = _val_ascii(gps[0x0001][2]) if 0x0001 in gps else "N"
    lon_ref = _val_ascii(gps[0x0003][2]) if 0x0003 in gps else "E"
    if lat and len(lat) >= 3:
        items.append(make_item("GPSLatitude", f"{_gps_to_decimal(lat, lat_ref):.6f}", CAT_LOCATION))
    if lon and len(lon) >= 3:
        items.append(make_item("GPSLongitude", f"{_gps_to_decimal(lon, lon_ref):.6f}", CAT_LOCATION))
    if items:
        items.append(make_item("GPSPosition", f"{lat_ref}/{lon_ref}", CAT_LOCATION))
    return items


def parse_tiff(tiff: bytes) -> list[MetadataItem]:
    """Разобрать блок TIFF (то, что идёт после 'Exif\\0\\0' в APP1, либо eXIf)."""
    endian = _tiff_endian(tiff)
    if endian is None or len(tiff) < 8:
        return []
    items: list[MetadataItem] = []
    try:
        (ifd0_off,) = struct.unpack(endian + "I", tiff[4:8])
    except struct.error:
        return []
    ifd0 = _read_ifd(tiff, ifd0_off, endian)
    for tag, (key, cat) in _IFD0_TAGS.items():
        if tag in ifd0:
            value = _val_ascii(ifd0[tag][2])
            if value:
                items.append(make_item(key, value, cat))
    if _EXIF_IFD_PTR in ifd0:
        exif = _read_ifd(tiff, _long(ifd0[_EXIF_IFD_PTR], endian), endian)
        for tag, (key, cat) in _EXIF_TAGS.items():
            if tag in exif:
                value = _val_ascii(exif[tag][2])
                if value:
                    items.append(make_item(key, value, cat))
    if _GPS_IFD_PTR in ifd0:
        gps = _read_ifd(tiff, _long(ifd0[_GPS_IFD_PTR], endian), endian)
        items.extend(_gps_items(gps, endian))
    return items


# ==========================================================================
# JPEG
# ==========================================================================
def find_app1_exif(data: bytes) -> bytes | None:
    """Вернуть TIFF-блок из сегмента APP1(Exif) или None."""
    if data[:2] != b"\xff\xd8":
        return None
    i, n = 2, len(data)
    while i + 4 <= n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD9, 0xDA):  # EOI / SOS — метаданных дальше нет
            break
        if 0xD0 <= marker <= 0xD7 or marker == 0x01:
            i += 2
            continue
        (length,) = struct.unpack(">H", data[i + 2 : i + 4])
        payload = data[i + 4 : i + 2 + length]
        if marker == 0xE1 and payload[:6] == b"Exif\x00\x00":
            return payload[6:]
        i = i + 2 + length
    return None


def parse_jpeg(data: bytes) -> list[MetadataItem]:
    tiff = find_app1_exif(data)
    if tiff is None:
        return []
    return parse_tiff(tiff)


# ==========================================================================
# PNG
# ==========================================================================
_PNG_SIG = b"\x89PNG\r\n\x1a\n"

# Ключевые слова текстовых чанков → категория.
_PNG_KEYWORD_CAT = {
    "author": CAT_AUTHOR,
    "artist": CAT_AUTHOR,
    "copyright": CAT_AUTHOR,
    "software": CAT_SOFTWARE,
    "source": CAT_SOFTWARE,
    "creation time": CAT_TIMESTAMPS,
    "date": CAT_TIMESTAMPS,
    "title": CAT_DOCUMENT,
    "description": CAT_DOCUMENT,
}


def iter_png_chunks(data: bytes):
    """Yield (ctype, chunk_data, raw_chunk_bytes) для каждого чанка PNG."""
    if data[:8] != _PNG_SIG:
        return
    i, n = 8, len(data)
    while i + 8 <= n:
        (length,) = struct.unpack(">I", data[i : i + 4])
        ctype = data[i + 4 : i + 8]
        cdata = data[i + 8 : i + 8 + length]
        end = i + 8 + length + 4  # + CRC
        yield ctype, cdata, data[i:end]
        i = end
        if ctype == b"IEND":
            break


def _png_category(keyword: str) -> str:
    return _PNG_KEYWORD_CAT.get(keyword.strip().lower(), CAT_OTHER)


def parse_png(data: bytes) -> list[MetadataItem]:
    items: list[MetadataItem] = []
    for ctype, cdata, _ in iter_png_chunks(data):
        if ctype == b"tEXt":
            kw, _, txt = cdata.partition(b"\x00")
            key = kw.decode("latin-1", "replace")
            items.append(make_item(key, txt.decode("latin-1", "replace"), _png_category(key)))
        elif ctype == b"zTXt":
            kw, _, rest = cdata.partition(b"\x00")
            key = kw.decode("latin-1", "replace")
            try:
                txt = zlib.decompress(rest[1:]).decode("latin-1", "replace")
            except (zlib.error, IndexError):
                txt = ""
            items.append(make_item(key, txt, _png_category(key)))
        elif ctype == b"iTXt":
            kw, _, rest = cdata.partition(b"\x00")
            key = kw.decode("utf-8", "replace")
            if len(rest) >= 2:
                comp_flag = rest[0]
                rest = rest[2:]  # пропускаем compression flag + method
                _, _, rest = rest.partition(b"\x00")  # language tag
                _, _, text = rest.partition(b"\x00")  # translated keyword
                if comp_flag == 1:
                    try:
                        text = zlib.decompress(text)
                    except zlib.error:
                        text = b""
                items.append(make_item(key, text.decode("utf-8", "replace"), _png_category(key)))
        elif ctype == b"eXIf":
            items.extend(parse_tiff(cdata))
    return items


# ==========================================================================
# WEBP (RIFF): EXIF-чанк как TIFF + отметка XMP
# ==========================================================================
def iter_webp_chunks(data: bytes):
    """Yield (fourcc, chunk_data, raw_chunk_bytes) для RIFF/WEBP."""
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return
    i, n = 12, len(data)
    while i + 8 <= n:
        fourcc = data[i : i + 4]
        (size,) = struct.unpack("<I", data[i + 4 : i + 8])
        cdata = data[i + 8 : i + 8 + size]
        end = i + 8 + size + (size & 1)  # чанки выравниваются до чётной длины
        yield fourcc, cdata, data[i:end]
        i = end


def parse_webp(data: bytes) -> list[MetadataItem]:
    items: list[MetadataItem] = []
    for fourcc, cdata, _ in iter_webp_chunks(data):
        if fourcc == b"EXIF":
            tiff = cdata
            if tiff[:6] == b"Exif\x00\x00":
                tiff = tiff[6:]
            items.extend(parse_tiff(tiff))
        elif fourcc == b"XMP ":
            items.append(make_item("XMP", "present", CAT_DOCUMENT))
    return items


# ==========================================================================
# PDF — Info dictionary (MVP: regex по строковым значениям)
# ==========================================================================
_PDF_FIELDS = [
    ("Author", CAT_AUTHOR),
    ("Creator", CAT_SOFTWARE),
    ("Producer", CAT_SOFTWARE),
    ("CreationDate", CAT_TIMESTAMPS),
    ("ModDate", CAT_TIMESTAMPS),
    ("Title", CAT_DOCUMENT),
    ("Subject", CAT_DOCUMENT),
    ("Keywords", CAT_DOCUMENT),
]


def parse_pdf(data: bytes) -> list[MetadataItem]:
    items: list[MetadataItem] = []
    seen: set[str] = set()
    for key, cat in _PDF_FIELDS:
        # /Author (значение) — литеральная строка PDF; экранированные ) пропускаем
        m = re.search(rb"/" + re.escape(key.encode()) + rb"\s*\(((?:\\.|[^\\)])*)\)", data)
        if not m:
            continue
        raw = m.group(1).replace(b"\\(", b"(").replace(b"\\)", b")")
        value = raw.decode("latin-1", "replace").strip()
        if value and key not in seen:
            seen.add(key)
            items.append(make_item(key, value, cat))
    return items


# ==========================================================================
# OOXML (docx/xlsx/pptx) — docProps/core.xml + app.xml
# ==========================================================================
_CORE_FIELDS = [
    ("creator", CAT_AUTHOR),
    ("lastModifiedBy", CAT_AUTHOR),
    ("created", CAT_TIMESTAMPS),
    ("modified", CAT_TIMESTAMPS),
    ("lastPrinted", CAT_TIMESTAMPS),
    ("revision", CAT_DOCUMENT),
    ("title", CAT_DOCUMENT),
    ("subject", CAT_DOCUMENT),
    ("keywords", CAT_DOCUMENT),
    ("category", CAT_DOCUMENT),
]
_APP_FIELDS = [
    ("Company", CAT_AUTHOR),
    ("Manager", CAT_AUTHOR),
    ("Application", CAT_SOFTWARE),
    ("AppVersion", CAT_SOFTWARE),
]


def _xml_text(xml: bytes, tag: str) -> str:
    """Достать текст элемента <ns:tag>...</ns:tag> без полноценного XML-парсера."""
    m = re.search(
        rb"<(?:\w+:)?" + re.escape(tag.encode()) + rb"\b[^>]*>(.*?)</(?:\w+:)?"
        + re.escape(tag.encode()) + rb">",
        xml,
        re.DOTALL,
    )
    if not m:
        return ""
    return m.group(1).decode("utf-8", "replace").strip()


def parse_ooxml(data: bytes) -> list[MetadataItem]:
    items: list[MetadataItem] = []
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError):
        return []
    names = set(zf.namelist())
    if "docProps/core.xml" in names:
        core = zf.read("docProps/core.xml")
        for tag, cat in _CORE_FIELDS:
            value = _xml_text(core, tag)
            if value:
                items.append(make_item(tag, value, cat))
    if "docProps/app.xml" in names:
        app = zf.read("docProps/app.xml")
        for tag, cat in _APP_FIELDS:
            value = _xml_text(app, tag)
            if value:
                items.append(make_item(tag, value, cat))
    # Наличие ревизий/комментариев — полезный сигнал деанонимизации.
    if any(n.endswith("comments.xml") or "/comments" in n for n in names):
        items.append(make_item("hasComments", "true", CAT_DOCUMENT))
    if any("revision" in n.lower() for n in names):
        items.append(make_item("hasRevisions", "true", CAT_DOCUMENT))
    return items


# ==========================================================================
# Диспетчер по формату
# ==========================================================================
def extract_metadata(fmt: str, data: bytes) -> list[MetadataItem]:
    """Извлечь метаданные согласно определённому формату. Не роняется на битом вводе."""
    try:
        if fmt == "jpeg":
            return parse_jpeg(data)
        if fmt == "png":
            return parse_png(data)
        if fmt == "webp":
            return parse_webp(data)
        if fmt == "pdf":
            return parse_pdf(data)
        if fmt in ("docx", "xlsx", "pptx"):
            return parse_ooxml(data)
    except Exception:
        # Метаданные — best effort: битый файл не должен ронять инспекцию.
        return []
    return []
