# OCR Markup Tool

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/python-3.12-blue">
  <img alt="Streamlit" src="https://img.shields.io/badge/frontend-Streamlit-FF4B4B">
  <img alt="FastAPI" src="https://img.shields.io/badge/backend-FastAPI-009688">
  <img alt="Docker" src="https://img.shields.io/badge/deploy-Docker%20Compose-2496ED">
  <a href="../../LICENSE"><img alt="License" src="https://img.shields.io/badge/license-Apache%202.0-blue.svg"></a>
</p>

<p align="center">
  <strong>Language:</strong>
  <a href="../../README.md">English</a> |
  <b>🇷🇺 Русский</b>
</p>

Инструмент из двух Python-сервисов для подготовки обучающих данных для OCR: **Streamlit**-приложение для ручной разметки пар изображение→текст и **FastAPI**-бэкенд, который авторазмечает пачку документов, прогоняя три OCR-движка параллельно и голосуя за результат.

> Локальный однопользовательский инструмент — без аутентификации, без мультитенантного деплоя. Эксплуатационный охват описан в [`backend/README.md`](backend-README.md) и [`docs/RUNBOOK.md`](RUNBOOK.md).

## Возможности

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

**🌐 Локализованный UI**
- Строки интерфейса локализованы (RU/EN); язык переключается в любой момент кнопками-флажками вверху страницы

## Быстрый старт

**Docker Compose (рекомендуется)** — оба сервиса как независимые контейнеры:
```bash
docker compose up --build
```
Frontend: http://localhost:8501 · Backend: http://localhost:8756
Рабочие данные кладите в `./data` на хосте — он монтируется в `/data` внутри обоих контейнеров; в UI указывайте пути вида `/data/ваша-папка`. Подробности: [`docs/docker.md`](docker.md).

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

## Структура репозитория

```
frontend/            Streamlit-приложение разметки
  app.py                роутер режимов (стартовый экран → авторазметка/ручная)
  src/                   models, backup, annotations, image ops, hotkeys, i18n, ui/
  tests/
backend/              FastAPI-сервис OCR-консенсуса
  main.py, jobs.py, pipeline.py, detector.py, recognizers.py, consensus.py, ...
  tests/
docs/                 архитектура, Docker, тесты, runbook — см. ниже
  ru/                   русский перевод всего из docs/, backend/README.md и этого README
```

`predict.py`/`predict.ipynb` (офлайн-скрипт генерации данных, упоминается в схеме именования кропов в `backend/README.md`) не входят в этот репозиторий — намеренно в `.gitignore`, так как тянут более тяжёлый, нигде не зафиксированный набор зависимостей и хардкодят локальные пути к моделям.

## Документация

| Документ | Содержит |
|---|---|
| [`docs/architecture.md`](architecture.md) | Карта модулей, форматы данных на диске, известные хрупкие места (фронтенд) |
| [`backend/README.md`](backend-README.md) | Полный справочник backend API, обработка PDF, проверка готовности моделей |
| [`docs/docker.md`](docker.md) | Настройка Docker Compose, volume'ы, сборка/запуск по отдельности |
| [`docs/testing.md`](testing.md) | Что покрыто юнит-тестами, а что нет, и почему; конфиг линтера |
| [`docs/RUNBOOK.md`](RUNBOOK.md) | Процедура деплоя/передеплоя, health-check'и, типичные проблемы, откат |

Английский оригинал каждого документа — по тому же имени файла в `docs/` (или в корне/`backend/` для README), со ссылкой на этот перевод сверху.

## Разработка

```bash
pip install -r requirements-dev.txt   # pytest, ruff
pytest                                 # frontend/tests/ + backend/tests/
ruff check . && ruff format .
```

CI в репозитории не настроен; строгой конвенции коммитов нет (неформально используются префиксы `feat:`/`fix:`); одна ветка `main`, прямые коммиты, без PR-флоу.

## Лицензия

[Apache License 2.0](../../LICENSE).
