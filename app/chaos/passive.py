"""Chaos 1a — Passive Security Check (композиция движков).

Отвечает на простой вопрос: «Я дал URL. Какие очевидные проблемы безопасности
видны БЕЗ атаки на сайт?». Только чтение ответа: заголовки, куки, схема, HTML.

Раньше все проверки жили здесь монолитом; теперь `run_checks` лишь КОМПОНУЕТ
чистые движки-компоненты (headers/csp/cookies/cors/content/disclosure/redirects).
Каждый движок тестируется отдельно и офлайн. Сигнатура и набор прежних id/severity
сохранены — старые тесты и роутер продолжают работать.

TLS, security.txt и OPTIONS требуют сети и относятся к origin — их дергает роутер
(см. `app.chaos.tls`, `app.chaos.metadata`, `app.chaos.active_safe`), а здесь их
нет, чтобы `run_checks` оставался чистой функцией над одним ответом.
"""

from __future__ import annotations

from urllib.parse import urlparse

from .content import check_content
from .cookies import check_cookies
from .cors import check_cors
from .csp import check_csp
from .disclosure import check_disclosure
from .headers import check_security_headers
from .models import lower_headers, sort_findings, summarize
from .redirects import check_redirect_chain, check_scheme

_CHECKS_RUN = ["scheme", "headers", "csp", "cookies", "cors", "content", "disclosure", "redirects"]


def run_checks(primary, http_probe, requested_url: str) -> dict:
    """primary/http_probe — объекты с .final_url/.status/.headers/.cookies/.text (или None).

    `redirect_chain` у primary — опционален (getattr): старые фейковые ответы его
    не имеют, и это корректно даёт «нет findings по редиректам».
    """
    h = primary.headers or {}
    hl = lower_headers(h)
    scheme = urlparse(primary.final_url).scheme
    https = scheme == "https"
    csp_raw = hl.get("content-security-policy") or ""

    findings: list[dict] = []
    findings += check_scheme(https, scheme, http_probe)
    findings += check_security_headers(h, https, csp_raw)
    findings += check_csp(csp_raw or None)
    findings += check_cookies(primary.cookies or [], https)
    findings += check_cors(h)
    findings += check_content(primary.text, https, primary.final_url)
    findings += check_disclosure(h, primary.text)
    findings += check_redirect_chain(getattr(primary, "redirect_chain", None) or [], requested_url, primary.final_url)

    findings = sort_findings(findings)
    return {
        "url": requested_url,
        "final_url": primary.final_url,
        "status": primary.status,
        "https": https,
        "findings": findings,
        "summary": summarize(findings),
        "checks_run": list(_CHECKS_RUN),
    }
