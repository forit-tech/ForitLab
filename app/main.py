"""Точка входа FastAPI.

Приложение собирается фабрикой: Passenger импортирует уже готовый `app`,
а тесты и локальный uvicorn могут собрать своё с другими настройками.
"""

from __future__ import annotations

import hashlib
import mimetypes
import re
from pathlib import Path

from fastapi import FastAPI

# На некоторых системах (в т.ч. Windows) mimetypes не знает webp — регистрируем,
# чтобы StaticFiles отдавал image/webp, а не application/octet-stream.
mimetypes.add_type("image/webp", ".webp")
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).resolve().parent / "static"
VERSIONED_ASSETS = ("styles.css", "app.js", "ui/kit.css", "ui/kit.js", "ui/caps.js")

from . import __service__, __version__
from .config import settings
from .errors import register_error_handlers
from .routers import meta
from .tools.apifinder.router import router as apifinder_router
from .tools.burner.router import router as burner_router
from .tools.chaos.router import router as chaos_router
from .tools.drift.router import router as drift_router
from .tools.scrape.router import router as scrape_router
from .tools.unicodelab.router import router as unicode_router

DESCRIPTION = """
**Forit Lab** — набор небольших data/dev-инструментов, которые не требуют
ни базы, ни очереди, ни нейросетей.

Первый инструмент — **Drift Lab**: загружаете `reference` и `current` выгрузки
и получаете расследование, а не просто «drift = 0.42»:

* **схема** — добавленные и исчезнувшие колонки, смена типов;
* **распределения** — PSI по квантильным бинам, двухвыборочный тест
  Колмогорова–Смирнова, размер эффекта (Cohen's d), изменение разброса;
* **категории** — chi², дивергенция Йенсена–Шеннона, новые и пропавшие значения,
  сдвиг долей, изменение кардинальности;
* **пропуски** — где `NULL` появились там, где их не было;
* **качество** — смешанные типы, схлопывание в константу, пересечение
  идентификаторов между выгрузками (привет, утечка).

Всё считается на стандартной библиотеке Python: ни numpy, ни scipy, ни pandas —
сервис рассчитан на бесплатный shared hosting с Passenger.
"""


def create_app() -> FastAPI:
    app = FastAPI(
        title="Forit Lab API",
        version=__version__,
        summary="Маленькие инструменты для данных и разработки",
        description=DESCRIPTION,
        docs_url="/docs" if settings.enable_docs else None,
        redoc_url="/redoc" if settings.enable_docs else None,
        openapi_url="/openapi.json" if settings.enable_docs else None,
        root_path=settings.root_path,
        contact={"name": "Forit Tech", "url": "https://forit-quest.ru"},
        license_info={"name": "MIT"},
    )

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            # С allow_origins=["*"] credentials всё равно запрещены спецификацией,
            # а фронту здесь достаточно анонимных запросов.
            allow_credentials=False,
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["*"],
        )

    register_error_handlers(app)

    app.include_router(meta.router)
    if settings.enable_status:
        app.include_router(meta.status_router)
    app.include_router(drift_router)
    app.include_router(burner_router)
    app.include_router(unicode_router)
    app.include_router(scrape_router)
    app.include_router(apifinder_router)
    app.include_router(chaos_router)

    # Веб-интерфейс. Отдаём одностраничное приложение из app/static.
    # API-роуты уже подключены выше, так что StaticFiles на корне их не затеняет.
    if STATIC_DIR.exists():
        index_html = versioned_index(STATIC_DIR)

        @app.get("/", include_in_schema=False)
        async def home() -> HTMLResponse:
            # сам HTML всегда перепроверяется, а CSS/JS кэшируются по версионированному URL
            return HTMLResponse(index_html, headers={"Cache-Control": "no-cache"})

        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

    return app


def asset_version(static_dir: Path) -> str:
    """Версия приложения + короткий хеш CSS/JS: кэш сбрасывается и при деплое без поднятия версии."""
    digest = hashlib.sha256()
    for name in VERSIONED_ASSETS:
        path = static_dir / name
        if path.exists():
            digest.update(path.read_bytes())
    return f"{__version__}-{digest.hexdigest()[:8]}"


def versioned_index(static_dir: Path) -> str:
    """index.html со ссылками вида /styles.css?v=<версия> и версией в футере — без сборки, один раз при старте.

    Единый источник версии — `app.__version__` (его же отдают /health и /api/status).
    """
    html = (static_dir / "index.html").read_text(encoding="utf-8")
    version = asset_version(static_dir)
    for name in VERSIONED_ASSETS:
        html = re.sub(rf'((?:href|src)="/{re.escape(name)})(?:\?v=[^"]*)?"', rf'\1?v={version}"', html)
    html = re.sub(r"(<([a-z]+)\b[^>]*\bdata-app-version\b[^>]*>)[^<]*(</\2>)", rf"\1v{__version__}\3", html)
    return html


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    # Локальная разработка. На хостинге запуск идёт через passenger_wsgi.py.
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
