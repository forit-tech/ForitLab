"""Проба реальных лимитов датасета сбора на Host-0.

Пишет append-only jsonl во временный файл в state_dir и меряет: сколько строк/
байт удаётся записать до упора в диск/квоту/иноды и как быстро. По результату
уточняются FORIT_COLLECT_RESULT_MAX_BYTES / FORIT_COLLECT_MAX_ROWS в проде.

Запуск на Host-0:
    ./.venv313/bin/python3.13 tools/result_limits_probe.py [target_mb]

Ничего лишнего не оставляет: временный файл удаляется в конце.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

TARGET_MB = int(sys.argv[1]) if len(sys.argv) > 1 else 64
STATE_DIR = Path(os.environ.get("FORIT_STATE_DIR", "var"))


def main() -> int:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        usage = shutil.disk_usage(str(STATE_DIR))
        print(f"disk: free {usage.free // 1024 // 1024} MiB / total {usage.total // 1024 // 1024} MiB")
    except OSError as exc:
        print("disk_usage недоступен:", exc)

    probe = STATE_DIR / f".result-probe-{os.getpid()}.jsonl"
    row = {"id": 0, "title": "Пример товара с описанием", "price": "12 990", "url": "https://example.com/p/00000", "img": "https://example.com/img/00000.jpg"}
    written = 0
    rows = 0
    limit = TARGET_MB * 1024 * 1024
    started = time.time()
    try:
        with probe.open("w", encoding="utf-8") as stream:
            while written < limit:
                row["id"] = rows
                line = json.dumps(row, ensure_ascii=False) + "\n"
                stream.write(line)
                written += len(line.encode("utf-8"))
                rows += 1
                if rows % 20000 == 0:
                    stream.flush()
        elapsed = time.time() - started
        print(f"OK: записано {rows} строк / {written // 1024 // 1024} MiB за {elapsed:.1f} c "
              f"(~{int(rows / elapsed)} строк/с)")
        print("рекомендация: держать FORIT_COLLECT_RESULT_MAX_BYTES заметно ниже free-квоты, "
              "FORIT_COLLECT_MAX_ROWS — по времени шага и памяти экспорта")
        return 0
    except OSError as exc:
        print(f"УПЁРЛИСЬ на {rows} строк / {written // 1024 // 1024} MiB: {exc}")
        return 1
    finally:
        probe.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
