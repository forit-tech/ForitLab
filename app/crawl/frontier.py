"""Очередь обхода с дедупликацией и ограничением глубины/размера.

Чистая структура данных без сети: её гоняет исполнитель (chunked step),
проверяя каждый URL через CrawlScope и списывая CrawlBudget.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from urllib.parse import urldefrag, urlparse, urlunparse


def normalize_url(url: str) -> str:
    """Нормализация для дедупликации: без фрагмента, нижний регистр схемы/хоста."""
    url, _ = urldefrag(url.strip())
    p = urlparse(url)
    scheme = p.scheme.lower()
    netloc = p.netloc.lower()
    path = p.path or "/"
    return urlunparse((scheme, netloc, path, p.params, p.query, ""))


@dataclass
class Frontier:
    max_size: int = 10_000
    _queue: deque[tuple[str, int]] = field(default_factory=deque)
    _seen: set[str] = field(default_factory=set)

    def add(self, url: str, depth: int) -> bool:
        key = normalize_url(url)
        if key in self._seen:
            return False
        if len(self._seen) >= self.max_size:
            return False
        self._seen.add(key)
        self._queue.append((key, depth))
        return True

    def pop(self) -> tuple[str, int] | None:
        if not self._queue:
            return None
        return self._queue.popleft()

    def seen(self, url: str) -> bool:
        return normalize_url(url) in self._seen

    def __len__(self) -> int:
        return len(self._queue)

    @property
    def visited_count(self) -> int:
        return len(self._seen)
