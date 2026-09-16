"""Заготовки испорченных ответов.

Каждый вариант воспроизводит реальную поломку, а не абстрактный мусор:
именно так ломаются настоящие интеграции.
"""

from __future__ import annotations

import json
import random

#: Ровно то, что клиент ожидает увидеть в хорошем мире.
VALID_BODY = {
    "ok": True,
    "data": {"id": 1, "name": "Всё хорошо", "score": 0.99},
    "meta": {"generated_by": "forit-lab/chaos"},
}

MALFORMED: dict[str, dict[str, str]] = {
    "truncated": {
        "body": '{"ok": true, "data": {"id": 1, "name": "обрыв на середин',
        "content_type": "application/json",
        "description": "JSON обрывается на середине — так выглядит ответ, который не долетел.",
    },
    "trailing_comma": {
        "body": '{"ok": true, "items": [1, 2, 3,], }',
        "content_type": "application/json",
        "description": "Висячие запятые: валидно в JS, невалидно в JSON.",
    },
    "nan": {
        "body": '{"ok": true, "score": NaN, "ratio": Infinity}',
        "content_type": "application/json",
        "description": "NaN и Infinity: Python их съест, строгий парсер — нет.",
    },
    "single_quotes": {
        "body": "{'ok': true, 'name': 'почти json'}",
        "content_type": "application/json",
        "description": "Одинарные кавычки — обычно признак repr() вместо сериализации.",
    },
    "duplicate_keys": {
        "body": '{"id": 1, "id": 2, "id": 3}',
        "content_type": "application/json",
        "description": "Повторяющиеся ключи: парсеры молча оставляют разные значения.",
    },
    "bom": {
        "body": "﻿" + json.dumps(VALID_BODY, ensure_ascii=False),
        "content_type": "application/json",
        "description": "BOM перед корректным JSON — классика выгрузок из Windows.",
    },
    "html_error": {
        "body": (
            "<!DOCTYPE html>\n<html><head><title>502 Bad Gateway</title></head>"
            "<body><h1>502 Bad Gateway</h1><p>nginx</p></body></html>"
        ),
        "content_type": "application/json",
        "description": "HTML-страница ошибки под заголовком application/json — привет от прокси.",
    },
    "empty_with_json_type": {
        "body": "",
        "content_type": "application/json",
        "description": "Пустое тело с Content-Type: application/json.",
    },
    "null_body": {
        "body": "null",
        "content_type": "application/json",
        "description": "Валидный JSON, который не является объектом.",
    },
    "xml_instead": {
        "body": '<?xml version="1.0"?><response><ok>true</ok></response>',
        "content_type": "application/json",
        "description": "XML под видом JSON — бывает при смене версии API.",
    },
    "wrong_encoding": {
        "body": "{\"ok\": true, \"name\": \"кракозябры\"}",
        "content_type": "application/json; charset=iso-8859-1",
        "description": "UTF-8 байты с заявленной charset=iso-8859-1.",
    },
}

PAGINATION_BUGS: dict[str, str] = {
    "duplicates": "Соседние страницы частично перекрываются — элементы приходят дважды.",
    "missing": "Между страницами есть дыра — часть элементов не отдаётся никогда.",
    "wrong_total": "Поле total не совпадает с реальным числом элементов.",
    "infinite": "has_next всегда true — наивный цикл `while has_next` не остановится.",
    "off_by_one": "Первая страница отдаёт на один элемент меньше остальных.",
    "unstable_order": "Порядок элементов меняется между запросами — курсор по offset разъезжается.",
    "shrinking_page": "Размер страницы уменьшается к концу выдачи без предупреждения.",
}

# HTTP-заголовки кодируются latin-1 — кириллицы тут быть не может физически,
# поэтому «враждебность» строим на некорректных, но валидных по кодировке значениях.
HOSTILE_HEADERS: dict[str, str] = {
    "X-Powered-By": "spite",
    "X-Rate-Limit-Remaining": "-1",
    "Retry-After": "soon-ish",  # обязано быть числом секунд или датой — здесь ни то, ни другое
    "X-Total-Count": "a lot",  # обязано быть числом
    "Cache-Control": "no-cache, no-store, must-revalidate, max-age=31536000",  # противоречит сам себе
    "X-Correlation-Id": "",  # пустой id, за который клиент часто цепляется
    "Warning": '199 forit-lab "this header means nothing"',
}


def fake_item(index: int, rng: random.Random) -> dict[str, object]:
    return {
        "id": index,
        "name": f"item-{index}",
        "value": round(rng.random() * 100, 2),
        "updated_at": f"2026-0{1 + index % 9}-1{index % 9}T12:00:00Z",
    }


def filler(size_bytes: int) -> bytes:
    """Заполнитель для больших ответов.

    Повторяем один блок вместо генерации случайных байтов: так ответ можно
    сделать хоть на двадцать мегабайт, не потратив столько же процессорного
    времени и памяти на его сборку.
    """
    block = ("forit-lab-chaos-" * 4 + "\n").encode()
    repeats = max(1, size_bytes // len(block))
    return block * repeats
