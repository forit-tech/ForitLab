"""Сборка ZIP-архива из (новое_имя, байты) — целиком на stdlib.

Честный способ «применить» переименование в вебе: браузер не может безопасно
менять локальные файлы, поэтому мы отдаём ZIP, внутри которого файлы уже лежат
под новыми именами.
"""

from __future__ import annotations

import io
import zipfile


def build_zip(files: list[tuple[str, bytes]]) -> bytes:
    """Собрать in-memory ZIP: имя записи = new_name, содержимое = байты.

    Дублей быть не должно — их отлавливает валидация плана до применения, но на
    всякий случай ZIP-формат сам по себе позволяет одинаковые имена, так что
    порядок записи сохраняем как есть (соответствует порядку плана).
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for new_name, data in files:
            archive.writestr(new_name, data)
    return buffer.getvalue()
