# Docker

Два независимых сервиса — они не общаются друг с другом по сети, каждый со
своим Dockerfile:

| Сервис | Dockerfile | Что внутри | Порт |
|---|---|---|---|
| `frontend` | `frontend/Dockerfile` | Streamlit-приложение `frontend/app.py` + `frontend/src/` | 8501 |
| `backend` | `backend/Dockerfile` | FastAPI-спайк консенсуса (`backend/`) — PaddleOCR + SuryaOCR + Tesseract | 8756 |

## Запуск через docker compose

```bash
docker compose up --build
```

- Frontend: http://localhost:8501
- Backend: http://localhost:8756 (см. `backend/README.md` за описанием API)

Оба сервиса монтируют `./data` (создайте эту папку на хосте и положите туда
рабочую директорию с изображениями/разметкой) в `/data` контейнера — это
единственный способ передать реальные файлы внутрь контейнера, так как
приложения не имеют доступа к остальной файловой системе хоста.

`backend` дополнительно использует именованные volume'ы
`paddleocr-models`/`surya-models`, чтобы модели PaddleOCR/SuryaOCR скачивались
один раз и переживали пересоздание контейнера.

## Сборка и запуск по отдельности

Frontend (контекст сборки — корень репозитория):

```bash
docker build -f frontend/Dockerfile -t ocr-markup-frontend .
docker run --rm -p 8501:8501 -v "$(pwd)/data:/data" ocr-markup-frontend
```

Backend (контекст сборки — корень репозитория, не `backend/`, так как образ
использует абсолютный импорт `backend.main`):

```bash
docker build -f backend/Dockerfile -t ocr-markup-backend .
docker run --rm -p 8756:8756 -v "$(pwd)/data:/data" ocr-markup-backend
```

## Важно

- Backend — это спайк без аутентификации, который принимает произвольные
  `input_dir`/`output_dir` в теле запроса (см. `backend/README.md`). Внутри
  контейнера эти пути ограничены смонтированными volume'ами, но не
  ограничивайте `docker run`/`docker compose` секцию `volumes` продакшн-данными
  без необходимости.
- Backend-образ тяжёлый (PaddleOCR + SuryaOCR + системный Tesseract) — первая
  сборка и первый запуск (скачивание ML-моделей) могут занять продолжительное
  время.
- Frontend-образ не включает `predict.py`/`predict.ipynb` и
  PyInstaller-обвязку (`frontend/wrapper.py`, `frontend/pyinst_command.txt`) —
  они не участвуют в запуске приложения (см. `CLAUDE.md`).
