# Разработка

<p align="center">
  <strong>Language:</strong>
  <a href="../CONTRIBUTING.md">English</a> |
  <b>🇷🇺 Русский</b>
</p>

<!-- AUTO-GENERATED: раздел ниже синхронизирован с pyproject.toml, requirements*.txt и docker-compose.yml.
     Не редактировать вручную — перегенерируется через /update-docs. -->

## Требования

- Python 3.12 (см. `frontend/Dockerfile`/`backend/Dockerfile` — `python:3.12-slim`; `target-version = "py311"` в `pyproject.toml` — это только нижняя граница синтаксической совместимости для ruff, а не фактическое требование)
- Системный бинарник Tesseract с языковыми пакетами `rus`/`eng`, если работаете с `backend/` (см. `backend/README.md`)
- Docker + Docker Compose — опционально, для запуска обоих сервисов без локальной установки зависимостей (см. `docs/docker.md`)

## Установка

Frontend и backend — независимые сервисы с раздельными наборами зависимостей:

```bash
pip install -r frontend/requirements.txt   # Streamlit-приложение
pip install -r backend/requirements.txt    # FastAPI OCR-consensus спайк
pip install -r requirements-dev.txt        # pytest, ruff — общие для обоих
```

Нет ни `venv`-конфигурации, ни lock-файла в репозитории — окружение настраивается вручную.

## Доступные команды

| Команда | Назначение |
|---|---|
| `cd frontend && streamlit run app.py --server.enableXsrfProtection=false` | Запуск frontend в dev-режиме |
| `uvicorn backend.main:app --reload` (из корня репозитория) | Запуск backend в dev-режиме |
| `pytest` | Запуск всех тестов (`frontend/tests/` + `backend/tests/`, см. `testpaths` в `pyproject.toml`) |
| `pytest --cov=src --cov=backend --cov-report=term-missing` | Тесты с покрытием |
| `ruff check .` | Линтер (репозиторий целиком) |
| `ruff format .` | Форматтер |
| `docker compose up --build` | Запуск обоих сервисов в контейнерах, см. `docs/docker.md` |

<!-- END AUTO-GENERATED -->

## Тестирование

Полное описание — в `docs/testing.md`. Кратко: `backend/detector.py` и
`backend/recognizers.py` не покрыты юнит-тестами намеренно (лениво импортируют
тяжёлые ML-зависимости, требуют реальных моделей/системного Tesseract).
Manual UI-флоу Streamlit-приложения всё равно нужно проверять руками — запустить
приложение и пройти по флоу разметки.

## Стиль кода

- `ruff` — и линтер, и форматтер, конфигурация в `pyproject.toml`
- Правила `pyupgrade` (`UP`) сознательно отключены — проект хранит
  `Dict`/`List`/`Optional` из `typing`, не переписывать на `dict`/`list`/`X | None`
  (см. `CLAUDE.md`, раздел «Code Style»)
- Пользовательские строки UI идут через `frontend/src/i18n.py::t()` (RU/EN) —
  для новой строки UI нужен ключ в обоих языках, а не хардкод. Комментарии и
  docstring в коде остаются на русском — по существующему соглашению
- Без `frozen=True` на dataclass — сохраняется намеренно (см. `docs/architecture.md`)

## Чеклист перед PR

- [ ] `ruff check .` и `ruff format .` без ошибок
- [ ] `pytest` зелёный
- [ ] Если менялся формат данных (`rec.txt`, `status_cache.txt`, `handwritten.txt`,
      `.backups/metadata.json`, `good.txt`/`needs_review.txt`) — обновлён
      `docs/architecture.md` и/или `docs/CODEMAPS/data.md`
- [ ] Если менялись роуты `backend/main.py` — обновлён `backend/README.md` и/или
      `docs/CODEMAPS/backend.md`
- [ ] Если добавлена/изменена строка UI — добавлен ключ в `frontend/src/i18n.py::STRINGS`
      для `ru` и `en`
- [ ] Ручная проверка UI-флоу в Streamlit, если менялся `frontend/src/ui/`

В репозитории нет отдельного PR-шаблона и нет CI — коммитятся напрямую в `main`
(см. `CLAUDE.md`, раздел «Conventions»).
