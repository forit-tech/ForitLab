"""Forit Lab — витрина маленьких data/dev-инструментов на FastAPI.

Первый инструмент — Drift Lab: расследование data drift между двумя
выгрузками. Namespace-пакет рассчитан на то, что рядом появятся другие
инструменты (log autopsy, schema watch) без переписывания ядра.

Собрано под ограничения бесплатного shared hosting (REG.RU Host-0):
Passenger + a2wsgi, без Docker, без systemd, без постоянного uvicorn,
без pandas/numpy/scipy — только стандартная библиотека.
"""

__version__ = "0.2.0"
__service__ = "forit-lab"
