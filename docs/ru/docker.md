# Docker

<p align="center">
  <strong>Language:</strong>
  <a href="../docker.md">English</a> |
  <b>🇷🇺 Русский</b>
</p>

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

## VLM-режим — опциональные companion-сервисы

Путь авторазметки `mode="vlm"` (см. `backend/README.md`) требует внешних
сервисов моделей. Они объявлены в `docker-compose.yml` под **профилями**,
поэтому `docker compose up` их **не** поднимает по умолчанию.

```bash
# CPU-движки (Ollama: glm-ocr + PaddleOCR-VL, llama-server: HunyuanOCR)
docker compose --profile vlm-cpu up -d

# + GPU-движки (vLLM: dots.ocr + Unlimited-OCR; нужен nvidia-container-toolkit)
docker compose --profile vlm-cpu --profile vlm-gpu up -d
```

либо скрипты-обёртки (печатают значения `*_ENDPOINT` и делают самопроверку
`GET /models/status`):

```bash
./scripts/vlm/setup.sh --cpu            # Linux / macOS / WSL
./scripts/vlm/setup.sh --gpu
```
```powershell
.\scripts\vlm\setup.ps1 -Cpu            # Windows
.\scripts\vlm\setup.ps1 -Gpu
```

| Сервис | Профиль | Порт | Обслуживает |
|---|---|---|---|
| `ollama` + `ollama-pull` | `vlm-cpu` | 11434 | `glm_ocr`, `paddleocr_vl` |
| `llama-hunyuan` | `vlm-cpu` | 8081 | `hunyuan_ocr` |
| `vllm-dots` | `vlm-gpu` | 8082 | `dots_ocr` |
| `vllm-unlimited` | `vlm-gpu` | 8083 | `unlimited_ocr` |

Сервис `backend` уже получает `GLM_OCR_ENDPOINT` / `PADDLEOCR_VL_ENDPOINT` /
`HUNYUAN_OCR_ENDPOINT` / `DOTS_OCR_ENDPOINT` / `UNLIMITED_OCR_ENDPOINT` с
указанием на эти сервисы (переопределяется через `.env` — см. `.env.example`).
Первый запуск качает многогигабайтные веса, поэтому дайте `ollama-pull` /
`llama-hunyuan` время до запуска VLM-задания. Готовность — в
`GET /models/status` (ключи `vlm_*`) или на вкладке «📦 Модели» фронтенда.

Контейнер `ollama-pull` — одноразовый init (`restart: "no"`), завершается
после `ollama pull`.

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
  PyInstaller-обвязку (`frontend/wrapper.py`, `frontend/pyinst_command.txt`,
  `frontend/build_exe.py`, `frontend/requirements-build.txt`) — они не
  участвуют в запуске приложения.
