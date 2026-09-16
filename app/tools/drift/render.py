"""Текстовый рендер отчёта — то, что не стыдно вставить в тикет или в CI-лог."""

from __future__ import annotations

MARKS = {"ok": "✓", "info": "·", "warn": "⚠", "alert": "✕"}


def _num(value: object) -> str:
    if isinstance(value, int):
        return f"{value:,}".replace(",", " ")
    if isinstance(value, float):
        return f"{value:,.4g}".replace(",", " ")
    return str(value)


def _pct(value: object) -> str:
    return f"{float(value) * 100:.1f}%" if isinstance(value, (int, float)) else "—"


def _psi_mark(value: float, thresholds: dict) -> str:
    """В таблице PSI отметка должна отражать сам PSI.

    Статус колонки складывается из всех находок сразу (например, из всплеска
    пропусков), и подставлять его рядом с числом PSI — значит вводить в
    заблуждение.
    """
    if value >= float(thresholds.get("psi_alert", 0.25)):
        return MARKS["alert"]
    if value >= float(thresholds.get("psi_warn", 0.10)):
        return MARKS["warn"]
    return MARKS["ok"]


def _section(lines: list[str], title: str) -> None:
    lines.append("")
    lines.append(title)
    lines.append("-" * len(title))


def render_text(report: dict) -> str:
    lines: list[str] = []
    inputs = report.get("inputs", {})
    reference = inputs.get("reference", {})
    current = inputs.get("current", {})
    summary = report.get("summary", {})
    rows = report.get("rows", {})
    schema = report.get("schema", {})
    columns = report.get("columns", [])

    title = "DATASET DRIFT REPORT"
    lines.append(title)
    lines.append("=" * len(title))
    if report.get("report_id"):
        lines.append(f"report    {report['report_id']}")
    lines.append(f"created   {report.get('created_at', '')}")
    lines.append(
        f"sources   {reference.get('name', 'reference')} ({reference.get('format', '?')}) "
        f"vs {current.get('name', 'current')} ({current.get('format', '?')})"
    )

    # --- строки -----------------------------------------------------------
    _section(lines, "Rows")
    lines.append(f"  reference   {_num(rows.get('reference', 0)):>12}")
    lines.append(f"  current     {_num(rows.get('current', 0)):>12}")
    diff = rows.get("diff", 0)
    change = rows.get("change")
    change_text = f"  ({change * 100:+.1f}%)" if isinstance(change, (int, float)) else ""
    lines.append(f"  delta       {_num(diff):>12}{change_text}")
    for label, table in (("reference", reference), ("current", current)):
        if table.get("truncated"):
            lines.append(f"  ! {label} обрезан по лимиту строк — сравнение по усечённой выборке")

    # --- схема ------------------------------------------------------------
    _section(lines, "Schema")
    unchanged = schema.get("unchanged", [])
    lines.append(f"  {MARKS['ok']} {len(unchanged)} columns unchanged")
    for column in schema.get("added", []):
        lines.append(f"  {MARKS['warn']} new column: {column}")
    for column in schema.get("removed", []):
        lines.append(f"  {MARKS['alert']} column removed: {column}")
    for change_item in schema.get("type_changed", []):
        lines.append(
            f"  {MARKS['alert']} {change_item['column']}: {change_item['from']} → {change_item['to']}"
        )

    # --- распределения ----------------------------------------------------
    drifting = [c for c in columns if c["analysis"] in {"numeric", "categorical"}]
    if drifting:
        _section(lines, "Distribution drift (PSI)")
        width = max(len(c["column"]) for c in drifting)
        for column in sorted(
            drifting, key=lambda c: float(c["metrics"].get("psi") or 0.0), reverse=True
        ):
            psi_value = column["metrics"].get("psi")
            if psi_value is None:
                continue
            mark = _psi_mark(float(psi_value), report.get("thresholds", {}))
            extra = ""
            if column["analysis"] == "numeric":
                ks = column["metrics"].get("ks_statistic")
                if ks is not None:
                    extra = f"   KS {ks:.3f}"
            lines.append(f"  {column['column']:<{width}}  {float(psi_value):>6.3f}  {mark}{extra}")

    # --- пропуски ---------------------------------------------------------
    missing_rows = [
        (c["column"], c["metrics"].get("missing_reference", 0.0), c["metrics"].get("missing_current", 0.0), c)
        for c in columns
        if any(f["code"].startswith("missing.") for f in c["findings"])
    ]
    if missing_rows:
        _section(lines, "Missingness")
        width = max(len(name) for name, _, _, _ in missing_rows)
        for name, ref_rate, cur_rate, column in missing_rows:
            mark = MARKS.get(column["status"], "·")
            lines.append(f"  {name:<{width}}  {_pct(ref_rate):>7} → {_pct(cur_rate):<7}  {mark}")

    # --- категории --------------------------------------------------------
    category_changes = [
        c
        for c in columns
        if c["metrics"].get("new_categories") or c["metrics"].get("missing_categories")
    ]
    if category_changes:
        _section(lines, "Categories")
        for column in category_changes:
            lines.append(f"  {column['column']}:")
            for value in column["metrics"].get("new_categories", [])[:10]:
                lines.append(f"    + {value}")
            for value in column["metrics"].get("missing_categories", [])[:10]:
                lines.append(f"    - {value}")

    # --- находки ----------------------------------------------------------
    flagged = [c for c in columns if c["findings"]]
    if flagged or schema.get("findings"):
        _section(lines, "Findings")
        for finding in schema.get("findings", []):
            lines.append(f"  {MARKS.get(finding['severity'], '·')} [schema] {finding['message']}")
        for column in flagged:
            for finding in column["findings"]:
                mark = MARKS.get(finding["severity"], "·")
                lines.append(f"  {mark} [{column['column']}] {finding['message']}")

    # --- вердикт ----------------------------------------------------------
    _section(lines, "Verdict")
    lines.append(f"  {MARKS.get(summary.get('status', 'ok'), '·')} {summary.get('verdict', '')}")
    lines.append(
        f"  alerts {summary.get('alerts', 0)} · warnings {summary.get('warnings', 0)} "
        f"· notes {summary.get('notes', 0)} · columns analyzed {summary.get('columns_analyzed', 0)}"
    )
    lines.append("")
    return "\n".join(lines)
