"""Проверка доступности эндпоинта через общий безопасный слой.

Важно: это проверка ДОСТУПНОСТИ, а не бесплатности. Живой ответ без ключа не
делает API бесплатным, а требование ключа не делает его платным — условия
free tier берутся из документации, здесь мы только смотрим, отвечает ли
публичный безопасный эндпоинт прямо сейчас.

Пользовательские ключи сюда не попадают: проверяем только no-key эндпоинты и
публичные demo-ключи, уже зашитые в verify_url каталога.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from ...errors import AppError
from ...safefetch import fetch


def check_availability(verify_url: str | None) -> dict:
    checked_at = datetime.now(timezone.utc).isoformat()
    if not verify_url:
        return {
            "ok": False,
            "checked_at": checked_at,
            "reason": "У записи нет безопасного эндпоинта для проверки",
        }

    try:
        # verify_url — это документированный пример вызова из каталога, а не
        # краулинг: robots.txt здесь не применяем, SSRF-защита остаётся.
        result = fetch(verify_url, respect_robots=False)
    except AppError as exc:
        return {"ok": False, "checked_at": checked_at, "reason": exc.message}

    outcome: dict[str, object] = {
        "ok": 200 <= result.status < 400,
        "checked_at": checked_at,
        "status": result.status,
        "content_type": result.content_type,
        "elapsed_ms": result.elapsed_ms,
        "bytes": len(result.body),
    }

    if "json" in result.content_type:
        try:
            parsed = json.loads(result.text)
        except json.JSONDecodeError:
            outcome["json"] = False
        else:
            outcome["json"] = True
            if isinstance(parsed, dict):
                outcome["shape"] = "object"
                outcome["preview_keys"] = list(parsed)[:20]
            elif isinstance(parsed, list):
                outcome["shape"] = "array"
                outcome["items"] = len(parsed)
                if parsed and isinstance(parsed[0], dict):
                    outcome["item_keys"] = list(parsed[0])[:20]
                    outcome["ready_for_dataset"] = True
    return outcome


def probe_preview(verify_url: str | None, max_chars: int = 2000) -> dict:
    """Как check_availability, но ещё отдаёт кусок тела для предпросмотра."""
    result = check_availability(verify_url)
    if not result.get("ok") or not verify_url:
        return result
    try:
        fetched = fetch(verify_url, respect_robots=False)
        result["preview"] = fetched.text[:max_chars]
    except AppError as exc:
        result["preview_error"] = exc.message
    return result
