"""Точка входа для Phusion Passenger на shared hosting.

Passenger умеет только WSGI и запускает процесс сам — постоянного uvicorn
здесь нет и быть не может. Поэтому ASGI-приложение FastAPI оборачивается
мостом a2wsgi.

Порядок действий:
  1. если нас запустили не интерпретатором из venv — перезапускаемся из него;
  2. добавляем корень проекта в sys.path;
  3. отдаём Passenger объект `application`.

Перезапуск приложения после деплоя:  touch tmp/restart.txt  (или .restart-app,
в зависимости от настроек панели — см. DEPLOY.md).
"""

import os
import sys

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

# Имя каталога venv можно переопределить, но по умолчанию — рабочий .venv313.
VENV_DIR = os.environ.get("FORIT_VENV", os.path.join(PROJECT_DIR, ".venv313"))
INTERPRETER = os.path.join(VENV_DIR, "bin", "python3.13")

# Passenger может стартовать системным python; тогда переезжаем в venv.
# execl заменяет процесс целиком, поэтому повторного захода сюда не будет:
# sys.executable уже будет равен INTERPRETER.
if os.path.exists(INTERPRETER) and os.path.realpath(sys.executable) != os.path.realpath(INTERPRETER):
    os.execl(INTERPRETER, INTERPRETER, *sys.argv)

if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

# Состояние (сохранённые отчёты) по умолчанию лежит внутри проекта:
# на shared hosting это единственный гарантированно доступный на запись каталог.
os.environ.setdefault("FORIT_STATE_DIR", os.path.join(PROJECT_DIR, "var"))

from a2wsgi import ASGIMiddleware  # noqa: E402  (импорт после правки sys.path)

from app.main import app as asgi_app  # noqa: E402

application = ASGIMiddleware(asgi_app)
