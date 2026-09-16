"""Логика поиска, фильтров, explore и surprise. Ничего не ходит в сеть."""

from __future__ import annotations

import random
import re
from datetime import date, datetime, timezone

from .catalog import ApiRecord, get_registry

# Синонимы для естественно-языкового поиска: тема на русском → категории и слова.
TOPIC_HINTS: dict[str, list[str]] = {
    "погода": ["weather"],
    "курс": ["finance", "crypto", "currency"],
    "валют": ["finance", "currency"],
    "деньги": ["finance"],
    "финанс": ["finance"],
    "крипт": ["crypto"],
    "космос": ["space"],
    "астроном": ["space"],
    "книг": ["books"],
    "стих": ["books"],
    "геокодинг": ["maps/geo", "geo"],
    "карт": ["maps/geo"],
    "адрес": ["maps/geo"],
    "страны": ["government/open data", "countries"],
    "страна": ["government/open data"],
    "наук": ["science"],
    "стать": ["science"],
    "публикац": ["science"],
    "земле": ["environment"],
    "воздух": ["environment"],
    "эколог": ["environment"],
    "кино": ["movies"],
    "сериал": ["movies"],
    "фильм": ["movies"],
    "музык": ["music"],
    "игр": ["games"],
    "викторин": ["games"],
    "спорт": ["sports"],
    "ваканс": ["jobs"],
    "работа": ["jobs"],
    "картинк": ["images"],
    "изображен": ["images"],
    "фото": ["images"],
    "кот": ["images"],
    "собак": ["images"],
    "еда": ["food"],
    "рецепт": ["food"],
    "здоров": ["health data"],
    "болезн": ["health data"],
    "транспорт": ["transport"],
    "самолёт": ["transport"],
    "полёт": ["transport"],
    "разработ": ["development"],
    "тест": ["development"],
    "фейк": ["development"],
    "имя": ["nlp"],
    "текст": ["nlp"],
    "ds": ["science", "government/open data", "environment"],
    "датасет": ["government/open data", "science", "environment"],
    "данные": ["government/open data", "science"],
}

EXPLORE_TOPICS = [
    {"id": "ds_idea", "title": "Хочу идею для DS-проекта", "categories": ["Science", "Government/Open Data", "Environment"]},
    {"id": "no_key", "title": "API без регистрации", "filter": "no_key"},
    {"id": "open_data", "title": "Open Data", "filter": "open_data"},
    {"id": "for_site", "title": "Что можно подключить к сайту", "categories": ["Weather", "Finance", "Maps/Geo", "Images"]},
    {"id": "unusual", "title": "Необычные API", "categories": ["Space", "Transport", "Misc"]},
    {"id": "pet", "title": "API для пет-проекта", "categories": ["Games", "Movies", "Books", "Images"]},
    {"id": "big_data", "title": "API с большими датасетами", "categories": ["Government/Open Data", "Science"]},
]


def _matches_query(record: ApiRecord, query: str) -> int:
    """Грубый релевантный скор. Ноль — не подходит."""
    if not query:
        return 1
    query = query.lower().strip()
    score = 0

    # Прямые вхождения в текстовые поля.
    haystacks = [
        (record.name.lower(), 5),
        (record.category.lower(), 4),
        (record.description.lower(), 3),
        (record.why_useful.lower(), 2),
        (" ".join(record.project_ideas).lower(), 2),
    ]
    for text, weight in haystacks:
        if query in text:
            score += weight

    # Тематические подсказки: «погода» → категория Weather.
    for token in re.findall(r"\w+", query):
        for stem, categories in TOPIC_HINTS.items():
            if token.startswith(stem) or stem.startswith(token):
                if record.category.lower() in categories:
                    score += 4
                if any(cat in record.description.lower() for cat in categories):
                    score += 1
    return score


def search(
    query: str = "",
    *,
    category: str | None = None,
    no_key: bool | None = None,
    free_type: str | None = None,
    rest_only: bool = False,
    cors: bool | None = None,
    commercial: bool | None = None,
    has_sdk: bool | None = None,
    limit: int = 50,
) -> list[dict]:
    today = datetime.now(timezone.utc).date()
    records = get_registry().all()

    scored: list[tuple[int, ApiRecord]] = []
    for record in records:
        if category and record.category.lower() != category.lower():
            continue
        if no_key is not None and record.no_key != no_key:
            continue
        if free_type and record.free_type != free_type:
            continue
        if cors is not None and record.cors != cors:
            continue
        if has_sdk is not None and record.sdk != has_sdk:
            continue
        if commercial and "разреш" not in record.commercial_use.lower():
            continue
        score = _matches_query(record, query)
        if score <= 0:
            continue
        scored.append((score, record))

    scored.sort(key=lambda pair: (pair[0], pair[1].name), reverse=True)
    return [record.as_card(today) for _, record in scored[:limit]]


def explore() -> dict:
    return {
        "topics": [
            {"id": topic["id"], "title": topic["title"]} for topic in EXPLORE_TOPICS
        ],
        "categories": get_registry().categories(),
        "hint": "Выберите тему или задайте вопрос естественным языком в /api/apifinder/search.",
    }


def explore_topic(topic_id: str) -> list[dict]:
    topic = next((t for t in EXPLORE_TOPICS if t["id"] == topic_id), None)
    if topic is None:
        return []
    if topic.get("filter") == "no_key":
        return search(no_key=True)
    if topic.get("filter") == "open_data":
        return search(free_type="open_data")
    today = datetime.now(timezone.utc).date()
    wanted = {c.lower() for c in topic.get("categories", [])}
    records = [r for r in get_registry().all() if r.category.lower() in wanted]
    return [record.as_card(today) for record in records]


def surprise(seed: int | None = None) -> dict:
    """Собирает связку из нескольких API и предлагает идею проекта."""
    rng = random.Random(seed)
    records = get_registry().all()
    if not records:
        return {"idea": "Каталог пуст", "apis": []}

    picked = rng.sample(records, min(3, len(records)))
    today = datetime.now(timezone.utc).date()
    categories = ", ".join(sorted({r.category for r in picked}))
    names = " + ".join(r.name for r in picked)

    idea = (
        f"Свяжите {names}: соберите данные из каждого через Web Harvester "
        f"или напрямую, склейте в один датасет и прогоните через Drift Lab, "
        f"чтобы следить, как меняются источники со временем. Темы: {categories}."
    )
    return {
        "idea": idea,
        "apis": [record.as_card(today) for record in picked],
        "workflow": "API Finder → probe → Build Dataset → Drift Lab",
    }


def match_candidate(url: str) -> dict:
    """Мост из Web Harvester: по найденному URL пытаемся узнать API.

    Если хост совпадает с записью каталога — отдаём подтверждённую карточку.
    Иначе возвращаем статус `discovered`: кандидат есть, условий мы не знаем.
    """
    from urllib.parse import urlparse

    today = datetime.now(timezone.utc).date()
    host = urlparse(url).netloc.lower().removeprefix("www.")

    for record in get_registry().all():
        for known in (record.verify_url or "", record.docs_url):
            if known and urlparse(known).netloc.lower().removeprefix("www.") == host:
                card = record.as_card(today)
                card["match"] = "catalog"
                return card

    return {
        "match": "unknown",
        "status": "discovered",
        "url": url,
        "host": host,
        "source": "web_discovery",
        "note": (
            "Кандидат найден, но в каталоге его нет. Условия бесплатности не "
            "подтверждены: откройте документацию вручную. Доступность можно "
            "проверить через /api/apifinder/check-url."
        ),
        "last_verified_at": None,
    }
