<!-- Generated: 2026-08-19 | Files scanned: 6 | Token estimate: ~250 -->

# Dependencies

## Frontend (`frontend/requirements.txt`)
- streamlit==1.36.0 — UI framework, sole entry point `app.py`
- Pillow==10.4.0 — image load/resize/rotate (`src/image_ops.py`)
- requests==2.32.3 — HTTP calls to backend from `src/ui/generation_view.py` (`CONSENSUS_BACKEND_URL`, default `http://127.0.0.1:8756`)
- PyInstaller — standalone .exe packaging (`frontend/wrapper.py`, `frontend/pyinst_command.txt`), not in requirements.txt

## Backend (`backend/requirements.txt`)
- FastAPI + uvicorn — API framework, entry point `backend/main.py`
- PaddleOCR — TextDetection (PP-OCRv6) in `detector.py`; TextRecognition (cyrillic_PP-OCRv5_mobile_rec + latin PP-OCRv6) in `recognizers.py`; `enable_mkldnn=False` workaround for a paddlepaddle build crash
- SuryaOCR — recognition engine, `recognizers.py`
- Tesseract — system binary, called via pytesseract/subprocess in `recognizers.py`/`models_status.py`; requires `rus`/`eng` lang packs installed on host — not a pip dependency

## Dev/shared (`requirements-dev.txt`)
- pytest — test runner for both `frontend/tests/` and `backend/tests/` (via `testpaths` in `pyproject.toml`)
- ruff — lint/format, config in `pyproject.toml`, applies repo-wide

## External services
None (no cloud APIs, no payment/auth providers). All OCR runs locally.

## Infra
- Docker / docker-compose — two independent containers (frontend, backend), no required inter-container network beyond the HTTP call frontend→backend (`docs/docker.md`)

## Not part of either service
`predict.py` / `predict.ipynb` (repo root) — offline OCR-labeling-data generation scripts with a separate, heavier, unlisted dependency set: opencv-python, surya-ocr, tqdm, and a private `ocr_library` package; hardcoded local model paths, not installable from either `requirements.txt`.
