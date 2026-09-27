#!/usr/bin/env bash
# Поднимает llama.cpp для VLM-режима (Linux / macOS / WSL). Один движок на все
# 5 моделей: llama-server в router-режиме, в памяти не больше одной модели.
#
#   ./scripts/vlm/setup.sh --cpu     # (по умолчанию) docker compose --profile vlm-cpu
#   ./scripts/vlm/setup.sh --gpu     # docker compose --profile vlm-gpu (нужен nvidia-container-toolkit)
#   ./scripts/vlm/setup.sh --native  # без docker: скачать GGUF в .vlm/ и запустить llama-server
#   ./scripts/vlm/setup.sh --cpu --backend-url http://localhost:8756
#
# VLM_MODELS=glm-ocr,dots-ocr — скачать только часть моделей (имена — из scripts/vlm/models.ini).
# В конце дергает GET {backend}/models/status для самопроверки.
set -euo pipefail

MODE="cpu"
BACKEND_URL="http://localhost:8756"
while [ $# -gt 0 ]; do
  case "$1" in
    --cpu) MODE="cpu" ;;
    --gpu) MODE="gpu" ;;
    --native) MODE="native" ;;
    --backend-url) BACKEND_URL="$2"; shift ;;
    *) echo "Неизвестный аргумент: $1" >&2; exit 2 ;;
  esac
  shift
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

selfcheck() {
  echo
  echo "== GET ${BACKEND_URL}/models/status =="
  curl -sf "${BACKEND_URL}/models/status" | python -m json.tool 2>/dev/null \
    || echo "(backend недоступен на ${BACKEND_URL} — запустите его и повторите проверку)"
}

run_compose() {
  local profile="$1"
  command -v docker >/dev/null || { echo "docker не найден" >&2; exit 1; }
  docker compose --profile "$profile" up -d --force-recreate
  echo "Жду загрузки моделей (init-контейнер vlm-models) — первый раз это долго..."
  docker compose logs -f vlm-models || true
  echo
  echo "# Backend в docker compose уже смотрит на llama-vlm по имени (http://llama-vlm:8080)."
  echo "# VLM_ENDPOINT в .env задавать не нужно — localhost-адрес там сломает VLM-режим."
  selfcheck
}

case "$MODE" in
  cpu) run_compose vlm-cpu ;;
  gpu)
    command -v nvidia-smi >/dev/null || echo "ВНИМАНИЕ: nvidia-smi не найден — GPU-профиль скорее всего не стартует"
    run_compose vlm-gpu
    ;;
  native)
    command -v llama-server >/dev/null || {
      echo "llama-server не найден — поставьте llama.cpp (сборка b11206 или новее)" >&2; exit 1; }
    python -c "import huggingface_hub, gguf" 2>/dev/null || {
      echo "нужны пакеты: pip install huggingface_hub==2.0.0 gguf==0.19.0" >&2; exit 1; }
    VLM_DIR="$REPO_ROOT/.vlm"
    mkdir -p "$VLM_DIR/models"
    python scripts/vlm/fetch_models.py "$VLM_DIR/models"
    # models.ini ссылается на /models (путь в контейнере) — подставляем локальную папку.
    sed "s#= /models/#= $VLM_DIR/models/#" scripts/vlm/models.ini > "$VLM_DIR/models.ini"
    echo "Запускаю llama-server (router) в фоне на :8080..."
    nohup llama-server --models-preset "$VLM_DIR/models.ini" --models-max "${VLM_MODELS_MAX:-1}" \
      --host 127.0.0.1 --port 8080 > "$VLM_DIR/llama-server.log" 2>&1 &
    echo "  лог: $VLM_DIR/llama-server.log"
    echo
    echo "# Нативный backend (uvicorn на хосте): добавьте в его окружение"
    echo "export VLM_ENDPOINT=http://localhost:8080"
    selfcheck
    ;;
esac
