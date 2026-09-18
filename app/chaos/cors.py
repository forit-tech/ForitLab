"""Движок CORS.

Разбирает заголовки Access-Control-* и объясняет наблюдаемую конфигурацию.
Единственная действительно опасная (и по спецификации некорректная) комбинация —
`*` + credentials → high.
"""

from __future__ import annotations

from .models import finding, lower_headers


def check_cors(headers) -> list[dict]:
    h = lower_headers(headers)
    acao = h.get("access-control-allow-origin")
    acac = (h.get("access-control-allow-credentials") or "").lower()
    vary = (h.get("vary") or "").lower()
    out: list[dict] = []

    if acao is None:
        return out

    if acao == "*":
        if acac == "true":
            out.append(finding(
                "cors_wildcard_credentials", "high", "CORS: wildcard + credentials",
                "Access-Control-Allow-Origin: * и Allow-Credentials: true",
                "Опасная (и по спецификации некорректная) комбинация: любой сайт может слать запросы с куками.",
                "Не используйте '*' вместе с credentials — задавайте конкретный доверенный Origin.", "cors"))
        else:
            out.append(finding(
                "cors_wildcard", "low", "CORS открыт для всех (*)",
                "Access-Control-Allow-Origin: *",
                "Любой сайт может читать ответы этого источника.",
                "Если это не публичный API — ограничьте Origin списком доверенных.", "cors"))
    elif acao.lower() == "null":
        out.append(finding(
            "cors_null_origin", "medium", "CORS разрешает Origin: null",
            "Access-Control-Allow-Origin: null",
            "Origin 'null' подделывается из sandbox-iframe/data:-документов — небезопасное доверие.",
            "Не используйте 'null' как доверенный Origin.", "cors"))
    else:
        # конкретный origin: если это отражение + credentials — отметим отсутствие Vary
        if acac == "true" and "origin" not in vary:
            out.append(finding(
                "cors_reflect_no_vary", "medium", "CORS отражает Origin с credentials без Vary: Origin",
                f"Access-Control-Allow-Origin: {acao[:80]}, Allow-Credentials: true, Vary без Origin",
                "Если Origin отражается динамически без Vary: Origin — возможно кэш-отравление и утечка ответов.",
                "Добавьте Vary: Origin и разрешайте только проверенный белый список Origin.", "cors"))

    return out
