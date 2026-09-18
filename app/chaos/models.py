"""Единая модель findings для всех движков Chaos.

Finding — обычный dict фиксированной формы. Никакого «Security Score»: движки
возвращают только честные наблюдения. Каждый движок — чистая функция, которая
принимает уже разобранные данные (заголовки/куки/текст/сертификат) и отдаёт
`list[Finding]`, поэтому тестируется офлайн без единого сетевого вызова.

Finding = {
    id, severity: high|medium|low|info, category, title,
    evidence, why, recommendation, [url], [origin]
}
"""

from __future__ import annotations

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}


def finding(
    fid: str,
    severity: str,
    title: str,
    evidence: str,
    why: str,
    recommendation: str,
    category: str = "misc",
    **extra: object,
) -> dict:
    """Собрать один Finding. `extra` — необязательные поля вроде url/origin."""
    out = {
        "id": fid,
        "severity": severity,
        "category": category,
        "title": title,
        "evidence": evidence,
        "why": why,
        "recommendation": recommendation,
    }
    out.update(extra)
    return out


def sort_findings(findings: list[dict]) -> list[dict]:
    """Стабильная сортировка по важности (high → info)."""
    return sorted(findings, key=lambda f: SEVERITY_ORDER[f["severity"]])


def summarize(findings: list[dict]) -> dict:
    """Счётчик по уровням важности."""
    return {sev: sum(1 for f in findings if f["severity"] == sev) for sev in ("high", "medium", "low", "info")}


def lower_headers(headers) -> dict:
    """Заголовки к нижнему регистру ключей (значения не трогаем)."""
    return {str(k).lower(): v for k, v in (headers or {}).items()}
