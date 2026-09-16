"""Каталог API и источники discovery.

Источник (`CatalogSource`) — это абстракция: сегодня единственный источник
читает встроенный JSON, завтра рядом встанут внешние каталоги и находки из
Web Harvester. Бизнес-логика Finder работает со списком записей и не знает,
откуда они пришли.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from ...config import settings

# Статусы записи — по возрастанию доверия.
STATUS_DISCOVERED = "discovered"          # найден кандидат, условия не подтверждены
STATUS_DOCS_VERIFIED = "docs_verified"    # условия подтверждены официальной документацией
STATUS_AVAILABILITY_CHECKED = "availability_checked"  # + живой безопасный эндпоинт отвечает
STATUS_STALE = "stale"                    # данные давно не перепроверялись

#: Допустимые виды бесплатности. Всё остальное (в т.ч. trial) отсекается.
FREE_TYPES = {"free_forever", "free_tier", "open_data"}

#: Через сколько дней docs-проверка считается протухшей.
STALE_AFTER_DAYS = 180


@dataclass
class ApiRecord:
    id: str
    name: str
    category: str
    description: str
    auth: str                 # none | key | oauth
    free_type: str            # free_forever | free_tier | open_data
    request_limit: str
    rate_limit: str
    commercial_use: str
    cors: bool
    https: bool
    formats: list[str]
    sdk: bool
    docs_url: str
    verify_url: str | None
    source: str               # official_docs | github | web_discovery | ...
    why_useful: str
    project_ideas: list[str] = field(default_factory=list)
    status: str = STATUS_DOCS_VERIFIED
    last_verified_at: str = ""
    availability: dict | None = None

    @property
    def no_key(self) -> bool:
        return self.auth == "none"

    @property
    def is_free(self) -> bool:
        # Free-only правило продукта: no-key ИЛИ один из бесплатных типов.
        return self.no_key or self.free_type in FREE_TYPES

    def effective_status(self, today: date) -> str:
        if self.availability and self.availability.get("ok"):
            return STATUS_AVAILABILITY_CHECKED
        if self.status == STATUS_DOCS_VERIFIED and self._is_stale(today):
            return STATUS_STALE
        return self.status

    def _is_stale(self, today: date) -> bool:
        if not self.last_verified_at:
            return True
        try:
            checked = date.fromisoformat(self.last_verified_at[:10])
        except ValueError:
            return True
        return (today - checked).days > STALE_AFTER_DAYS

    def as_card(self, today: date | None = None) -> dict:
        today = today or datetime.now(timezone.utc).date()
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "auth": self.auth,
            "no_key": self.no_key,
            "free_type": self.free_type,
            "request_limit": self.request_limit,
            "rate_limit": self.rate_limit,
            "commercial_use": self.commercial_use,
            "cors": self.cors,
            "https": self.https,
            "formats": self.formats,
            "sdk": self.sdk,
            "docs_url": self.docs_url,
            "why_useful": self.why_useful,
            "project_ideas": self.project_ideas,
            "status": self.effective_status(today),
            "source": self.source,
            "last_verified_at": self.last_verified_at,
            "availability": self.availability,
            "actions": {
                "details": f"/api/apifinder/apis/{self.id}",
                "check_availability": f"/api/apifinder/apis/{self.id}/check",
                "example_request": self.verify_url,
            },
        }


class CatalogSource(Protocol):
    """Источник кандидатов. Реализаций может быть много."""

    name: str

    def load(self) -> list[ApiRecord]:  # pragma: no cover - протокол
        ...


class BundledCatalogSource:
    """Встроенный выверенный каталог из data/apis.json."""

    name = "bundled"

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> list[ApiRecord]:
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        curated_at = raw.get("curated_at", "")
        records: list[ApiRecord] = []
        for item in raw.get("apis", []):
            records.append(
                ApiRecord(
                    id=item["id"],
                    name=item["name"],
                    category=item["category"],
                    description=item["description"],
                    auth=item.get("auth", "none"),
                    free_type=item.get("free_type", "free_forever"),
                    request_limit=item.get("request_limit", "Not specified"),
                    rate_limit=item.get("rate_limit", "Not specified"),
                    commercial_use=item.get("commercial_use", "Not specified"),
                    cors=bool(item.get("cors", False)),
                    https=bool(item.get("https", True)),
                    formats=item.get("formats", []),
                    sdk=bool(item.get("sdk", False)),
                    docs_url=item.get("docs_url", ""),
                    verify_url=item.get("verify_url"),
                    source=item.get("source", "official_docs"),
                    why_useful=item.get("why_useful", ""),
                    project_ideas=item.get("project_ideas", []),
                    # Записи каталога считаются подтверждёнными документацией.
                    status=STATUS_DOCS_VERIFIED,
                    last_verified_at=item.get("last_verified_at", curated_at),
                )
            )
        return records


class Registry:
    """Собирает записи из всех источников и обеспечивает free-only правило."""

    def __init__(self, sources: list[CatalogSource]) -> None:
        self._sources = sources

    def all(self) -> list[ApiRecord]:
        seen: dict[str, ApiRecord] = {}
        for source in self._sources:
            for record in source.load():
                # Free-only — жёсткое правило продукта, а не пользовательский фильтр.
                if not record.is_free:
                    continue
                seen.setdefault(record.id, record)
        return list(seen.values())

    def get(self, api_id: str) -> ApiRecord | None:
        for record in self.all():
            if record.id == api_id:
                return record
        return None

    def categories(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for record in self.all():
            counts[record.category] = counts.get(record.category, 0) + 1
        return dict(sorted(counts.items()))

    def source_names(self) -> list[str]:
        return [source.name for source in self._sources]


@lru_cache(maxsize=1)
def get_registry() -> Registry:
    # Один источник в MVP; добавление новых — просто расширение списка.
    return Registry([BundledCatalogSource(settings.data_dir / "apis.json")])
