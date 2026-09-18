"""Движок анализа cookie (raw Set-Cookie строки).

Флаги Secure/HttpOnly/SameSite, префиксы `__Host-`/`__Secure-` и некорректные
комбинации (SameSite=None без Secure, `__Host-` с Domain / без Path=/, `__Secure-`
без Secure).
"""

from __future__ import annotations

from .models import finding


def parse_cookie(raw: str) -> tuple[str, dict[str, str], set[str]]:
    """raw Set-Cookie → (name, attrs{k:v в нижнем регистре}, flags{имена без значения})."""
    parts = [p.strip() for p in raw.split(";")]
    name = parts[0].split("=", 1)[0].strip() if parts else "cookie"
    attrs: dict[str, str] = {}
    flags: set[str] = set()
    for part in parts[1:]:
        if "=" in part:
            key, value = part.split("=", 1)
            attrs[key.strip().lower()] = value.strip()
        elif part:
            flags.add(part.strip().lower())
    return name, attrs, flags


def check_cookies(cookies, https: bool) -> list[dict]:
    out: list[dict] = []
    for raw in cookies or []:
        name, attrs, flags = parse_cookie(raw)
        ev = raw[:120]
        secure = "secure" in flags
        httponly = "httponly" in flags
        samesite_present = "samesite" in attrs or "samesite" in flags
        samesite_val = (attrs.get("samesite") or "").lower()

        if https and not secure:
            out.append(finding(
                "cookie_no_secure", "medium", f"Cookie «{name}» без Secure", ev,
                "Кука без Secure может уйти по незащищённому http-соединению.",
                "Добавьте флаг Secure к cookie.", "cookies"))
        if not httponly:
            out.append(finding(
                "cookie_no_httponly", "low", f"Cookie «{name}» без HttpOnly", ev,
                "Куку без HttpOnly можно украсть через XSS (доступна из JavaScript).",
                "Добавьте флаг HttpOnly, если кука не нужна фронтенду.", "cookies"))
        if not samesite_present:
            out.append(finding(
                "cookie_no_samesite", "low", f"Cookie «{name}» без SameSite", ev,
                "Без SameSite кука отправляется на межсайтовые запросы — риск CSRF.",
                "Задайте SameSite=Lax или Strict.", "cookies"))

        if samesite_val == "none" and not secure:
            out.append(finding(
                "cookie_samesite_none_insecure", "medium", f"Cookie «{name}»: SameSite=None без Secure", ev,
                "SameSite=None без Secure отвергается современными браузерами и небезопасен.",
                "Для SameSite=None обязательно добавьте флаг Secure.", "cookies"))

        # --- префиксы ---
        if name.startswith("__Host-"):
            if not secure:
                out.append(finding(
                    "cookie_host_prefix_insecure", "medium", f"Cookie «{name}»: префикс __Host- без Secure", ev,
                    "Префикс __Host- требует Secure — иначе браузер игнорирует гарантии префикса.",
                    "Добавьте Secure к __Host- cookie.", "cookies"))
            if "domain" in attrs:
                out.append(finding(
                    "cookie_host_prefix_domain", "medium", f"Cookie «{name}»: префикс __Host- с Domain", ev,
                    "Префикс __Host- запрещает атрибут Domain — иначе кука не соответствует контракту префикса.",
                    "Уберите атрибут Domain у __Host- cookie.", "cookies"))
            if attrs.get("path") != "/":
                out.append(finding(
                    "cookie_host_prefix_path", "low", f"Cookie «{name}»: префикс __Host- без Path=/", ev,
                    "Префикс __Host- требует Path=/ — иначе браузер не примет гарантии префикса.",
                    "Задайте Path=/ для __Host- cookie.", "cookies"))
        elif name.startswith("__Secure-") and not secure:
            out.append(finding(
                "cookie_secure_prefix_insecure", "medium", f"Cookie «{name}»: префикс __Secure- без Secure", ev,
                "Префикс __Secure- требует флаг Secure — иначе он не имеет смысла.",
                "Добавьте Secure к __Secure- cookie.", "cookies"))

    return out
