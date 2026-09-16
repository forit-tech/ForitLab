<p align="center">
  <img src="app/static/brand/logo-fox.png" alt="FORIT TECH" width="120">
</p>

<h1 align="center">🦊 Forit Lab</h1>

<p align="center">
  Лаборатория из шести инструментов для работы с <b>данными, API и текстом</b>:<br>
  добыть → создать/испортить → исследовать → сравнить → проверить клиент.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11%2B-fb7132?logo=python&logoColor=white">
  <img src="https://img.shields.io/badge/FastAPI-0.141-a855f7?logo=fastapi&logoColor=white">
  <img src="https://img.shields.io/badge/stdlib--only-без%20pandas%20%2F%20numpy%20%2F%20scipy-22d3ee">
  <img src="https://img.shields.io/badge/tests-176%20passed-3fb950">
  <img src="https://img.shields.io/badge/license-MIT-f5b53c">
</p>

---

## 📑 Содержание

- [🌟 О проекте](#-о-проекте)
- [🚀 Инструменты](#-инструменты)
  - [🌐 Web Harvester](#-web-harvester--достань-данные)
  - [🔎 API Finder](#-api-finder--найди-источник)
  - [🔥 Data Burner](#-data-burner--создай-синтетику)
  - [🔬 Drift Lab](#-drift-lab--сравни-версии)
  - [🔤 Unicode Crime Lab](#-unicode-crime-lab--раскопай-текст)
  - [😈 Chaos API](#-chaos-api--сломай-свой-клиент)
- [🔗 Как соединяются](#-как-соединяются)
- [🛠 Технологии](#-технологии)
- [📦 Установка и запуск](#-установка-и-запуск-локально)
- [🗂 Структура проекта](#-структура-проекта)
- [🌐 API](#-api)
- [🧪 Тестирование](#-тестирование)
- [📄 Лицензия](#-лицензия)

---

## 🌟 О проекте

**Forit Lab** — продукт [FORIT TECH](https://github.com/forit-tech): единое пространство, где шесть небольших,
но серьёзных инструментов закрывают полный цикл работы с данными. Каждый решает свой этап, и все они соединяются
в один конвейер.

Ключевая особенность: **вся статистика и разбор написаны на стандартной библиотеке Python** — без `pandas`,
`numpy` и `scipy`. Благодаря этому проект запускается где угодно, включая самый дешёвый shared-хостинг с Passenger.

<p align="center">
  <img src="docs/images/home.png" alt="Главная страница Forit Lab" width="900">
</p>

<p align="center"><i>Рис. 1 — Главная страница лаборатории</i></p>

---

## 🚀 Инструменты

### 🌐 Web Harvester — достань данные
Принимает ссылку на публичную страницу и вытаскивает всё структурированное: таблицы, повторяющиеся
карточки-сущности, ссылки, картинки, формы, метаданные, JSON-LD и кандидатов в открытые API.
Любую часть можно выгрузить датасетом (CSV / JSON / NDJSON).

<p align="center"><img src="docs/images/harvester.png" alt="Web Harvester" width="900"></p>
<p align="center"><i>Рис. 2 — Разбор страницы: метрики и таблицы</i></p>

### 🔎 API Finder — найди источник
Ищет **бесплатные** публичные API по теме на естественном языке. Только free forever / free tier /
open data / без ключа — trial-only отсекается. Карточка каждого API: авторизация, лимиты, CORS, форматы,
ссылка на документацию и дата проверки.

<p align="center"><img src="docs/images/finder.png" alt="API Finder" width="900"></p>
<p align="center"><i>Рис. 3 — Поиск бесплатных API с карточками условий</i></p>

### 🔥 Data Burner — создай синтетику
Генерирует реалистичные выгрузки с управляемыми дефектами: пропуски, выбросы, дубли, перекос классов,
сломанные даты, unicode-ловушки, дрейф. Умеет собрать пару `reference`/`current` сразу для Drift Lab.

<p align="center"><img src="docs/images/burner.png" alt="Data Burner" width="900"></p>
<p align="center"><i>Рис. 4 — Конструктор синтетического датасета</i></p>

### 🔬 Drift Lab — сравни версии
Сравнивает две выгрузки и объясняет расхождения: смена схемы, распределения (PSI, KS-тест), категории
(χ², новые/пропавшие значения), рост пропусков, утечка идентификаторов. С человеческим разбором
«что это значит и что делать», а не сухим «drift = 0.42».

<p align="center"><img src="docs/images/drift.png" alt="Drift Lab" width="900"></p>
<p align="center"><i>Рис. 5 — Отчёт о дрейфе и его разбор</i></p>

### 🔤 Unicode Crime Lab — раскопай текст
Вскрывает невидимый текстовый мусор: zero-width, NBSP, управляющие символы, разницу NFC/NFD и
кириллицу под видом латиницы — с подсветкой прямо в тексте. Даёт очищенную строку с копированием.

<p align="center"><img src="docs/images/unicode.png" alt="Unicode Crime Lab" width="900"></p>
<p align="center"><i>Рис. 6 — Подсветка проблемных символов и очищенная строка</i></p>

### 😈 Chaos API — сломай свой клиент
Эндпоинт, который намеренно ведёт себя плохо: задержки, произвольные 5xx, битый JSON, обрыв соединения,
сломанная пагинация, гигантский ответ, враждебные заголовки. Проверь, переживёт ли клиент реальную жизнь.

<p align="center"><img src="docs/images/chaos.png" alt="Chaos API" width="900"></p>
<p align="center"><i>Рис. 7 — Конструктор хаоса и разбор ответа</i></p>

---

## 🔗 Как соединяются

```
API Finder → Web Harvester → Data Burner → Unicode Crime Lab → Drift Lab → Chaos API
 найти        добыть          создать/       исследовать        сравнить     проверить
 источник     данные          испортить      текст              версии       клиент
```

---

## 🛠 Технологии

- **Python 3.11+**
- **FastAPI** + **a2wsgi** (мост ASGI → WSGI для Passenger)
- **python-multipart** (загрузка файлов)
- Вся аналитика — **стандартная библиотека** (PSI, KS-тест, χ², JSD, профилирование, парсинг HTML на `html.parser`)
- Фронтенд — **чистый HTML/CSS/JS** без сборки и внешних зависимостей

---

## 📦 Установка и запуск (локально)

### 1️⃣ Клонирование
```bash
git clone https://github.com/forit-tech/ForitLab.git
cd ForitLab
```

### 2️⃣ Виртуальное окружение и зависимости
```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

pip install -r requirements-dev.txt
```

### 3️⃣ Запуск
```bash
uvicorn app.main:app --port 8000
```

Приложение будет доступно по адресу **http://127.0.0.1:8000/**
API-документация (Swagger) — **http://127.0.0.1:8000/docs**

---

## 🗂 Структура проекта

```
ForitLab/
├── app/
│   ├── main.py              # сборка FastAPI, отдача веб-интерфейса
│   ├── config.py            # настройки через переменные окружения
│   ├── safefetch.py         # единый безопасный слой исходящих запросов (SSRF-защита)
│   ├── routers/meta.py      # /, /health, /api/status, /api/tools
│   ├── tools/               # шесть инструментов, каждый — отдельный пакет
│   │   ├── scrape/          # Web Harvester
│   │   ├── apifinder/       # API Finder
│   │   ├── burner/          # Data Burner
│   │   ├── drift/           # Drift Lab
│   │   ├── unicodelab/      # Unicode Crime Lab
│   │   └── chaos/           # Chaos API
│   └── static/              # фронтенд (index.html, styles.css, app.js) + brand/
├── data/                    # каталог API + демо-датасеты
├── tests/                   # 176 тестов
├── passenger_wsgi.py        # точка входа для shared-хостинга
├── requirements.txt         # прод-зависимости (без dev)
├── DEPLOY.md                # деплой на REG.RU Host-0 (Passenger + a2wsgi)
└── README.md
```

---

## 🌐 API

| Метод | Путь | Назначение |
|-------|------|------------|
| `GET` | `/` | Веб-интерфейс лаборатории |
| `GET` | `/api` | Машиночитаемое описание сервиса |
| `GET` | `/health` | Healthcheck |
| `GET` | `/api/status` | Диагностика окружения |
| `GET` | `/api/tools` | Каталог инструментов |
| `POST` | `/api/scrape/inspect` | Разбор страницы (Web Harvester) |
| `GET` | `/api/apifinder/search` | Поиск API (API Finder) |
| `GET` | `/api/burner/datasets` | Генерация датасета (Data Burner) |
| `POST` | `/api/drift/reports` | Сравнение выгрузок (Drift Lab) |
| `POST` | `/api/unicode/inspect` | Разбор строки (Unicode Crime Lab) |
| `GET` | `/api/chaos/respond` | Управляемо «плохой» ответ (Chaos API) |

Полный список — в Swagger по `/docs`.

---

## 🧪 Тестирование


```bash
pytest
```

**176 тестов**: спецфункции против табличных критических значений, определение типов данных,
чтение форматов, HTTP-слой, SSRF-защита и проверка, что подложенные дефекты реально находятся.


---



## 📄 Лицензия

[MIT](LICENSE) © FORIT TECH
