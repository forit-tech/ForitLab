"""Ошибки сетевого ядра.

Живут отдельно от :mod:`app.safefetch`, чтобы и новый клиент, и старая обёртка
ссылались на одни и те же классы. `safefetch` их реэкспортирует — поэтому
`app.tools.scrape.fetcher.UnsafeUrlError is app.net.errors.UnsafeUrlError`, и
существующие тесты продолжают ловить тот же объект.
"""

from __future__ import annotations

from ..errors import AppError


class UnsafeUrlError(AppError):
    """Адрес не прошёл проверку — запрос даже не отправляется."""

    status_code = 400
    code = "unsafe_url"


class FetchError(AppError):
    """Не удалось получить ответ (сеть, таймаут, слишком много редиректов)."""

    status_code = 502
    code = "fetch_failed"


class RobotsDisallowedError(AppError):
    """robots.txt запрещает этот путь."""

    status_code = 403
    code = "robots_disallowed"
