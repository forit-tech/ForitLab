"""Диагностические well-known пути (origin-level).

ФИКСИРОВАННЫЙ маленький список: /.well-known/security.txt и /robots.txt. Это НЕ
directory brute force — только два стандартных пути с полезной метаинформацией.
Функции чистые: принимают уже полученные (status, text), возвращают findings.
"""

from __future__ import annotations

import datetime as _dt

from .models import finding


def parse_security_txt(text: str) -> dict[str, list[str]]:
    fields: dict[str, list[str]] = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields.setdefault(key.strip().lower(), []).append(value.strip())
    return fields


def _looks_like_security_txt(text: str, content_type: str) -> bool:
    low = (text or "").lower()
    if "contact:" in low or "-----begin pgp" in low or "expires:" in low:
        return True
    return (content_type or "").lower().startswith("text/plain") and bool(text)


def check_security_txt(status: int | None, text: str = "", content_type: str = "", origin: str = "") -> list[dict]:
    present = bool(status) and status < 400 and _looks_like_security_txt(text, content_type)
    if not present:
        return [finding(
            "security_txt_missing", "info", "Нет /.well-known/security.txt",
            "Файл не найден или не является security.txt",
            "Без security.txt исследователям некуда сообщить об уязвимости — задержка реакции.",
            "Добавьте /.well-known/security.txt с полями Contact и Expires.", "metadata", origin=origin)]

    fields = parse_security_txt(text)
    out: list[dict] = [finding(
        "security_txt_present", "info", "Найден /.well-known/security.txt",
        f"Поля: {', '.join(sorted(fields)) or '(пусто)'}",
        "Файл security.txt задаёт канал ответственного раскрытия уязвимостей.",
        "Поддерживайте актуальность полей Contact и Expires.", "metadata", origin=origin)]

    if "contact" not in fields:
        out.append(finding(
            "security_txt_no_contact", "low", "security.txt без обязательного поля Contact",
            "Поле Contact отсутствует",
            "Без Contact файл security.txt бесполезен — некуда писать о проблеме.",
            "Добавьте строку Contact: (email/URL) в security.txt.", "metadata", origin=origin))

    for raw in fields.get("expires", []):
        try:
            exp = _dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=_dt.timezone.utc)
            if exp < _dt.datetime.now(tz=_dt.timezone.utc):
                out.append(finding(
                    "security_txt_expired", "low", "security.txt просрочен (Expires в прошлом)",
                    f"Expires: {raw}",
                    "Просроченный security.txt считается недействительным.",
                    "Обновите поле Expires в security.txt.", "metadata", origin=origin))
        except ValueError:
            pass
        break

    return out


def check_robots(status: int | None, text: str | None = "", origin: str = "") -> list[dict]:
    present = bool(status) and status < 400 and text is not None
    if present:
        return [finding(
            "robots_present", "info", "Найден /robots.txt",
            f"Размер: {len(text or '')} символов",
            "robots.txt задаёт правила для поисковых роботов (не защита, а гигиена).",
            "Убедитесь, что robots.txt не раскрывает чувствительные пути.", "metadata", origin=origin)]
    return [finding(
        "robots_missing", "info", "Нет /robots.txt",
        "Файл не найден",
        "Отсутствие robots.txt не является уязвимостью — отмечено для полноты.",
        "При необходимости добавьте /robots.txt.", "metadata", origin=origin)]
