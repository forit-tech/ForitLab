"""Применение ExtractionSchema к странице → строки + asset-manifest.

Флагман — извлечение из повторяющихся DOM-структур по CSS/XPath. Для источников
json_ld/embedded_json — проекция массива объектов в таблицу. Файлы/картинки
попадают в manifest (URL), без bulk-скачивания через сервер.
"""

from __future__ import annotations

from urllib.parse import urljoin

from . import transforms
from .dom import parse as dom_parse
from .models import (
    AssetRef,
    ExtractionSchema,
    FieldSource,
    FieldSpec,
    SelectorType,
    SourceKind,
)
from .selectors import InvalidSelector, query, query_first, validate

_ASSET_SOURCES = {FieldSource.IMAGE, FieldSource.FILE_URL}


def validate_schema(schema: ExtractionSchema) -> None:
    """Полная валидация ДО сбора. Бросает InvalidSelector/InvalidTransform/ValueError."""
    if not schema.fields:
        raise ValueError("Схема без полей")
    names = [f.name for f in schema.fields]
    if any(not n for n in names):
        raise ValueError("У поля пустое имя")
    if len(set(names)) != len(names):
        raise ValueError("Имена полей повторяются")

    if schema.source_kind == SourceKind.REPEATED_DOM:
        validate(schema.container_selector, schema.container_type)
        for f in schema.fields:
            if f.selector:
                validate(f.selector, f.selector_type)
            if f.source == FieldSource.ATTR and not f.attr_name:
                raise ValueError(f"Поле {f.name!r}: source=attr требует attr_name")
            transforms.validate(f.transform, f.transform_arg)
    # для json-источников селекторы не нужны (проекция ключей)


def _field_raw(container, field: FieldSpec, base_url: str) -> tuple[str, str | None, bool]:
    """(значение, asset_url|None, matched). Умеет XPath, возвращающий строку (атрибут/text())."""
    if field.selector and field.selector_type == SelectorType.XPATH:
        raw_results = container.xpath_raw(field.selector)
        if not raw_results:
            return "", None, False
        first = raw_results[0]
        if isinstance(first, str):  # атрибут или text()
            if field.source in (FieldSource.URL, FieldSource.IMAGE, FieldSource.FILE_URL):
                absolute = urljoin(base_url, first) if first else ""
                return absolute, (absolute if field.source != FieldSource.URL and absolute else None), True
            return first, None, True
        el = _wrap_lxml(first)  # это элемент
        val, asset = _extract_value(el, field, base_url)
        return val, asset, True
    el = query_first(container, field.selector, field.selector_type) if field.selector else container
    if el is None:
        return "", None, False
    val, asset = _extract_value(el, field, base_url)
    return val, asset, True


def _wrap_lxml(node):
    from .dom import _LxmlElement

    return _LxmlElement(node)


def _extract_value(el, field: FieldSpec, base_url: str) -> tuple[str, str | None]:
    """Возвращает (значение, asset_url|None)."""
    if el is None:
        return "", None
    src = field.source
    if src == FieldSource.TEXT:
        return el.text().strip(), None
    if src == FieldSource.HTML:
        return el.inner_html(), None
    if src == FieldSource.ATTR:
        return (el.get(field.attr_name or "") or ""), None
    if src in (FieldSource.URL, FieldSource.FILE_URL):
        raw = el.get("href") or el.get("src") or el.get(field.attr_name or "") or ""
        absolute = urljoin(base_url, raw) if raw else ""
        return absolute, (absolute if src == FieldSource.FILE_URL and absolute else None)
    if src == FieldSource.IMAGE:
        raw = el.get("src") or el.get("data-src") or el.get(field.attr_name or "") or ""
        absolute = urljoin(base_url, raw) if raw else ""
        return absolute, (absolute or None)
    return "", None


def apply_schema(html: str, schema: ExtractionSchema, base_url: str = "", *, limit: int = 50) -> dict:
    """Применяет схему к HTML. Возвращает dict (rows/columns/assets/match_counts/...)."""
    validate_schema(schema)
    if schema.source_kind != SourceKind.REPEATED_DOM:
        raise ValueError(f"apply_schema: источник {schema.source_kind.value} обрабатывается отдельно (project_json)")

    doc = dom_parse(html, base_url)
    containers = query(doc.root, schema.container_selector, schema.container_type)
    columns = [f.name for f in schema.fields]
    rows: list[dict] = []
    assets: list[AssetRef] = []
    match_counts = {f.name: 0 for f in schema.fields}
    warnings: list[str] = []

    for container in containers[:limit]:
        row: dict[str, str] = {}
        for f in schema.fields:
            raw, asset, matched = _field_raw(container, f, base_url)
            value = transforms.apply(raw, f.transform, f.transform_arg)
            row[f.name] = value
            if matched and (value or asset):
                match_counts[f.name] += 1
            if asset:
                assets.append(AssetRef(field=f.name, url=asset))
        rows.append(row)

    for f in schema.fields:
        if match_counts[f.name] == 0 and containers:
            warnings.append(f"Поле {f.name!r}: селектор не дал ни одного совпадения")

    return {
        "source_kind": schema.source_kind.value,
        "container_matches": len(containers),
        "columns": columns,
        "rows": rows,
        "assets": [a.to_dict() for a in assets],
        "match_counts": match_counts,
        "truncated": len(containers) > limit,
        "warnings": warnings,
    }


def project_json(records: list, fields: list[str] | None = None, *, limit: int = 50) -> dict:
    """Проекция массива объектов (json_ld/embedded_json/api) в таблицу."""
    records = [r for r in records if isinstance(r, dict)]
    if fields is None:
        seen: list[str] = []
        for r in records[: min(len(records), 200)]:
            for k in r:
                if k not in seen:
                    seen.append(k)
        fields = seen
    rows = [{k: _stringify(r.get(k)) for k in fields} for r in records[:limit]]
    return {
        "source_kind": "json",
        "container_matches": len(records),
        "columns": fields,
        "rows": rows,
        "assets": [],
        "match_counts": {k: sum(1 for r in records[:limit] if r.get(k) not in (None, "")) for k in fields},
        "truncated": len(records) > limit,
        "warnings": [],
    }


def _stringify(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        import json

        return json.dumps(v, ensure_ascii=False)[:500]
    return str(v)
