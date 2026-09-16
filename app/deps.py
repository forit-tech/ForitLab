"""Общие для приложения объекты: хранилище и отметка старта процесса.

Passenger поднимает и убивает воркеры когда захочет, поэтому «старт процесса»
это именно старт воркера, а не аптайм сервиса. Для диагностики так честнее.
"""

from __future__ import annotations

import time

from .config import settings
from .storage import ReportStore, build_store

PROCESS_STARTED_AT = time.time()

_store: ReportStore | None = None


def get_store() -> ReportStore:
    global _store
    if _store is None:
        _store = build_store(
            settings.reports_store,
            settings.reports_dir,
            settings.max_reports,
            settings.report_ttl_hours,
        )
    return _store
