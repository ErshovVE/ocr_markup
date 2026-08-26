# OCR Markup Tool

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/python-3.12-blue">
  <img alt="Streamlit" src="https://img.shields.io/badge/frontend-Streamlit-FF4B4B">
  <img alt="FastAPI" src="https://img.shields.io/badge/backend-FastAPI-009688">
  <img alt="Docker" src="https://img.shields.io/badge/deploy-Docker%20Compose-2496ED">
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-Apache%202.0-blue.svg"></a>
</p>

<p align="center">
  <b><a href="#english">en English</a></b> &nbsp;•&nbsp; <b><a href="#русский">🇷🇺 Русский</a></b>
</p>

---

<a id="english"></a>

## en English

A two-service Python toolkit for building OCR training data: a **Streamlit** app for manually labeling image→text pairs, and a **FastAPI** backend that auto-labels a batch of documents by running three OCR engines in parallel and voting on the result.

> Local, single-user tool — no auth, no multi-tenant deployment. See [`backend/README.md`](backend/README.md) and [`docs/RUNBOOK.md`](docs/RUNBOOK.md) for the operational scope this is designed for.

### Features

**✍️ Manual labeling**
- Load a working directory + a tab-separated `path\ttext` annotation file
- Paginated, filterable image list (all / unmarked / marked / **disputed** — see below)
- Edit annotation text, rotate, delete (with automatic backup), mark as handwritten
- Keyboard navigation (←/→), autosave every 10 edits + manual save
- Backup history with one-click restore

**🤖 Auto-labeling (OCR consensus)**
- Runs **PaddleOCR + SuryaOCR + Tesseract** on every detected text line and votes on the result (majority vote → preferred-engine tiebreak → best score)
- Selectable line-detection engine, adjustable confidence threshold
- Direct PDF text-layer extraction — skips OCR entirely when a PDF already has one
- Live progress tracker while a job runs, with cooperative cancellation
- Resilient to a hung engine call: a stuck OCR call can't strand future calls, it just times out and the job keeps going
- Per-file/line errors are visible in the UI, not just backend logs
- Job status survives a backend restart (disk snapshot), even though the in-memory tracker doesn't
- Lines where two engines disagreed are flagged **"Спорные"** ("disputed") and can be reviewed with each engine's individual text/confidence shown side by side

### Quickstart

**Docker Compose (recommended)** — runs both services as independent containers:
```bash
docker compose up --build
```
Frontend: http://localhost:8501 · Backend: http://localhost:8756
Put your working data under `./data` on the host — it's mounted at `/data` inside both containers; enter paths like `/data/your-folder` in the UI. Details: [`docs/docker.md`](docs/docker.md).

**Native (no Docker)**:
```bash
# Frontend
pip install -r frontend/requirements.txt
cd frontend && streamlit run app.py --server.enableXsrfProtection=false

# Backend (from repo root — uses absolute backend.* imports)
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload
```
The backend additionally needs a system Tesseract install with the `rus`/`eng` language packs (`tesseract --list-langs`). PaddleOCR/SuryaOCR models download automatically on first use.

**Frontend-only (no backend)** — a fully working scenario: manual labeling (list/editor/sidebar, backups, hotkeys) needs no backend at all. Only the auto-labeling (OCR consensus) generation mode requires `backend/` to be running; skip it if you're bringing your own image→text pairs and just want to label them by hand.

A standalone frontend executable can be built via PyInstaller:
```bash
cd frontend
pip install -r requirements-build.txt
python build_exe.py
```
This wraps the raw command documented in `frontend/pyinst_command.txt` (bundles `app.py` via `wrapper.py`; produces a native executable for the host OS, `.exe` on Windows).

### Project structure

```
frontend/            Streamlit labeling app
  app.py                mode router (landing screen → generation/manual mode)
  src/                   models, backup, annotations, image ops, hotkeys, ui/
  tests/
backend/              FastAPI OCR-consensus service
  main.py, jobs.py, pipeline.py, detector.py, recognizers.py, consensus.py, ...
  tests/
docs/                 architecture, Docker, testing, runbook — see below
predict.py            standalone offline data-generation script (not part of either service)
```

### Documentation

| Doc | Covers |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | Module map, on-disk data formats, known fragile couplings (frontend side) |
| [`backend/README.md`](backend/README.md) | Full backend API reference, PDF handling, model-readiness checks |
| [`docs/docker.md`](docs/docker.md) | Docker Compose setup, volumes, individual `docker build`/`run` |
| [`docs/testing.md`](docs/testing.md) | What's unit-tested vs. not, and why; lint config |
| [`docs/RUNBOOK.md`](docs/RUNBOOK.md) | Deploy/redeploy procedure, health checks, common issues, rollback |

### Development

```bash
pip install -r requirements-dev.txt   # pytest, ruff
pytest                                 # frontend/tests/ + backend/tests/
ruff check . && ruff format .
```

No CI is configured in this repo; no enforced commit convention beyond informal `feat:`/`fix:` prefixes; single `main` branch, direct commits, no PR workflow.

### License

[Apache License 2.0](LICENSE).

<p align="right"><a href="#русский">Русский ⬇</a></p>

---

<a id="русский"></a>

## 🇷🇺 Русский

Инструмент из двух Python-сервисов для подготовки обучающих данных для OCR: **Streamlit**-приложение для ручной разметки пар изображение→текст и **FastAPI**-бэкенд, который авторазмечает пачку документов, прогоняя три OCR-движка параллельно и голосуя за результат.

> Локальный однопользовательский инструмент — без аутентификации, без мультитенантного деплоя. Эксплуатационный охват описан в [`backend/README.md`](backend/README.md) и [`docs/RUNBOOK.md`](docs/RUNBOOK.md).

### Возможности

**✍️ Ручная разметка**
- Загрузка рабочей директории + файла разметки (`путь\tтекст`, TSV)
- Список изображений с пагинацией и фильтром (все / неразмеченные / размеченные / **спорные** — см. ниже)
- Редактирование текста, поворот, удаление (с автоматическим бэкапом), пометка как рукописный
- Навигация с клавиатуры (←/→), автосохранение каждые 10 правок + ручное сохранение
- История бэкапов с восстановлением в один клик

**🤖 Авторазметка (OCR-консенсус)**
- Прогоняет **PaddleOCR + SuryaOCR + Tesseract** по каждой обнаруженной строке текста и голосует за результат (большинство → тай-брейк по предпочитаемому движку → лучший score)
- Выбираемый движок детекции строк, настраиваемый порог уверенности
- Прямое извлечение текстового слоя PDF — полностью пропускает OCR, если у PDF уже есть текст
- Живой трекер прогресса во время выполнения задания, кооперативная отмена
- Устойчивость к зависшему вызову движка: застрявший вызов не блокирует будущие вызовы, просто отдаёт таймаут и job продолжается
- Ошибки файлов/строк видны прямо в UI, а не только в логах backend'а
- Статус задания переживает перезапуск backend'а (снэпшот на диске), хотя трекер в памяти — нет
- Строки, где два движка разошлись, помечаются **«Спорные»** — можно посмотреть текст и уверенность каждого движка отдельно

### Быстрый старт

**Docker Compose (рекомендуется)** — оба сервиса как независимые контейнеры:
```bash
docker compose up --build
```
Frontend: http://localhost:8501 · Backend: http://localhost:8756
Рабочие данные кладите в `./data` на хосте — он монтируется в `/data` внутри обоих контейнеров; в UI указывайте пути вида `/data/ваша-папка`. Подробности: [`docs/docker.md`](docs/docker.md).

**Нативно (без Docker)**:
```bash
# Frontend
pip install -r frontend/requirements.txt
cd frontend && streamlit run app.py --server.enableXsrfProtection=false

# Backend (из корня репозитория — абсолютные импорты backend.*)
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload
```
Backend'у дополнительно нужен системный Tesseract с языковыми пакетами `rus`/`eng` (`tesseract --list-langs`). Модели PaddleOCR/SuryaOCR скачиваются автоматически при первом использовании.

**Только frontend (без backend)** — тоже полностью рабочий сценарий: ручная разметка (список/редактор/сайдбар, бэкапы, хоткеи) не требует backend вообще. Backend нужен только для режима авторазметки (OCR-консенсус) — его можно пропустить, если у вас уже есть свои пары изображение→текст и нужна только ручная разметка.

Автономный исполняемый файл фронтенда собирается через PyInstaller:
```bash
cd frontend
pip install -r requirements-build.txt
python build_exe.py
```
Скрипт оборачивает сырую команду, описанную в `frontend/pyinst_command.txt` (упаковывает `app.py` через `wrapper.py`; на выходе — нативный исполняемый файл под текущую ОС, `.exe` на Windows).

### Структура репозитория

```
frontend/            Streamlit-приложение разметки
  app.py                роутер режимов (стартовый экран → авторазметка/ручная)
  src/                   models, backup, annotations, image ops, hotkeys, ui/
  tests/
backend/              FastAPI-сервис OCR-консенсуса
  main.py, jobs.py, pipeline.py, detector.py, recognizers.py, consensus.py, ...
  tests/
docs/                 архитектура, Docker, тесты, runbook — см. ниже
predict.py            автономный офлайн-скрипт генерации данных (не часть сервисов)
```

### Документация

| Документ | Содержит |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | Карта модулей, форматы данных на диске, известные хрупкие места (фронтенд) |
| [`backend/README.md`](backend/README.md) | Полный справочник backend API, обработка PDF, проверка готовности моделей |
| [`docs/docker.md`](docs/docker.md) | Настройка Docker Compose, volume'ы, сборка/запуск по отдельности |
| [`docs/testing.md`](docs/testing.md) | Что покрыто юнит-тестами, а что нет, и почему; конфиг линтера |
| [`docs/RUNBOOK.md`](docs/RUNBOOK.md) | Процедура деплоя/передеплоя, health-check'и, типичные проблемы, откат |

### Разработка

```bash
pip install -r requirements-dev.txt   # pytest, ruff
pytest                                 # frontend/tests/ + backend/tests/
ruff check . && ruff format .
```

CI в репозитории не настроен; строгой конвенции коммитов нет (неформально используются префиксы `feat:`/`fix:`); одна ветка `main`, прямые коммиты, без PR-флоу.

### Лицензия

[Apache License 2.0](LICENSE).

<p align="right"><a href="#english">English ⬆</a></p>
