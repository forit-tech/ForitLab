"""File Inspector — офлайн-тесты domain-логики и тонкого HTTP-слоя.

EXIF/PNG собираем в самом тесте из байтов (никаких Pillow/piexif), чтобы
проверять ручной разбор TIFF/GPS, sensitive-классификацию и то, что JPEG/PNG
sanitize реально убирает метаданные, не трогая пиксели.
"""

from __future__ import annotations

import hashlib
import struct
import zlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.errors import register_error_handlers
from app.file_inspector import detect_format, inspect_file, sanitize_copy
from app.file_inspector.metadata import extract_metadata, parse_tiff
from app.file_inspector.router import router

_LE = "<"


# ==========================================================================
# Конструкторы валидных мини-файлов
# ==========================================================================
def build_exif_tiff() -> bytes:
    """TIFF (LE) с Make/Software/DateTime/Artist + Exif + GPS (37.8 / -122.416667)."""
    ifd0_off = 8
    ifd0_size = 2 + 6 * 12 + 4
    exif_off = ifd0_off + ifd0_size
    exif_size = 2 + 1 * 12 + 4
    gps_off = exif_off + exif_size
    gps_size = 2 + 4 * 12 + 4
    data_off = gps_off + gps_size

    ext = bytearray()

    def put(b: bytes) -> int:
        off = data_off + len(ext)
        ext.extend(b)
        return off

    make_o = put(b"TestCam\x00")
    soft_o = put(b"ForIT\x00")
    dt = b"2021:01:02 03:04:05\x00"  # 20 байт
    dt_o = put(dt)
    artist_o = put(b"Alice\x00")
    dto_o = put(dt)
    lat_o = put(struct.pack(_LE + "IIIIII", 37, 1, 48, 1, 0, 1))  # 37.8
    lon_o = put(struct.pack(_LE + "IIIIII", 122, 1, 25, 1, 0, 1))  # -122.416667 при W

    def entry(tag: int, typ: int, count: int, value4: bytes) -> bytes:
        return struct.pack(_LE + "HHI", tag, typ, count) + value4

    def off4(o: int) -> bytes:
        return struct.pack(_LE + "I", o)

    def inline(b: bytes) -> bytes:
        return b + b"\x00" * (4 - len(b))

    ifd0 = struct.pack(_LE + "H", 6)
    ifd0 += entry(0x010F, 2, 8, off4(make_o))
    ifd0 += entry(0x0131, 2, 6, off4(soft_o))
    ifd0 += entry(0x0132, 2, 20, off4(dt_o))
    ifd0 += entry(0x013B, 2, 6, off4(artist_o))
    ifd0 += entry(0x8769, 4, 1, off4(exif_off))
    ifd0 += entry(0x8825, 4, 1, off4(gps_off))
    ifd0 += struct.pack(_LE + "I", 0)

    exif = struct.pack(_LE + "H", 1)
    exif += entry(0x9003, 2, 20, off4(dto_o))
    exif += struct.pack(_LE + "I", 0)

    gps = struct.pack(_LE + "H", 4)
    gps += entry(0x0001, 2, 2, inline(b"N\x00"))
    gps += entry(0x0002, 5, 3, off4(lat_o))
    gps += entry(0x0003, 2, 2, inline(b"W\x00"))
    gps += entry(0x0004, 5, 3, off4(lon_o))
    gps += struct.pack(_LE + "I", 0)

    header = b"II" + struct.pack(_LE + "H", 42) + struct.pack(_LE + "I", ifd0_off)
    return header + ifd0 + exif + gps + bytes(ext)


def build_exif_jpeg() -> bytes:
    """Минимальный JPEG: SOI + APP1(Exif) + SOF0 + SOS + entropy + EOI."""
    tiff = build_exif_tiff()
    app1_payload = b"Exif\x00\x00" + tiff
    app1 = b"\xff\xe1" + struct.pack(">H", len(app1_payload) + 2) + app1_payload
    # SOF0 (baseline) — чтобы был реальный маркер кадра
    sof0 = b"\xff\xc0" + struct.pack(">H", 2 + 15) + (
        b"\x08\x00\x01\x00\x01\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    )
    # SOS: заголовок сканирования + немного entropy-данных + EOI
    sos = b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x01\x00\x00\x3f\x00"
    entropy = b"\xd2\xab\x7f\x00"
    return b"\xff\xd8" + app1 + sof0 + sos + entropy + b"\xff\xd9"


def _png_chunk(ctype: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + ctype
        + data
        + struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF)
    )


def build_text_png() -> bytes:
    """1x1 grayscale PNG с tEXt Author (sensitive) и Comment (не sensitive)."""
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0))
    author = _png_chunk(b"tEXt", b"Author\x00Alice")
    comment = _png_chunk(b"tEXt", b"Comment\x00hello world")
    idat = _png_chunk(b"IDAT", zlib.compress(b"\x00\x00"))
    iend = _png_chunk(b"IEND", b"")
    return sig + ihdr + author + comment + idat + iend


def build_fake_pdf() -> bytes:
    return (
        b"%PDF-1.4\n1 0 obj\n<< /Author (Bob) /Producer (ForIT PDF) "
        b"/CreationDate (D:20210102030405) >>\nendobj\n%%EOF"
    )


# ==========================================================================
# Фикстуры
# ==========================================================================
@pytest.fixture(scope="module")
def client() -> TestClient:
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(router)
    return TestClient(app)


# ==========================================================================
# Базовая инспекция: sha256 / size / mime / format
# ==========================================================================
def test_inspect_basic_identity() -> None:
    data = build_exif_jpeg()
    report = inspect_file("photo.jpg", data).as_dict()
    assert report["size_bytes"] == len(data)
    assert report["sha256"] == hashlib.sha256(data).hexdigest()
    assert report["mime"] == "image/jpeg"
    assert report["type"] == report["mime"]
    assert report["format"] == "jpeg"
    assert report["can_sanitize"] is True


def test_detect_format_by_magic() -> None:
    assert detect_format("x.jpg", build_exif_jpeg()) == "jpeg"
    assert detect_format("x.png", build_text_png()) == "png"
    assert detect_format("x.pdf", build_fake_pdf()) == "pdf"
    assert detect_format("x.bin", b"not a known file at all") == "unknown"


# ==========================================================================
# EXIF/GPS: извлечение и перевод в десятичные координаты
# ==========================================================================
def test_tiff_gps_to_decimal() -> None:
    items = {m.key: m.value for m in parse_tiff(build_exif_tiff())}
    assert items["Make"] == "TestCam"
    assert items["Software"] == "ForIT"
    assert items["Artist"] == "Alice"
    assert items["DateTimeOriginal"] == "2021:01:02 03:04:05"
    assert float(items["GPSLatitude"]) == pytest.approx(37.8, abs=1e-4)
    assert float(items["GPSLongitude"]) == pytest.approx(-122.416667, abs=1e-4)


def test_gps_ref_signs_lat_lon_not_confused() -> None:
    """Широта/долгота не должны меняться местами, знаки — по ref (N/S, E/W).

    Карта строится по GPSLatitude→mlat, GPSLongitude→mlon; если их перепутать,
    точка уедет в другое полушарие. San Francisco ≈ (37.8, -122.4): широта
    положительная (N), долгота отрицательная (W).
    """
    from app.file_inspector.metadata import _gps_to_decimal

    # одинаковые рациональные значения, разные ref → знак задаёт именно ref
    dms = [(37, 1), (48, 1), (0, 1)]  # 37°48' = 37.8
    assert _gps_to_decimal(dms, "N") == pytest.approx(37.8, abs=1e-4)
    assert _gps_to_decimal(dms, "S") == pytest.approx(-37.8, abs=1e-4)
    assert _gps_to_decimal(dms, "E") == pytest.approx(37.8, abs=1e-4)
    assert _gps_to_decimal(dms, "W") == pytest.approx(-37.8, abs=1e-4)

    # и в собранном отчёте широта — это широта (37.8), долгота — это долгота (-122.4)
    items = {m.key: m.value for m in parse_tiff(build_exif_tiff())}
    lat = float(items["GPSLatitude"])
    lon = float(items["GPSLongitude"])
    assert lat > 0 and lat == pytest.approx(37.8, abs=1e-4)   # N → +
    assert lon < 0 and lon == pytest.approx(-122.4167, abs=1e-3)  # W → −
    assert lat != lon  # не одно и то же значение в обоих полях


def test_jpeg_metadata_and_sensitive() -> None:
    report = inspect_file("photo.jpg", build_exif_jpeg()).as_dict()
    by_key = {m["key"]: m for m in report["metadata"]}
    # GPS — самое важное чувствительное поле
    assert by_key["GPSLatitude"]["category"] == "location"
    assert by_key["GPSLatitude"]["sensitive"] is True
    assert by_key["Make"]["category"] == "device"
    assert by_key["Make"]["sensitive"] is True
    assert by_key["Software"]["sensitive"] is True
    # sensitive_metadata — подмножество sensitive
    keys = {m["key"] for m in report["sensitive_metadata"]}
    assert {"GPSLatitude", "GPSLongitude", "Make", "Software", "Artist"} <= keys
    assert all(m["sensitive"] for m in report["sensitive_metadata"])


# ==========================================================================
# PNG: текстовые чанки + разделение sensitive / не-sensitive
# ==========================================================================
def test_png_text_classification() -> None:
    report = inspect_file("i.png", build_text_png()).as_dict()
    by_key = {m["key"]: m for m in report["metadata"]}
    assert by_key["Author"]["category"] == "author"
    assert by_key["Author"]["sensitive"] is True
    # Comment не деанонимизирует → не sensitive
    assert by_key["Comment"]["category"] == "other"
    assert by_key["Comment"]["sensitive"] is False


# ==========================================================================
# Display-модель: крупные значения не вываливаются простынёй, есть подписи/размеры
# ==========================================================================
def build_drawio_png() -> bytes:
    """PNG с tEXt mxfile — большой URL-encoded XML (как экспорт draw.io)."""
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1280, 1090, 8, 2, 0, 0, 0))
    blob = b"mxfile\x00" + b"%3Cmxfile%20host%3D%22app.diagrams.net%22%3E" * 400
    mxfile = _png_chunk(b"tEXt", blob)
    idat = _png_chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
    iend = _png_chunk(b"IEND", b"")
    return sig + ihdr + mxfile + idat + iend


def test_large_value_is_collapsed_not_dumped() -> None:
    report = inspect_file("diagram.drawio.png", build_drawio_png()).as_dict()
    mx = next(m for m in report["metadata"] if m["key"] == "mxfile")
    assert mx["large"] is True
    assert mx["value_kind"] == "encoded-xml"
    assert "draw.io" in mx["type_label"]
    assert "KB" in mx["type_label"]
    assert len(mx["preview"]) <= 200  # превью короткое
    assert mx["value_length"] > 1000  # но полное значение сохранено для копирования


def test_short_value_is_not_marked_large() -> None:
    report = inspect_file("i.png", build_text_png()).as_dict()
    author = next(m for m in report["metadata"] if m["key"] == "Author")
    assert author["large"] is False
    assert author["type_label"] == ""
    assert author["label"] == "Автор"  # человекочитаемая подпись


def test_png_dimensions_reported() -> None:
    report = inspect_file("diagram.drawio.png", build_drawio_png()).as_dict()
    assert report["width"] == 1280
    assert report["height"] == 1090


def test_jpeg_dimensions_reported() -> None:
    report = inspect_file("photo.jpg", build_exif_jpeg()).as_dict()
    assert report["width"] and report["height"]


# ==========================================================================
# Sanitize JPEG: APP1 исчезает, маркеры кадра и entropy-данные на месте
# ==========================================================================
def test_sanitize_jpeg_strips_exif_keeps_pixels() -> None:
    data = build_exif_jpeg()
    cleaned, removed = sanitize_copy("photo.jpg", data)
    assert cleaned is not None
    # оригинал не мутирован
    assert data == build_exif_jpeg()
    # APP1/Exif удалён
    assert b"Exif\x00\x00" not in cleaned
    assert inspect_file("photo.jpg", cleaned).as_dict()["metadata"] == []
    # структурные маркеры сохранены (пиксели не пересжаты)
    assert cleaned.startswith(b"\xff\xd8")  # SOI
    assert b"\xff\xc0" in cleaned  # SOF0
    assert b"\xff\xda" in cleaned  # SOS
    assert cleaned.endswith(b"\xff\xd9")  # EOI
    # entropy-данные скопированы байт-в-байт
    assert b"\xd2\xab\x7f\x00" in cleaned
    assert {"Make", "GPSLatitude", "Software", "Artist"} <= set(removed)


def test_sanitize_png_strips_text() -> None:
    data = build_text_png()
    cleaned, removed = sanitize_copy("i.png", data)
    assert cleaned is not None
    assert data == build_text_png()
    assert cleaned.startswith(b"\x89PNG\r\n\x1a\n")
    assert b"IHDR" in cleaned and b"IDAT" in cleaned and b"IEND" in cleaned
    assert b"tEXt" not in cleaned
    assert inspect_file("i.png", cleaned).as_dict()["metadata"] == []
    assert set(removed) == {"Author", "Comment"}


# ==========================================================================
# Неподдержанный формат / битый файл
# ==========================================================================
def test_pdf_metadata_but_not_sanitizable() -> None:
    report = inspect_file("d.pdf", build_fake_pdf()).as_dict()
    assert report["format"] == "pdf"
    assert report["can_sanitize"] is False
    by_key = {m["key"]: m for m in report["metadata"]}
    assert by_key["Author"]["value"] == "Bob"
    assert by_key["Author"]["sensitive"] is True
    cleaned, removed = sanitize_copy("d.pdf", build_fake_pdf())
    assert cleaned is None
    assert removed == []


@pytest.mark.parametrize(
    "blob",
    [
        b"",
        b"\xff\xd8\xff garbage tail only",  # обрезанный JPEG
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\x05bad!",  # обрезанный PNG
        bytes(range(64)),  # мусор
        b"II*\x00\x08\x00\x00\x00",  # TIFF-заголовок без IFD
    ],
)
def test_corrupt_files_do_not_crash(blob: bytes) -> None:
    report = inspect_file("weird.bin", blob).as_dict()
    assert report["size_bytes"] == len(blob)
    assert isinstance(report["metadata"], list)
    cleaned, removed = sanitize_copy("weird.bin", blob)
    assert isinstance(removed, list)


def test_extract_metadata_unknown_format_empty() -> None:
    assert extract_metadata("unknown", b"whatever") == []


# ==========================================================================
# Тонкий HTTP-слой
# ==========================================================================
def test_http_inspect_endpoint(client: TestClient) -> None:
    data = build_exif_jpeg()
    resp = client.post("/api/file/inspect", files={"file": ("photo.jpg", data, "image/jpeg")})
    assert resp.status_code == 200
    body = resp.json()
    assert body["format"] == "jpeg"
    assert body["sha256"] == hashlib.sha256(data).hexdigest()
    assert any(m["key"] == "GPSLatitude" for m in body["metadata"])


def test_http_sanitize_before_after(client: TestClient) -> None:
    data = build_exif_jpeg()
    resp = client.post("/api/file/sanitize", files={"file": ("photo.jpg", data, "image/jpeg")})
    assert resp.status_code == 200
    body = resp.json()
    assert body["can_sanitize"] is True
    assert body["before"]["metadata"]
    assert body["after"]["metadata"] == []
    assert "GPSLatitude" in body["removed_fields"]


def test_http_sanitize_download(client: TestClient) -> None:
    data = build_exif_jpeg()
    resp = client.post(
        "/api/file/sanitize?download=true",
        files={"file": ("photo.jpg", data, "image/jpeg")},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    assert "attachment" in resp.headers["content-disposition"]
    assert b"Exif\x00\x00" not in resp.content


def test_http_sanitize_unsupported_returns_flag(client: TestClient) -> None:
    resp = client.post("/api/file/sanitize", files={"file": ("d.pdf", build_fake_pdf(), "application/pdf")})
    assert resp.status_code == 200
    assert resp.json()["can_sanitize"] is False


def test_http_empty_file_422(client: TestClient) -> None:
    resp = client.post("/api/file/inspect", files={"file": ("empty.bin", b"", "application/octet-stream")})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "unprocessable_data"
