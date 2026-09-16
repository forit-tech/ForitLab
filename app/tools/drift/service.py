"""Сценарий работы Drift Lab: прочитать → профилировать → сравнить → сохранить."""

from __future__ import annotations

import secrets
import time

from ...config import settings
from ...deps import get_store
from ...errors import NotFoundError, PayloadTooLargeError, UnprocessableDataError
from .compare import Thresholds, compare_profiles
from .profiling import MAX_NUMERIC_SAMPLE, profile_table
from .tabular import load_table

ENGINE = "psi+ks+chi2 (stdlib)"


def default_thresholds() -> Thresholds:
    return Thresholds(
        psi_warn=settings.psi_warn,
        psi_alert=settings.psi_alert,
        p_value_alert=settings.p_value_alert,
        missing_warn=settings.missing_warn,
        missing_alert=settings.missing_alert,
        numeric_bins=settings.numeric_bins,
    )


def check_size(payload: bytes, label: str) -> None:
    if len(payload) > settings.max_upload_bytes:
        raise PayloadTooLargeError(
            f"Файл {label} больше лимита {settings.max_upload_mb:g} МБ",
            {
                "limit_bytes": settings.max_upload_bytes,
                "received_bytes": len(payload),
                "hint": "Лимит выставлен под бесплатный тариф; поднимается через FORIT_MAX_UPLOAD_MB",
            },
        )


def build_profile(payload: bytes, *, name: str, filename: str | None = None):
    check_size(payload, name)
    table = load_table(
        payload,
        name=name,
        filename=filename,
        max_rows=settings.max_rows,
        max_columns=settings.max_columns,
    )
    if not table.columns:
        raise UnprocessableDataError(f"В {name} не нашлось ни одной колонки")
    if table.row_count == 0:
        raise UnprocessableDataError(f"В {name} есть заголовок, но нет строк")

    profile = profile_table(
        table,
        max_categories=settings.max_categories,
        id_uniqueness_ratio=settings.id_uniqueness_ratio,
    )
    # Сырую таблицу дальше не несём: на Host-0 память кончается раньше времени.
    del table
    return profile


def run_comparison(
    reference_payload: bytes,
    current_payload: bytes,
    *,
    reference_name: str,
    current_name: str,
    reference_filename: str | None = None,
    current_filename: str | None = None,
    thresholds: Thresholds | None = None,
    save: bool = True,
) -> dict:
    started = time.perf_counter()

    reference = build_profile(
        reference_payload, name=reference_name, filename=reference_filename
    )
    current = build_profile(current_payload, name=current_name, filename=current_filename)

    if not set(reference.column_names) & set(current.column_names):
        raise UnprocessableDataError(
            "У выгрузок нет ни одной общей колонки — сравнивать нечего",
            {
                "reference_columns": reference.column_names[:20],
                "current_columns": current.column_names[:20],
            },
        )

    report = compare_profiles(reference, current, thresholds or default_thresholds())
    report_id = secrets.token_hex(6)
    report["report_id"] = report_id
    report["tool"] = "drift"
    report["engine"] = ENGINE
    report["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)

    store = get_store()
    if save:
        report["storage"] = store.save(report_id, report).as_dict()
    else:
        report["storage"] = {
            "stored": False,
            "backend": store.backend,
            "reason": "save=false — отчёт отдан, но не сохранён",
        }
    return report


def get_report(report_id: str) -> dict:
    store = get_store()
    report = store.get(report_id)
    # Блок storage дописывается уже после сохранения, поэтому в файле его нет.
    report.setdefault("storage", {"stored": True, "backend": store.backend})
    return report


def list_reports(limit: int = 50) -> dict:
    store = get_store()
    reports = store.list(limit)
    items = [
        {
            "report_id": report.get("report_id", "?"),
            "created_at": report.get("created_at", ""),
            "status": report.get("summary", {}).get("status", "ok"),
            "verdict": report.get("summary", {}).get("verdict", ""),
            "reference": report.get("inputs", {}).get("reference", {}).get("name", "?"),
            "current": report.get("inputs", {}).get("current", {}).get("name", "?"),
            "alerts": report.get("summary", {}).get("alerts", 0),
            "warnings": report.get("summary", {}).get("warnings", 0),
        }
        for report in reports
    ]
    return {"backend": store.backend, "count": len(items), "items": items}


def delete_report(report_id: str) -> None:
    get_store().delete(report_id)


def limits() -> dict:
    store = get_store()
    return {
        "max_upload_mb": settings.max_upload_mb,
        "max_rows": settings.max_rows,
        "max_columns": settings.max_columns,
        "max_categories": settings.max_categories,
        "numeric_sample": MAX_NUMERIC_SAMPLE,
        "reports_store": store.backend,
        "max_reports": settings.max_reports,
        "report_ttl_hours": settings.report_ttl_hours,
        "notes": [
            "Лимиты подобраны под бесплатный shared hosting и меняются переменными FORIT_*.",
            "Строки сверх max_rows отбрасываются, в отчёте это помечено как truncated.",
            f"Для KS-теста берётся подвыборка до {MAX_NUMERIC_SAMPLE} значений на колонку.",
        ],
    }


def demo_payloads() -> tuple[bytes, bytes]:
    samples = settings.data_dir / "samples"
    reference = samples / "reference.csv"
    current = samples / "current.csv"
    if not reference.exists() or not current.exists():
        raise NotFoundError(
            "Демо-данные не найдены",
            {"expected": [str(reference), str(current)]},
        )
    return reference.read_bytes(), current.read_bytes()
