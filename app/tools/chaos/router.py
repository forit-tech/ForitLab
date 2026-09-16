"""HTTP-слой Chaos API.

Все параметры зажаты потолками из настроек: инструмент должен мучить клиента,
а не убивать воркер Passenger, в котором сам же и живёт.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Path, Query, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field

from ...config import settings
from ...errors import AppError
from . import TOOL_TITLE
from .payloads import (
    HOSTILE_HEADERS,
    MALFORMED,
    PAGINATION_BUGS,
    VALID_BODY,
    fake_item,
    filler,
)

router = APIRouter(prefix="/api/chaos", tags=[TOOL_TITLE])


class Scenario(BaseModel):
    id: str
    title: str
    example: str
    description: str


class ScenarioList(BaseModel):
    tool: str
    warning: str
    limits: dict[str, int]
    scenarios: list[Scenario]


class MalformedKind(BaseModel):
    id: str
    description: str
    example: str


async def _sleep(delay_ms: int) -> int:
    """Спит не дольше потолка и возвращает фактическую задержку."""
    capped = max(0, min(delay_ms, settings.chaos_max_delay_ms))
    if capped:
        await asyncio.sleep(capped / 1000)
    return capped


@router.get(
    "/scenarios",
    response_model=ScenarioList,
    summary="Каталог способов испортить вам день",
)
async def scenarios() -> ScenarioList:
    return ScenarioList(
        tool="chaos",
        warning=(
            "Эндпоинты специально ломаются. Не подключайте их к чему-то, "
            "что не должно падать."
        ),
        limits={
            "max_delay_ms": settings.chaos_max_delay_ms,
            "max_size_kb": settings.chaos_max_size_kb,
            "max_chunks": settings.chaos_max_chunks,
            "max_redirects": settings.chaos_max_redirects,
        },
        scenarios=[
            Scenario(
                id="respond",
                title="Универсальный ответ",
                example="/api/chaos/respond?status=503&delay_ms=2000&body=malformed_json",
                description="Собирает нужную комбинацию кода, задержки и тела.",
            ),
            Scenario(
                id="status",
                title="Произвольный код ответа",
                example="/api/chaos/status/418",
                description="Отдаёт ровно тот статус, который попросили.",
            ),
            Scenario(
                id="delay",
                title="Медленный ответ",
                example="/api/chaos/delay/5000",
                description="Проверка клиентских таймаутов и пула соединений.",
            ),
            Scenario(
                id="malformed",
                title="Битый JSON",
                example="/api/chaos/malformed/truncated",
                description="Десяток способов отдать не тот JSON, которого ждут.",
            ),
            Scenario(
                id="huge",
                title="Гигантский ответ",
                example="/api/chaos/huge?size_kb=5120",
                description="Проверка лимитов памяти и буферизации на всём пути.",
            ),
            Scenario(
                id="stream",
                title="Медленная струйка",
                example="/api/chaos/stream?chunks=10&interval_ms=500",
                description="Данные идут по капле — ловит таймауты между чанками.",
            ),
            Scenario(
                id="disconnect",
                title="Обрыв на середине",
                example="/api/chaos/disconnect?after_chunks=3",
                description="Соединение рвётся посреди тела ответа.",
            ),
            Scenario(
                id="pagination",
                title="Сломанная пагинация",
                example="/api/chaos/pagination?page=1&bug=duplicates",
                description="Семь способов, которыми ломается постраничная выдача.",
            ),
            Scenario(
                id="flaky",
                title="Плавающая ошибка",
                example="/api/chaos/flaky?fail_rate=0.5",
                description="Падает через раз — проверка ретраев и идемпотентности.",
            ),
            Scenario(
                id="redirect",
                title="Цепочка редиректов",
                example="/api/chaos/redirect?times=5",
                description="Длинная цепочка или замкнутый цикл.",
            ),
            Scenario(
                id="headers",
                title="Враждебные заголовки",
                example="/api/chaos/headers",
                description="Retry-After не числом, пустой correlation id и прочая радость.",
            ),
        ],
    )


@router.get(
    "/respond",
    summary="Универсальный испорченный ответ",
    description=(
        "Комбинирует задержку, статус и тело. Параметры зажаты потолками из "
        "`/api/chaos/scenarios`."
    ),
)
async def respond(
    status: int = Query(default=200, ge=100, le=599),
    delay_ms: int = Query(default=0, ge=0, description="Задержка перед ответом"),
    jitter_ms: int = Query(default=0, ge=0, description="Случайная добавка к задержке"),
    body: str = Query(
        default="json",
        description="json | text | html | empty | malformed_json | huge",
    ),
    size_kb: int = Query(default=64, ge=1, description="Размер тела для body=huge"),
    fail_rate: float = Query(default=0.0, ge=0.0, le=1.0, description="Доля случайных 500"),
    seed: int | None = Query(default=None, description="Фиксирует случайность"),
    hostile_headers: bool = Query(default=False, description="Добавить враждебные заголовки"),
) -> Response:
    rng = random.Random(seed)
    total_delay = delay_ms + (rng.randint(0, jitter_ms) if jitter_ms else 0)
    actual_delay = await _sleep(total_delay)

    if fail_rate and rng.random() < fail_rate:
        status, body = 500, "json"

    headers = {"X-Chaos-Delay-Ms": str(actual_delay), "X-Chaos-Requested-Status": str(status)}
    if hostile_headers:
        headers.update(HOSTILE_HEADERS)

    # 204 и 304 по спецификации не имеют тела; отдадим честно пустой ответ.
    if status in {204, 304}:
        return Response(status_code=status, headers=headers)

    if body == "empty":
        return Response(status_code=status, headers=headers, media_type="application/json")
    if body == "text":
        return PlainTextResponse("всё сломано, но текстом", status_code=status, headers=headers)
    if body == "html":
        return Response(
            content="<html><body><h1>Не то, что вы просили</h1></body></html>",
            status_code=status,
            media_type="text/html",
            headers=headers,
        )
    if body == "malformed_json":
        variant = MALFORMED["truncated"]
        return Response(
            content=variant["body"],
            status_code=status,
            media_type=variant["content_type"],
            headers=headers,
        )
    if body == "huge":
        capped_kb = min(size_kb, settings.chaos_max_size_kb)
        headers["X-Chaos-Size-Kb"] = str(capped_kb)
        return Response(
            content=filler(capped_kb * 1024),
            status_code=status,
            media_type="text/plain",
            headers=headers,
        )

    return JSONResponse(
        content={**VALID_BODY, "requested_status": status, "delay_ms": actual_delay},
        status_code=status,
        headers=headers,
    )


@router.get("/status/{code}", summary="Ответ с заданным кодом")
async def arbitrary_status(code: int = Path(ge=100, le=599)) -> Response:
    if code in {204, 304}:
        return Response(status_code=code)
    return JSONResponse(
        status_code=code,
        content={"requested_status": code, "note": "Этот код запрошен вами, а не случился сам"},
    )


@router.get("/delay/{milliseconds}", summary="Медленный ответ")
async def delay(milliseconds: int = Path(ge=0)) -> dict:
    started = time.perf_counter()
    actual = await _sleep(milliseconds)
    return {
        "requested_ms": milliseconds,
        "slept_ms": actual,
        "measured_ms": round((time.perf_counter() - started) * 1000, 1),
        "capped": milliseconds > settings.chaos_max_delay_ms,
        "cap_ms": settings.chaos_max_delay_ms,
    }


@router.get(
    "/malformed",
    response_model=list[MalformedKind],
    summary="Список способов испортить JSON",
)
async def malformed_kinds() -> list[MalformedKind]:
    return [
        MalformedKind(
            id=key,
            description=variant["description"],
            example=f"/api/chaos/malformed/{key}",
        )
        for key, variant in MALFORMED.items()
    ]


@router.get("/malformed/{kind}", summary="Битый JSON выбранного сорта")
async def malformed(kind: str) -> Response:
    variant = MALFORMED.get(kind)
    if variant is None:
        raise AppError(
            f"Неизвестный способ сломать JSON: {kind}",
            {"available": sorted(MALFORMED)},
        )
    return Response(
        content=variant["body"],
        media_type=variant["content_type"],
        headers={"X-Chaos-Malformed": kind},
    )


@router.get("/huge", summary="Гигантский ответ")
async def huge(
    size_kb: int = Query(default=1024, ge=1, description="Желаемый размер тела"),
    stream: bool = Query(default=True, description="Отдавать потоком или одним куском"),
) -> Response:
    capped_kb = min(size_kb, settings.chaos_max_size_kb)
    headers = {
        "X-Chaos-Size-Kb": str(capped_kb),
        "X-Chaos-Capped": str(size_kb > capped_kb).lower(),
    }

    if not stream:
        return Response(content=filler(capped_kb * 1024), media_type="text/plain", headers=headers)

    async def generate() -> AsyncIterator[bytes]:
        # Гоним по мегабайту: так проверяется буферизация на всём пути,
        # а память сервера не выедается целиком.
        chunk = filler(1024 * 1024)
        remaining = capped_kb * 1024
        while remaining > 0:
            piece = chunk[: min(len(chunk), remaining)]
            remaining -= len(piece)
            yield piece

    return StreamingResponse(generate(), media_type="text/plain", headers=headers)


@router.get("/stream", summary="Ответ по капле")
async def stream(
    chunks: int = Query(default=10, ge=1),
    interval_ms: int = Query(default=500, ge=0),
    chunk_size: int = Query(default=64, ge=1, le=65536, description="Байт в одном чанке"),
) -> StreamingResponse:
    capped_chunks = min(chunks, settings.chaos_max_chunks)
    # Потолок общий на весь ответ, иначе 500 чанков по 30 секунд повесят воркер.
    interval = min(interval_ms, settings.chaos_max_delay_ms // max(capped_chunks, 1))

    async def generate() -> AsyncIterator[bytes]:
        for index in range(capped_chunks):
            if index:
                await asyncio.sleep(interval / 1000)
            yield (f"chunk {index + 1}/{capped_chunks} " + "." * chunk_size + "\n").encode()

    return StreamingResponse(
        generate(),
        media_type="text/plain",
        headers={
            "X-Chaos-Chunks": str(capped_chunks),
            "X-Chaos-Interval-Ms": str(interval),
        },
    )


@router.get("/disconnect", summary="Обрыв посреди ответа")
async def disconnect(
    after_chunks: int = Query(default=3, ge=1, le=100),
    declare_length: bool = Query(
        default=True,
        description="Заявить Content-Length больше, чем реально будет отдано",
    ),
) -> StreamingResponse:
    """Рвёт соединение на середине тела.

    Клиент либо увидит незакрытый chunked-поток, либо получит меньше байт,
    чем обещал Content-Length. Оба случая регулярно ломают наивные клиенты.
    """

    async def generate() -> AsyncIterator[bytes]:
        for index in range(after_chunks):
            yield f'{{"chunk": {index}, "ok": true}}\n'.encode()
            await asyncio.sleep(0.05)
        # Исключение внутри генератора обрывает передачу: ответ остаётся
        # незавершённым, как при падении апстрима.
        raise ConnectionResetError("Chaos API оборвал ответ намеренно")

    headers = {"X-Chaos-Disconnect-After": str(after_chunks)}
    if declare_length:
        headers["Content-Length"] = str(1024 * 1024)

    return StreamingResponse(generate(), media_type="application/json", headers=headers)


@router.get("/pagination", summary="Сломанная постраничная выдача")
async def pagination(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=10, ge=1, le=100),
    total: int = Query(default=95, ge=1, le=10_000),
    bug: str = Query(default="duplicates", description="Какой именно баг воспроизвести"),
    seed: int | None = Query(default=None),
) -> dict:
    if bug not in PAGINATION_BUGS:
        raise AppError(f"Неизвестный баг пагинации: {bug}", {"available": sorted(PAGINATION_BUGS)})

    rng = random.Random(seed if seed is not None else page)
    pages_total = max(1, -(-total // per_page))
    offset = (page - 1) * per_page
    size = per_page

    if bug == "duplicates":
        offset = max(0, offset - 2)  # страницы перекрываются на два элемента
    elif bug == "missing":
        offset = offset + 2  # между страницами остаётся дыра
    elif bug == "off_by_one" and page == 1:
        size = per_page - 1
    elif bug == "shrinking_page":
        size = max(1, per_page - (page - 1))

    items = [fake_item(offset + i, rng) for i in range(size) if offset + i < total]
    if bug == "unstable_order":
        rng.shuffle(items)

    reported_total = total
    if bug == "wrong_total":
        reported_total = total + rng.randint(5, 50)

    has_next = page < pages_total
    if bug == "infinite":
        has_next = True

    return {
        "items": items,
        "page": page,
        "per_page": per_page,
        "total": reported_total,
        "pages": pages_total,
        "has_next": has_next,
        "_chaos": {"bug": bug, "explanation": PAGINATION_BUGS[bug], "real_total": total},
    }


@router.get("/flaky", summary="Падает через раз")
async def flaky(
    request: Request,
    fail_rate: float = Query(default=0.5, ge=0.0, le=1.0),
    seed: int | None = Query(default=None),
    status: int = Query(default=503, ge=400, le=599),
) -> Response:
    rng = random.Random(seed)
    if rng.random() < fail_rate:
        return JSONResponse(
            status_code=status,
            content={
                "error": {
                    "code": "chaos_flaky",
                    "message": "Не повезло. Повторите запрос — возможно, повезёт.",
                }
            },
            headers={"Retry-After": "1"},
        )
    return JSONResponse(
        content={"ok": True, "attempt_survived": True, "path": str(request.url.path)}
    )


@router.get("/redirect", summary="Цепочка редиректов")
async def redirect(
    times: int = Query(default=5, ge=1, description="Сколько раз перекинуть"),
    loop: bool = Query(default=False, description="Замкнуть цепочку в цикл"),
) -> RedirectResponse:
    capped = min(times, settings.chaos_max_redirects)
    if loop:
        # Цикл из двух шагов: наивный клиент без счётчика будет ходить вечно.
        return RedirectResponse(url="/api/chaos/redirect?times=1&loop=true", status_code=302)
    if capped <= 1:
        return RedirectResponse(url="/api/chaos/scenarios", status_code=302)
    return RedirectResponse(url=f"/api/chaos/redirect?times={capped - 1}", status_code=302)


@router.get("/headers", summary="Враждебные заголовки")
async def headers() -> Response:
    return JSONResponse(
        content={
            "ok": True,
            "note": "Посмотрите на заголовки ответа, а не на тело",
            "headers": HOSTILE_HEADERS,
        },
        headers=HOSTILE_HEADERS,
    )


@router.post("/echo", summary="Эхо запроса, но с искажениями")
async def echo(
    request: Request,
    corrupt: bool = Query(default=True, description="Испортить эхо до неузнаваемости"),
) -> Response:
    raw = await request.body()
    try:
        parsed = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        parsed = {"_raw": raw[:500].decode("utf-8", "replace")}

    if not corrupt:
        return JSONResponse(content={"received": parsed})

    # Клиенты часто верят, что эхо вернёт ровно отправленное. Не вернёт.
    return Response(
        content=json.dumps({"received": parsed}, ensure_ascii=False)[:-1],
        media_type="application/json",
        headers={"X-Chaos-Echo": "truncated-on-purpose"},
    )
