"""TLS-движок уровня origin (один раз на origin).

Две части:
- `analyze_certificate` / `check_tls` — ЧИСТЫЙ анализ уже разобранных данных
  сертификата и согласованной версии (тестируется офлайн, без сокета).
- `probe_tls` / `check_tls_origin` — сетевой сбор этих данных: host сначала
  валидируется через :func:`app.net.ssrf.classify_ip` (резолв + проверка, что
  адрес публичный), затем обычный stdlib TLS-хендшейк к запиненному IP.
"""

from __future__ import annotations

import datetime as _dt
import socket
import ssl

from .models import finding

_SOON_DAYS = 21
_OBSOLETE_VERSIONS = {"SSLv2", "SSLv3", "TLSv1", "TLSv1.1"}


def hostname_matches(host: str, names) -> bool:
    """Проверка hostname против списка имён сертификата (с поддержкой *.example)."""
    host = (host or "").lower().rstrip(".")
    for raw in names or []:
        name = (raw or "").lower().rstrip(".")
        if not name:
            continue
        if name.startswith("*."):
            suffix = name[1:]  # ".example.com"
            head, _, tail = host.partition(".")
            if head and ("." + tail) == suffix:
                return True
        elif name == host:
            return True
    return False


def _as_utc(value) -> _dt.datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return _dt.datetime.fromtimestamp(value, tz=_dt.timezone.utc)
    if isinstance(value, _dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=_dt.timezone.utc)
    return None


def analyze_certificate(info: dict, now: _dt.datetime | None = None) -> list[dict]:
    """info: {negotiated_version, hostname, names[], not_before, not_after,
    issuer, subject, self_signed?, trusted?, error?, port?}."""
    now = now or _dt.datetime.now(tz=_dt.timezone.utc)
    origin = info.get("origin") or info.get("hostname") or ""
    out: list[dict] = []

    if info.get("error"):
        out.append(finding(
            "tls_handshake_failed", "high", "Не удалось установить доверенный TLS",
            str(info["error"])[:200],
            "Сбой TLS-хендшейка/проверки означает, что защищённое соединение не гарантировано.",
            "Проверьте сертификат и конфигурацию TLS сервера.", "tls", origin=origin))
        # даже при ошибке продолжаем, если есть распарсенные данные

    version = info.get("negotiated_version")
    if version in _OBSOLETE_VERSIONS:
        out.append(finding(
            "tls_version_obsolete", "medium", f"Устаревшая версия TLS: {version}",
            f"Согласовано: {version}",
            "Старые версии TLS/SSL имеют известные слабости (BEAST/POODLE и др.).",
            "Отключите SSLv3/TLS 1.0/1.1; включите минимум TLS 1.2 (лучше 1.3).", "tls", origin=origin))

    not_after = _as_utc(info.get("not_after"))
    if not_after is not None:
        days = (not_after - now).days
        if not_after < now:
            out.append(finding(
                "tls_cert_expired", "high", "Сертификат истёк",
                f"notAfter: {not_after.isoformat()} (просрочен на {abs(days)} дн.)",
                "Истёкший сертификат браузеры отвергают — пользователи видят предупреждение безопасности.",
                "Перевыпустите/обновите сертификат.", "tls", origin=origin))
        elif days < _SOON_DAYS:
            out.append(finding(
                "tls_cert_expiring_soon", "medium", "Сертификат скоро истекает",
                f"notAfter: {not_after.isoformat()} (осталось {days} дн.)",
                "Скорое истечение грозит внезапной недоступностью сайта по HTTPS.",
                "Настройте автопродление (например, ACME/Let's Encrypt).", "tls", origin=origin))

    if info.get("hostname") and info.get("names") is not None:
        if not hostname_matches(info["hostname"], info["names"]):
            out.append(finding(
                "tls_cert_hostname_mismatch", "high", "Имя в сертификате не совпадает с хостом",
                f"host={info['hostname']}, SAN/CN={', '.join(info['names'][:6])}",
                "Несовпадение имени означает, что сертификат выдан не для этого домена — риск MITM.",
                "Используйте сертификат, покрывающий этот hostname (SAN).", "tls", origin=origin))

    if info.get("self_signed") or info.get("trusted") is False:
        out.append(finding(
            "tls_cert_untrusted", "high", "Самоподписанный или недоверенный сертификат",
            f"issuer: {info.get('issuer') or '(неизвестен)'}",
            "Недоверенный сертификат не подтверждает подлинность сервера — соединение можно подменить.",
            "Установите сертификат, выданный доверенным центром сертификации.", "tls", origin=origin))

    return out


# обратная совместимость по имени
check_tls = analyze_certificate


def _flatten_name(rdn_seq) -> str:
    """(( (k,v), ), …) из getpeercert() → 'k=v, k=v'."""
    parts = []
    for rdn in rdn_seq or ():
        for key, value in rdn:
            parts.append(f"{key}={value}")
    return ", ".join(parts)


def probe_tls(host: str, port: int = 443, timeout: float = 6.0) -> dict:
    """Сетевой сбор данных сертификата. Возвращает info-dict для analyze_certificate.

    Host валидируется через SSRF-классификацию (резолв + публичность адреса).
    Любая ошибка отражается в info['error'] — исключения наружу не выбрасываются
    для аналитики, только для явных проблем валидации адреса.
    """
    from ..net.resolver import SystemResolver
    from ..net.ssrf import classify_ip

    info: dict = {"hostname": host, "origin": f"https://{host}:{port}", "port": port}
    try:
        addrs = SystemResolver().resolve(host, port)
    except LookupError as exc:
        info["error"] = f"DNS: {exc}"
        return info
    if not addrs:
        info["error"] = "имя не резолвится"
        return info
    for addr in addrs:
        safe, reason = classify_ip(addr.ip)
        if not safe:
            info["error"] = f"адрес отклонён (SSRF): {reason}"
            return info
    ip = addrs[0].ip

    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((ip, port), timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as tls:
                info["negotiated_version"] = tls.version()
                cert = tls.getpeercert() or {}
        info["trusted"] = True
        names = [v for typ, v in cert.get("subjectAltName", ()) if typ.lower() == "dns"]
        subject = _flatten_name(cert.get("subject"))
        issuer = _flatten_name(cert.get("issuer"))
        if not names and "commonName" in subject:
            names = [subject.split("commonName=", 1)[1].split(",", 1)[0].strip()]
        info["names"] = names
        info["subject"] = subject
        info["issuer"] = issuer
        info["self_signed"] = bool(subject) and subject == issuer
        for key, dest in (("notBefore", "not_before"), ("notAfter", "not_after")):
            if cert.get(key):
                info[dest] = _dt.datetime.fromtimestamp(ssl.cert_time_to_seconds(cert[key]), tz=_dt.timezone.utc)
    except ssl.SSLCertVerificationError as exc:
        info["trusted"] = False
        info["error"] = f"проверка сертификата не прошла: {exc.verify_message or exc}"
    except (ssl.SSLError, OSError) as exc:
        info["error"] = f"TLS-хендшейк не удался: {exc}"
    return info


def check_tls_origin(host: str, port: int = 443, timeout: float = 6.0) -> list[dict]:
    """Пробинг + анализ. Все findings помечены origin=https://host:port."""
    return analyze_certificate(probe_tls(host, port, timeout))
