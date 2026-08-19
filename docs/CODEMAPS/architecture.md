<!-- Generated: 2026-08-19 | Files scanned: 28 | Token estimate: ~450 -->

# Architecture

Two independent Python services, no shared code, no DB. Connected only by HTTP (frontend → backend) and a shared flat-file convention on disk.

```
┌─────────────────────┐   POST /run             ┌──────────────────────┐
│  frontend/           │   GET  /status/{id}     │  backend/             │
│  Streamlit app       │──────────────────────▶  │  FastAPI OCR-consensus│
│  (labeling UI)       │   GET  /result/{id}     │  spike                │
│                       │   GET  /models/status   │                       │
│                       │   POST /models/prepare  │                       │
└──────────┬───────────┘  (CONSENSUS_BACKEND_URL) └──────────┬───────────┘
           │                default http://127.0.0.1:8756     │
           │                                                   │
           ▼                                                   ▼
   flat files on shared disk: rec.txt / status_cache.txt /
   handwritten.txt / .backups/metadata.json / good.txt /
   needs_review.txt / crops/*.webp
```

## Service boundaries
- **frontend/** — Streamlit labeling app. Two modes selected on a landing screen: "Авторазметка" (generation, talks to backend) and "Ручная разметка" (manual, direct file/folder labeling). See [frontend.md](frontend.md).
- **backend/** — FastAPI OCR-consensus spike. Runs PaddleOCR + SuryaOCR + Tesseract in parallel per crop, votes on the result, writes `good.txt`/`needs_review.txt`. In-memory job store only (no persistence across restart). See [backend.md](backend.md).

## Data flow (generation mode, the main cross-service path)
1. User submits `input_dir`/`output_dir`/`lang`/threshold in `generation_view.py` → `POST /run`.
2. `backend/jobs.py` spawns a daemon thread running `backend/pipeline.py`.
3. Pipeline: glob images → `Detector.detect` (PaddleOCR TextDetection) → crop → recognize via 3 engines → `consensus.vote` → append to `good.txt` or `needs_review.txt`, write crop to `output_dir/crops/*.webp`.
4. Frontend polls `GET /status/{job_id}` until `done`.
5. User clicks "Перейти к разметке результатов" → `_build_manager_from_output(output_dir)` builds an `AnnotationManager` from `good.txt`/`needs_review.txt` → session switches to manual mode with that manager already populated.

## No database
All state is flat files. See [data.md](data.md) for exact formats and `docs/architecture.md` (repo root docs) for the original detailed writeup.

## Deployment
`docker compose up --build` runs frontend and backend as two independent containers (no inter-container network dependency beyond the HTTP call above). See `docs/docker.md`. Frontend additionally ships as a standalone .exe via PyInstaller (`frontend/wrapper.py`).
