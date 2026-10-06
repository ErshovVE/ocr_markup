<!-- Generated: 2026-10-06 | Files scanned: requirements*.txt, docker-compose*.yml, Dockerfiles, scripts/vlm | Token estimate: ~550 -->

# Dependencies

## Backend (`backend/requirements.txt`, install with `uv … --override backend/overrides.txt`)
- fastapi + uvicorn[standard] + python-multipart — API (`main.py`)
- paddleocr 3.7.0 + paddlepaddle 3.3.1 — detection (PP-OCRv6) and recognition (cyrillic PP-OCRv5 mobile / latin PP-OCRv6)
- surya-ocr 0.16.0 — detection + recognition (pins resolved via overrides.txt)
- pytesseract — wraps the system Tesseract binary (`rus`/`eng` packs; not a pip dependency)
- opencv-python (+ libgl1/libglib2.0-0 in the image) — image ops; augraphy — page degradation (`degrade.py`, MIT;
  pulls numba, scikit-image, scikit-learn)
- Pillow (WebP crops) · pypdfium2 5.x (render + text layer) · httpx (VLM client)

## Frontend (`frontend/requirements.txt`)
streamlit ≥1.37 · Pillow · requests (→ backend, `CONSENSUS_BACKEND_URL`). PyInstaller for the .exe (not listed).

## Dev (`requirements-dev.txt`)
pytest, pytest-cov, ruff (config in pyproject.toml), pip-audit, pypdfium2 + numpy (pdf_extract tests). Augraphy is
deliberately not here — degrade tests that need it skip.

## External services / runtimes
- llama.cpp `llama-server` (ghcr.io/ggml-org/llama.cpp:server-b11206 / server-cuda) in router mode, one model loaded at a
  time; GGUF presets in `scripts/vlm/models.ini`, fetched by `scripts/vlm/fetch_models.py` (compose `vlm-models`).
  VLM_ENDPOINT (default http://localhost:8080; `http://llama-vlm:8080` in compose).
- Model downloads on first use: PaddleX and Surya caches (compose volumes `paddleocr-models`, `surya-models`).
- Scrapers (`scripts/scrape/`): Wikimedia Commons, stroyinf — network, no API keys.
- No cloud APIs, no auth/payment providers.

## Infra
docker compose: frontend, backend (+ `docker-compose.gpu.yml` → `backend/Dockerfile.gpu`), profiles vlm-cpu/vlm-gpu.

## Consumers of this repo
doc-generator (sibling) imports `backend/pdf_extract.py`, `backend/labels.py`, `backend/degrade.py` via sys.path
(OCR_MARKUP_PATH) — keep their public functions stable.

## Not part of either service
`predict.py` / `predict.ipynb` — offline scripts with their own unlisted deps (surya, tqdm, private `ocr_library`).
