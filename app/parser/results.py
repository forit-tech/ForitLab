"""Append-only датасет результата сбора: var/jobs/<id>.result.jsonl.

Хранится ОТДЕЛЬНО от состояния джобы (у состояния жёсткий лимит размера).
Здесь — большой поток строк, дописываемый по мере обхода страниц.
"""

from __future__ import annotations

import json
from pathlib import Path


class ResultFile:
    def __init__(self, directory: Path, job_id: str) -> None:
        self.path = Path(directory) / f"{job_id}.result.jsonl"

    def append(self, rows: list[dict]) -> int:
        """Дописывает строки, возвращает новый размер файла в байтах."""
        if rows:
            with self.path.open("a", encoding="utf-8") as stream:
                for row in rows:
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        return self.size()

    def size(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0

    def read(self, limit: int | None = None):
        if not self.path.exists():
            return
        with self.path.open(encoding="utf-8") as stream:
            for i, line in enumerate(stream):
                if limit is not None and i >= limit:
                    return
                line = line.strip()
                if line:
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue

    def count(self) -> int:
        if not self.path.exists():
            return 0
        with self.path.open(encoding="utf-8") as stream:
            return sum(1 for line in stream if line.strip())
