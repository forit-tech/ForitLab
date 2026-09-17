"""Finding/Evidence: три независимые оси и маскировка секретов до сериализации."""

from __future__ import annotations

from app.findings import (
    Confidence,
    Evidence,
    Finding,
    HttpSnapshot,
    Severity,
    VerificationStatus,
    mask_headers,
    mask_url,
)


def test_three_axes_are_independent():
    # разные перечисления, значения не пересекаются между осями
    assert {s.value for s in Severity} == {"info", "low", "medium", "high", "critical"}
    assert {c.value for c in Confidence} == {"low", "medium", "high"}
    assert {v.value for v in VerificationStatus} == {"potential", "indicated", "confirmed"}


def test_mask_headers():
    masked = mask_headers({"Authorization": "Bearer abc", "Cookie": "s=1", "Accept": "*/*"})
    assert masked["Authorization"] == "***"
    assert masked["Cookie"] == "***"
    assert masked["Accept"] == "*/*"


def test_mask_url_userinfo_and_secret_query():
    masked = mask_url("https://user:pass@example.com/x?api_key=SECRET&page=2&token=T")
    assert "pass" not in masked
    assert "SECRET" not in masked and "token=T" not in masked
    assert "page=2" in masked
    assert masked.startswith("https://***@example.com/x")


def test_snapshot_capture_masks():
    snap = HttpSnapshot.capture(
        method="get",
        url="https://example.com/x?token=abc",
        status=200,
        request_headers={"Authorization": "Bearer z"},
        response_headers={"Set-Cookie": "s=1"},
        body="<html>",
        size=6,
        elapsed_ms=12.3,
    )
    d = snap.to_dict()
    assert d["method"] == "GET"
    assert d["request_headers"]["Authorization"] == "***"
    assert d["response_headers"]["Set-Cookie"] == "***"
    assert "token=abc" not in d["url"]


def test_finding_serialization_keeps_axes_separate():
    f = Finding(
        id="F-1",
        title="Возможная SQL-инъекция",
        category="injection",
        severity=Severity.HIGH,
        confidence=Confidence.LOW,
        verification_status=VerificationStatus.POTENTIAL,
        target="https://user:pass@example.com/api?token=x",
        endpoint="/api/items",
        parameter="id",
        why="Различие ответов на кавычку",
        evidence=Evidence(notes="baseline vs probe"),
    )
    d = f.to_dict()
    assert d["severity"] == "high"
    assert d["confidence"] == "low"
    assert d["verification_status"] == "potential"
    assert "pass" not in d["target"] and "token=x" not in d["target"]
    assert d["evidence"]["notes"] == "baseline vs probe"
    assert d["retest"] is None
