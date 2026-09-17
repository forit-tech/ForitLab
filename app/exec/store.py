"""Дисковое хранилище состояний джоб (деталь ChunkedCursorExecutor).

Почему диск: воркеры Passenger не делят память, поэтому джоба, начатая одним
воркером, должна быть видна другому на следующем step(). Единственный общий
ресурс — файловая система (var/jobs).

Гарантии:
* opaque random job id (secrets), id не кодирует путь/цель/данные пользователя;
* атомарная запись (tempfile + os.replace);
* межпроцессная блокировка на джобу (кроссплатформенный lock-файл) — два
  воркера не портят одну джобу при одновременном step();
* повреждённый/частично записанный файл трактуется как отсутствующий, а не
  роняет процесс;
* TTL и жёсткие лимиты: число джоб, размер одной джобы, общий объём каталога.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

_ID_RE = re.compile(r"^[0-9a-f]{32}$")


class JobStoreLimits:
    def __init__(self, max_jobs: int, max_job_bytes: int, max_total_bytes: int, ttl_seconds: int) -> None:
        self.max_jobs = max_jobs
        self.max_job_bytes = max_job_bytes
        self.max_total_bytes = max_total_bytes
        self.ttl_seconds = ttl_seconds


class JobTooLargeError(Exception):
    """Состояние джобы превысило лимит размера — сохранять нельзя."""


@contextmanager
def _file_lock(lock_path: Path, *, timeout: float = 5.0, stale: float = 30.0) -> Iterator[None]:
    """Кроссплатформенная блокировка через атомарный lock-файл (O_CREAT|O_EXCL)."""
    start = time.monotonic()
    acquired = False
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(time.time()).encode())
            os.close(fd)
            acquired = True
            break
        except FileExistsError:
            try:
                age = time.time() - lock_path.stat().st_mtime
            except OSError:
                age = 0.0
            if age > stale:  # осиротевший lock от упавшего воркера
                try:
                    lock_path.unlink()
                except OSError:
                    pass
                continue
            if time.monotonic() - start > timeout:
                raise TimeoutError(f"не удалось взять блокировку {lock_path.name}")
            time.sleep(0.02)
    try:
        yield
    finally:
        if acquired:
            try:
                lock_path.unlink()
            except OSError:
                pass


class FileJobStore:
    def __init__(self, directory: Path, limits: JobStoreLimits) -> None:
        self._dir = directory
        self._limits = limits

    @property
    def directory(self) -> Path:
        self._ensure_dir()
        return self._dir

    def new_id(self) -> str:
        return secrets.token_hex(16)

    def _path(self, job_id: str) -> Path:
        if not _ID_RE.match(job_id):
            raise ValueError("некорректный job id")
        return self._dir / f"{job_id}.json"

    def _result_path(self, job_id: str) -> Path:
        return self._dir / f"{job_id}.result.jsonl"

    def _lock_path(self, job_id: str) -> Path:
        return self._dir / f"{job_id}.lock"

    def _ensure_dir(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)

    def load(self, job_id: str) -> dict | None:
        try:
            path = self._path(job_id)
        except ValueError:
            return None
        try:
            with path.open(encoding="utf-8") as stream:
                return json.load(stream)
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError):
            # частично записанный/битый файл — как будто джобы нет
            return None

    def save(self, job_id: str, data: dict) -> None:
        payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        if len(payload.encode("utf-8")) > self._limits.max_job_bytes:
            raise JobTooLargeError("состояние джобы превысило лимит размера")
        self._ensure_dir()
        path = self._path(job_id)
        handle, tmp_name = tempfile.mkstemp(dir=self._dir, suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(payload)
            os.replace(tmp_name, path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    def delete(self, job_id: str) -> None:
        try:
            self._path(job_id).unlink(missing_ok=True)
            self._result_path(job_id).unlink(missing_ok=True)
        except (ValueError, OSError):
            pass

    @contextmanager
    def locked(self, job_id: str) -> Iterator[None]:
        self._ensure_dir()
        with _file_lock(self._lock_path(job_id)):
            yield

    def evict(self) -> None:
        """TTL + лимиты по числу и общему объёму. Терминальные джобы уходят первыми."""
        if not self._dir.exists():
            return
        files = list(self._dir.glob("*.json"))
        now = time.time()

        def _drop(path: Path) -> None:
            path.unlink(missing_ok=True)
            # вместе с состоянием удаляем и датасет результата (иначе .result.jsonl копятся)
            self._dir.joinpath(path.stem + ".result.jsonl").unlink(missing_ok=True)

        # TTL
        for path in files:
            try:
                if self._limits.ttl_seconds > 0 and (now - path.stat().st_mtime) > self._limits.ttl_seconds:
                    _drop(path)
            except OSError:
                continue
        files = sorted(
            (p for p in self._dir.glob("*.json")),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        # лимит по количеству
        for path in files[self._limits.max_jobs :]:
            _drop(path)
        # лимит по общему объёму (режем самые старые), учитывая и датасеты
        files = sorted(self._dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        total = 0
        for path in files:
            try:
                size = path.stat().st_size
                result = self._dir.joinpath(path.stem + ".result.jsonl")
                size += result.stat().st_size if result.exists() else 0
            except OSError:
                continue
            total += size
            if total > self._limits.max_total_bytes:
                _drop(path)
