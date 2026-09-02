#!/usr/bin/env bash
# Провижининг companion-сервисов VLM-режима (Linux / macOS / WSL).
#
#   ./scripts/vlm/setup.sh --cpu     # (по умолчанию) Ollama + llama-server через docker compose
#   ./scripts/vlm/setup.sh --gpu     # + vLLM для dots.ocr / Unlimited-OCR (нужен nvidia-container-toolkit)
#   ./scripts/vlm/setup.sh --native  # без docker: ollama pull + llama-server в фоне
#   ./scripts/vlm/setup.sh --cpu --backend-url http://localhost:8756
#
# В конце печатает строки `export *_ENDPOINT=...` и дергает GET {backend}/models/status.
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

print_endpoints() {
  echo
  echo "# Добавьте в окружение backend'а (или в .env):"
  echo "export GLM_OCR_ENDPOINT=${GLM_OCR_ENDPOINT:-http://localhost:11434}"
  echo "export PADDLEOCR_VL_ENDPOINT=${PADDLEOCR_VL_ENDPOINT:-http://localhost:11434}"
  echo "export HUNYUAN_OCR_ENDPOINT=${HUNYUAN_OCR_ENDPOINT:-http://localhost:8081}"
  if [ "$MODE" = "gpu" ]; then
    echo "export DOTS_OCR_ENDPOINT=${DOTS_OCR_ENDPOINT:-http://localhost:8082}"
    echo "export UNLIMITED_OCR_ENDPOINT=${UNLIMITED_OCR_ENDPOINT:-http://localhost:8083}"
  fi
}

selfcheck() {
  echo
  echo "== GET ${BACKEND_URL}/models/status =="
  curl -sf "${BACKEND_URL}/models/status" | python -m json.tool 2>/dev/null \
    || echo "(backend недоступен на ${BACKEND_URL} — запустите его и повторите проверку)"
}

case "$MODE" in
  cpu)
    command -v docker >/dev/null || { echo "docker не найден" >&2; exit 1; }
    docker compose --profile vlm-cpu up -d --force-recreate
    echo "Жду загрузки моделей Ollama (glm-ocr, PaddleOCR-VL) — первый раз это долго..."
    docker compose logs -f ollama-pull || true
    print_endpoints
    selfcheck
    ;;
  gpu)
    command -v docker >/dev/null || { echo "docker не найден" >&2; exit 1; }
    command -v nvidia-smi >/dev/null || echo "ВНИМАНИЕ: nvidia-smi не найден — GPU-профиль скорее всего не стартует"
    docker compose --profile vlm-cpu --profile vlm-gpu up -d --force-recreate
    docker compose logs -f ollama-pull || true
    print_endpoints
    selfcheck
    ;;
  native)
    command -v ollama >/dev/null || { echo "ollama не найден — поставьте https://ollama.com" >&2; exit 1; }
    ollama pull glm-ocr
    ollama pull MedAIBase/PaddleOCR-VL:0.9b
    if command -v llama-server >/dev/null; then
      echo "Запускаю llama-server (HunyuanOCR) в фоне на :8081..."
      nohup llama-server -hf ggml-org/HunyuanOCR-GGUF --host 0.0.0.0 --port 8081 -c 16384 \
        > "$REPO_ROOT/llama-hunyuan.log" 2>&1 &
      echo "  лог: $REPO_ROOT/llama-hunyuan.log"
    else
      echo "llama-server не найден — поставьте llama.cpp и запустите:"
      echo "  llama-server -hf ggml-org/HunyuanOCR-GGUF --port 8081 -c 16384"
    fi
    print_endpoints
    selfcheck
    ;;
esac
