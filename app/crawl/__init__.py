"""Примитивы обхода: строгий scope, бюджет, очередь. Без сети.

Используются и Web Parser (мягкая политика), и будущим Chaos (строгий scope
внутри authorized target). Сетевые запросы делает :mod:`app.net`.
"""

from __future__ import annotations

from .frontier import Frontier, normalize_url
from .scope import CrawlBudget, CrawlScope, HostRule, Origin, ScopeDecision

__all__ = [
    "CrawlScope",
    "CrawlBudget",
    "HostRule",
    "Origin",
    "ScopeDecision",
    "Frontier",
    "normalize_url",
]
