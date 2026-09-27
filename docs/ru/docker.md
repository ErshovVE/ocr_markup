# Docker

<p align="center">
  <strong>Language:</strong>
  <a href="../docker.md">English</a> |
  <b>🇷🇺 Русский</b>
</p>

Два сервиса, каждый со своим Dockerfile. Фронтенд ходит в бэкенд по
compose-сети (`CONSENSUS_BACKEND_URL=http://backend:8756`); опциональные
серверы VLM-моделей описаны ниже:

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

Все published-порты биндятся на `127.0.0.1` (см. комментарий в начале
`docker-compose.yml`): у бэкенда нет аутентификации, а фронтенд работает с
выключенной XSRF-защитой — из LAN они недоступны, только с этой машины.

Оба сервиса монтируют `./data` (создайте эту папку на хосте и положите туда
рабочую директорию с изображениями/разметкой) в `/data` контейнера — это
единственный способ передать реальные файлы внутрь контейнера, так как
приложения не имеют доступа к остальной файловой системе хоста. Бэкенд также
получает `OCR_DATA_ROOT=/data`, поэтому `POST /run` отклоняет `input_dir`/
`output_dir` вне `/data`.

`backend` дополнительно использует именованные volume'ы
`paddleocr-models`/`surya-models`, чтобы модели PaddleOCR/SuryaOCR скачивались
один раз и переживали пересоздание контейнера.

## VLM-режим — опциональные companion-сервисы

Режиму авторазметки `mode="vlm"` (см. `backend/README.md`) нужен сервер
моделей. Это **один движок на все пять моделей — llama.cpp `llama-server`** в
router-режиме; он объявлен в `docker-compose.yml` под **профилями**, поэтому
`docker compose up` по умолчанию его **не** поднимает. Выбирайте **один**
профиль (у них общий порт и имя `llama-vlm`):

```bash
docker compose --profile vlm-cpu up -d      # CPU (llama.cpp:server)
docker compose --profile vlm-gpu up -d      # GPU (llama.cpp:server-cuda; нужен nvidia-container-toolkit)
```

или скрипты-обёртки (заодно проверяют `GET /models/status`):

```bash
./scripts/vlm/setup.sh --cpu            # Linux / macOS / WSL
./scripts/vlm/setup.sh --gpu
./scripts/vlm/setup.sh --native         # без Docker: GGUF в .vlm/ + локальный llama-server
```
```powershell
.\scripts\vlm\setup.ps1 -Cpu            # Windows
.\scripts\vlm\setup.ps1 -Gpu
.\scripts\vlm\setup.ps1 -Native
```

| Сервис | Профиль | Порт | Что делает |
|---|---|---|---|
| `vlm-models` | `vlm-cpu`, `vlm-gpu` | — | одноразовый init: качает GGUF в volume `vlm-models` (коммиты HF запинены, `scripts/vlm/fetch_models.py`) и патчит mmproj PaddleOCR-VL для `Spotting:` |
| `llama-vlm` | `vlm-cpu` | 8080 | `llama-server --models-preset scripts/vlm/models.ini --models-max 1` |
| `llama-vlm-gpu` | `vlm-gpu` | 8080 | то же на CUDA-сборке, сетевой alias `llama-vlm` |

- Сервис `backend` уже получает `VLM_ENDPOINT=http://llama-vlm:8080`; не кладите
  в `.env` значение с `localhost` (см. `.env.example`).
- **В памяти не больше одной модели** (`--models-max 1`, `VLM_MODELS_MAX`): модель
  грузится при первом запросе к ней и вытесняет предыдущую. Backend обходит
  папку модель за моделью, поэтому VLM-задание меняет модель всего
  `len(vlm_engines)` раз.
- `VLM_MODELS=glm-ocr,dots-ocr` — скачать только часть моделей (имена пресетов из
  `scripts/vlm/models.ini`); остальные в `/models/status` будут `error`.
- Первый запуск качает несколько ГБ (веса Q8_0). `llama-vlm` стартует только
  после завершения `vlm-models` (`docker compose logs -f vlm-models`). Готовность —
  в `GET /models/status` (ключи `vlm_*`) или на вкладке «📦 Модели» фронтенда.
- GPU: номер карты — `VLM_GPU` (по умолчанию 0).

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

- Published-порты биндятся только на `127.0.0.1` (см. выше). Если поменяете это
  в `docker-compose.yml`, вы откроете всей сети бэкенд без аутентификации и
  Streamlit с выключенной XSRF — не делайте так без крайней необходимости.
- Backend — это спайк без аутентификации, который принимает произвольные
  `input_dir`/`output_dir` в теле запроса (см. `backend/README.md`).
  `OCR_DATA_ROOT=/data` (задан в `docker-compose.yml`) ограничивает их
  смонтированным volume'ом; не ограничивайте секцию `volumes` продакшн-данными
  без необходимости.
- Backend-образ тяжёлый (PaddleOCR + SuryaOCR + системный Tesseract) — первая
  сборка и первый запуск (скачивание ML-моделей) могут занять продолжительное
  время.
- Сервер VLM-моделей запинен: образ llama.cpp — по номеру сборки
  (`server-b11206`), GGUF — по коммиту Hugging Face. llama.cpp не исполняет код
  из репозиториев моделей. GGUF Unlimited-OCR — сборка сообщества (другой нет).
- Frontend-образ не включает `predict.py`/`predict.ipynb` и
  PyInstaller-обвязку (`frontend/wrapper.py`, `frontend/build_exe.py`,
  `frontend/requirements-build.txt`) — они не участвуют в запуске приложения.
