# OCR Markup Tool

Это приложение на Python с использованием Streamlit для разметки данных для моделей распознавания символов (OCR).

## Возможности:

- Выбор рабочей папки с изображениями.
- Загрузка/создание файла `rec.txt` для хранения разметки.
- Отображение списка изображений и выбранного изображения.
- Редактирование текста, ассоциированного с изображением.
- Навигация по изображениям.
- Сохранение размеченных данных в `rec_gt.txt`.

## Установка и запуск:

1. Клонируйте репозиторий.
2. Установите зависимости: `pip install -r frontend/requirements.txt`.
3. Запустите приложение из папки `frontend/`: `streamlit run app.py --server.enableXsrfProtection=false`.

## Структура репозитория

- `frontend/` — Streamlit-приложение разметки (`app.py`, `src/`)
- `backend/` — FastAPI-спайк OCR-консенсуса (`backend/README.md`)

Подробнее — в [docs/architecture.md](docs/architecture.md).

## Docker

Приложение и backend-спайк консенсуса можно запустить в контейнерах:
`docker compose up --build`. Подробности — в [docs/docker.md](docs/docker.md).

## Разработка

- Тесты: `pytest` (см. [docs/testing.md](docs/testing.md))
- Линтер: `ruff check .` / `ruff format .`

