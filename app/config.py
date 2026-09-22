"""Конфигурация.

Всё через переменные окружения: на shared hosting нет удобного способа
передать флаги процессу — Passenger сам запускает passenger_wsgi.py.
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def _env_list(name: str, default: str) -> list[str]:
    raw = os.environ.get(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


class Settings:
    """Плоский объект настроек (без pydantic-settings — лишняя зависимость)."""

    # --- пути -------------------------------------------------------------
    data_dir: Path = Path(os.environ.get("FORIT_DATA_DIR", str(BASE_DIR / "data")))

    #: Каталог для записи (сохранённые отчёты). На Host-0 — внутри проекта.
    state_dir: Path = Path(os.environ.get("FORIT_STATE_DIR", str(BASE_DIR / "var")))

    # --- хранилище отчётов ------------------------------------------------
    #: memory | json
    #:   memory — ничего не пишем на диск: переживает запросы, но не рестарт
    #:            Passenger и не шарится между его процессами;
    #:   json   — пишем в state_dir/reports/ — заодно проверка Host-0 на запись.
    reports_store: str = os.environ.get("FORIT_REPORTS_STORE", "json").strip().lower()

    #: Сколько отчётов держим — бесплатный тариф не место для архива.
    max_reports: int = _env_int("FORIT_MAX_REPORTS", 100)

    #: Через сколько часов отчёт протухает.
    report_ttl_hours: int = _env_int("FORIT_REPORT_TTL_HOURS", 72)

    # --- лимиты загрузки (Host-0 живёт в узких рамках) --------------------
    #: Максимальный размер одного файла, МБ.
    max_upload_mb: float = _env_float("FORIT_MAX_UPLOAD_MB", 8.0)

    #: Сколько строк реально читаем из файла (остальное отбрасываем).
    max_rows: int = _env_int("FORIT_MAX_ROWS", 50_000)

    #: Максимум колонок.
    max_columns: int = _env_int("FORIT_MAX_COLUMNS", 200)

    #: Сколько уникальных значений храним на колонку при профилировании.
    max_categories: int = _env_int("FORIT_MAX_CATEGORIES", 2_000)

    # --- пороги drift -----------------------------------------------------
    psi_warn: float = _env_float("FORIT_PSI_WARN", 0.10)
    psi_alert: float = _env_float("FORIT_PSI_ALERT", 0.25)
    #: Уровень значимости для KS / chi-square.
    p_value_alert: float = _env_float("FORIT_P_VALUE_ALERT", 0.01)
    #: Насколько должна измениться доля пропусков, чтобы это считалось дрейфом.
    missing_warn: float = _env_float("FORIT_MISSING_WARN", 0.02)
    missing_alert: float = _env_float("FORIT_MISSING_ALERT", 0.05)
    #: Число бинов для численного PSI.
    numeric_bins: int = _env_int("FORIT_NUMERIC_BINS", 10)
    #: Колонка считается идентификатором, если уникальных значений больше доли.
    id_uniqueness_ratio: float = _env_float("FORIT_ID_UNIQUENESS_RATIO", 0.95)

    # --- Chaos API --------------------------------------------------------
    #: Потолки нужны не для удобства, а чтобы инструмент для вредительства
    #: не укладывал воркер Passenger насмерть.
    chaos_max_delay_ms: int = _env_int("FORIT_CHAOS_MAX_DELAY_MS", 30_000)
    chaos_max_size_kb: int = _env_int("FORIT_CHAOS_MAX_SIZE_KB", 20_480)
    chaos_max_chunks: int = _env_int("FORIT_CHAOS_MAX_CHUNKS", 500)
    chaos_max_redirects: int = _env_int("FORIT_CHAOS_MAX_REDIRECTS", 20)

    # --- Data Burner ------------------------------------------------------
    burner_max_rows: int = _env_int("FORIT_BURNER_MAX_ROWS", 100_000)
    burner_max_columns: int = _env_int("FORIT_BURNER_MAX_COLUMNS", 60)

    # --- Scrape Lab -------------------------------------------------------
    scrape_timeout_s: float = _env_float("FORIT_SCRAPE_TIMEOUT_S", 12.0)
    scrape_max_bytes: int = _env_int("FORIT_SCRAPE_MAX_BYTES", 4 * 1024 * 1024)
    scrape_max_redirects: int = _env_int("FORIT_SCRAPE_MAX_REDIRECTS", 3)
    #: Соблюдать robots.txt. Выключать это на чужих сайтах — плохая идея.
    scrape_respect_robots: bool = _env_bool("FORIT_SCRAPE_RESPECT_ROBOTS", True)
    #: Разрешить обращения к приватным адресам. По умолчанию нет: это защита
    #: от SSRF, а не перестраховка.
    scrape_allow_private: bool = _env_bool("FORIT_SCRAPE_ALLOW_PRIVATE", False)
    #: Доп. порты сверх 80/443. Dev-only (локальные сервера на нестандартных
    #: портах). По умолчанию пусто — прод-безопасно, как и allow_private.
    scrape_extra_ports: set[int] = {int(p) for p in _env_list("FORIT_SCRAPE_EXTRA_PORTS", "") if p.isdigit()}
    #: Только ASCII: HTTP-заголовки кодируются latin-1, кириллица здесь
    #: роняет запрос ещё до отправки.
    scrape_user_agent: str = os.environ.get(
        "FORIT_SCRAPE_USER_AGENT",
        "ForitLab-ScrapeLab/0.3 (+https://forit-quest.ru; respects robots.txt)",
    )

    # --- Unicode Crime Lab ------------------------------------------------
    unicode_max_chars: int = _env_int("FORIT_UNICODE_MAX_CHARS", 50_000)

    # --- Job execution (ChunkedCursorExecutor, Host-0) --------------------
    #: Состояние порционных задач (crawl/scan) переживает многопроцессный
    #: Passenger только на диске: воркеры не делят память. Каталог — внутри var.
    jobs_max_count: int = _env_int("FORIT_JOBS_MAX_COUNT", 200)
    jobs_max_job_bytes: int = _env_int("FORIT_JOBS_MAX_JOB_BYTES", 2 * 1024 * 1024)
    jobs_max_total_bytes: int = _env_int("FORIT_JOBS_MAX_TOTAL_BYTES", 64 * 1024 * 1024)
    jobs_ttl_hours: int = _env_int("FORIT_JOBS_TTL_HOURS", 6)

    # --- Crawl (Web Parser / будущий Chaos scope) -------------------------
    crawl_max_pages: int = _env_int("FORIT_CRAWL_MAX_PAGES", 50)
    crawl_max_depth: int = _env_int("FORIT_CRAWL_MAX_DEPTH", 2)
    crawl_max_requests: int = _env_int("FORIT_CRAWL_MAX_REQUESTS", 200)
    crawl_max_bytes: int = _env_int("FORIT_CRAWL_MAX_BYTES", 32 * 1024 * 1024)
    crawl_delay_ms: int = _env_int("FORIT_CRAWL_DELAY_MS", 200)
    #: Сколько единиц работы делает один step() (порция chunked-исполнения).
    crawl_step_max_units: int = _env_int("FORIT_CRAWL_STEP_MAX_UNITS", 10)

    # --- Multi-page collection (Web Parser 1d) ----------------------------
    #: Потолки датасета отдельно от лимита состояния джобы (jobs_max_job_bytes).
    #: Точные значения для Host-0 уточняются пробой tools/result_limits_probe.py;
    #: здесь консервативные дефолты, которые точно живут в рамках shared hosting.
    collect_max_pages: int = _env_int("FORIT_COLLECT_MAX_PAGES", 50)
    collect_max_rows: int = _env_int("FORIT_COLLECT_MAX_ROWS", 5_000)
    collect_result_max_bytes: int = _env_int("FORIT_COLLECT_RESULT_MAX_BYTES", 16 * 1024 * 1024)
    collect_pages_per_step: int = _env_int("FORIT_COLLECT_PAGES_PER_STEP", 3)
    # Короткий шаг: за обратным прокси (nginx/preview) длинный одиночный запрос
    # даёт 502. Держим шаг заведомо ниже типового gateway-таймаута.
    collect_step_max_ms: int = _env_int("FORIT_COLLECT_STEP_MAX_MS", 3_500)
    collect_delay_ms: int = _env_int("FORIT_COLLECT_DELAY_MS", 200)
    #: Останавливаемся, если свободного места в state_dir меньше порога.
    collect_min_free_bytes: int = _env_int("FORIT_COLLECT_MIN_FREE_BYTES", 32 * 1024 * 1024)

    # --- API --------------------------------------------------------------
    enable_docs: bool = _env_bool("FORIT_ENABLE_DOCS", True)
    enable_status: bool = _env_bool("FORIT_ENABLE_STATUS", True)
    cors_origins: list[str] = _env_list("FORIT_CORS_ORIGINS", "*")
    root_path: str = os.environ.get("FORIT_ROOT_PATH", "")

    @property
    def max_upload_bytes(self) -> int:
        return int(self.max_upload_mb * 1024 * 1024)

    @property
    def reports_dir(self) -> Path:
        return self.state_dir / "reports"

    @property
    def jobs_dir(self) -> Path:
        return self.state_dir / "jobs"


settings = Settings()
