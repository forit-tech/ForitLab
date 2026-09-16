"""Совместимость: безопасный слой переехал в app.safefetch.

Модуль оставлен реэкспортом, чтобы Web Harvester и его тесты продолжали
импортировать привычные имена, пока код не устаканится.
"""

from ...safefetch import (  # noqa: F401
    ALLOWED_PORTS,
    ALLOWED_SCHEMES,
    FetchError,
    FetchResult,
    RobotsDisallowedError,
    UnsafeUrlError,
    fetch,
    robots_allows,
    validate_url,
)
