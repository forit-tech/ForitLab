"""Хранилище отчётов.

Два режима, и оба честные про свои ограничения:

* memory — словарь в процессе. На Passenger это значит «отчёт виден только
  тому воркеру, который его сделал, и только до рестарта»;
* json   — файл на отчёт в state_dir/reports. Переживает рестарт и общий для
  всех воркеров, но упирается в дисковую квоту и инодов shared hosting.

Запись никогда не роняет запрос: если хостинг не дал записать, отчёт всё
равно возвращается, а причина уезжает в поле `storage` ответа.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from .errors import NotFoundError


@dataclass
class SaveResult:
    stored: bool
    backend: str
    reason: str | None = None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"stored": self.stored, "backend": self.backend}
        if self.reason:
            payload["reason"] = self.reason
        return payload


class MemoryReportStore:
    backend = "memory"

    def __init__(self, max_reports: int) -> None:
        self._max = max_reports
        self._lock = threading.Lock()
        self._items: OrderedDict[str, dict] = OrderedDict()

    def save(self, report_id: str, report: dict) -> SaveResult:
        with self._lock:
            self._items[report_id] = report
            self._items.move_to_end(report_id)
            while len(self._items) > self._max:
                self._items.popitem(last=False)
        return SaveResult(
            stored=True,
            backend=self.backend,
            reason="Отчёт живёт в памяти процесса: не переживёт рестарт Passenger",
        )

    def get(self, report_id: str) -> dict:
        with self._lock:
            report = self._items.get(report_id)
        if report is None:
            raise NotFoundError(f"Отчёт {report_id} не найден", {"report_id": report_id})
        return report

    def list(self, limit: int = 50) -> list[dict]:
        with self._lock:
            return list(reversed(list(self._items.values())))[:limit]

    def delete(self, report_id: str) -> None:
        with self._lock:
            if self._items.pop(report_id, None) is None:
                raise NotFoundError(f"Отчёт {report_id} не найден", {"report_id": report_id})

    def count(self) -> int:
        with self._lock:
            return len(self._items)

    def writable(self) -> bool:
        return True


class JsonFileReportStore:
    backend = "json"

    def __init__(self, directory: Path, max_reports: int, ttl_hours: int) -> None:
        self._dir = directory
        self._max = max_reports
        self._ttl_seconds = ttl_hours * 3600
        self._lock = threading.Lock()

    def _ensure_dir(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, report_id: str) -> Path:
        # report_id генерируем сами (hex), но путь всё равно не склеиваем вслепую.
        safe = "".join(ch for ch in report_id if ch.isalnum() or ch in {"-", "_"})
        if not safe:
            raise NotFoundError("Некорректный идентификатор отчёта", {"report_id": report_id})
        return self._dir / f"{safe}.json"

    def save(self, report_id: str, report: dict) -> SaveResult:
        try:
            with self._lock:
                self._ensure_dir()
                payload = json.dumps(report, ensure_ascii=False, separators=(",", ":"))
                # Пишем через временный файл в том же каталоге: os.replace
                # атомарен, и параллельный читатель не увидит половину JSON.
                handle, tmp_name = tempfile.mkstemp(dir=self._dir, suffix=".tmp")
                try:
                    with os.fdopen(handle, "w", encoding="utf-8") as stream:
                        stream.write(payload)
                    os.replace(tmp_name, self._path(report_id))
                except BaseException:
                    Path(tmp_name).unlink(missing_ok=True)
                    raise
                self._evict()
        except OSError as exc:
            return SaveResult(
                stored=False,
                backend=self.backend,
                reason=f"Хостинг не дал записать отчёт: {exc.strerror or exc}",
            )
        return SaveResult(stored=True, backend=self.backend)

    def _evict(self) -> None:
        """Чистим протухшее и лишнее — на бесплатном тарифе место кончается быстро."""
        files = sorted(self._dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        now = time.time()
        for index, path in enumerate(files):
            expired = self._ttl_seconds > 0 and (now - path.stat().st_mtime) > self._ttl_seconds
            if index >= self._max or expired:
                path.unlink(missing_ok=True)

    def get(self, report_id: str) -> dict:
        path = self._path(report_id)
        try:
            with path.open(encoding="utf-8") as stream:
                return json.load(stream)
        except FileNotFoundError:
            raise NotFoundError(f"Отчёт {report_id} не найден", {"report_id": report_id}) from None
        except (OSError, json.JSONDecodeError) as exc:
            raise NotFoundError(
                f"Отчёт {report_id} не читается", {"report_id": report_id, "reason": str(exc)}
            ) from exc

    def list(self, limit: int = 50) -> list[dict]:
        if not self._dir.exists():
            return []
        files = sorted(self._dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        reports: list[dict] = []
        for path in files[:limit]:
            try:
                with path.open(encoding="utf-8") as stream:
                    reports.append(json.load(stream))
            except (OSError, json.JSONDecodeError):
                continue  # битый файл не должен ронять список
        return reports

    def delete(self, report_id: str) -> None:
        path = self._path(report_id)
        if not path.exists():
            raise NotFoundError(f"Отчёт {report_id} не найден", {"report_id": report_id})
        try:
            path.unlink()
        except OSError as exc:
            raise NotFoundError(f"Не удалось удалить отчёт {report_id}", {"reason": str(exc)}) from exc

    def count(self) -> int:
        return len(list(self._dir.glob("*.json"))) if self._dir.exists() else 0

    def writable(self) -> bool:
        try:
            self._ensure_dir()
            probe = self._dir / ".write-probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return True
        except OSError:
            return False


ReportStore = MemoryReportStore | JsonFileReportStore


def build_store(kind: str, directory: Path, max_reports: int, ttl_hours: int) -> ReportStore:
    if kind == "memory":
        return MemoryReportStore(max_reports)
    return JsonFileReportStore(directory, max_reports, ttl_hours)
