<!-- Generated: 2026-08-21 | Files scanned: 28 | Token estimate: ~500 -->

# Architecture

Two independent Python services, no shared code, no DB. Connected only by HTTP (frontend → backend) and a shared flat-file convention on disk.

```
┌─────────────────────┐   POST /run                    ┌──────────────────────┐
│  frontend/           │   GET  /status/{id}            │  backend/             │
│  Streamlit app       │   POST /jobs/{id}/cancel        │  FastAPI OCR-consensus│
│  (labeling UI)       │──▶ GET  /jobs/status_snapshot ─▶│  spike                │
│                       │   GET  /result/{id}            │                       │
│                       │   GET  /models/status          │                       │
│                       │   POST /models/prepare         │                       │
└──────────┬───────────┘  (CONSENSUS_BACKEND_URL)        └──────────┬───────────┘
           │                default http://127.0.0.1:8756           │
           │                                                         │
           ▼                                                         ▼
   flat files on shared disk: rec.txt / status_cache.txt /
   handwritten.txt / .backups/metadata.json / good.txt /
   needs_review.txt / debug.jsonl / crops/{N//10000}/image_*.webp /
   _job_status.json
```

## Service boundaries
- **frontend/** — Streamlit labeling app. Two modes selected on a landing screen: "Авторазметка" (generation, talks to backend) and "Ручная разметка" (manual, direct file/folder labeling). See [frontend.md](frontend.md).
- **backend/** — FastAPI OCR-consensus spike. Runs PaddleOCR + SuryaOCR + Tesseract in parallel per crop, votes on the result, writes `good.txt`/`needs_review.txt`/`debug.jsonl`. Job tracking (counts, status) is in-memory only and lost on restart, but is also snapshotted to disk per output_dir (`_job_status.json`) and the labeled data itself is never memory-only. See [backend.md](backend.md).

## Data flow (generation mode, the main cross-service path)
1. User submits `input_dir`/`output_dir`/`lang`/threshold in `generation_view.py` → `POST /run` (backend replies with `warnings` if a required model isn't ready yet — job starts regardless).
2. `backend/jobs.py` spawns a daemon thread running `backend/pipeline.py`.
3. Pipeline: glob images → `Detector.detect` (selectable engine) → crop → recognize via 3 engines (each call bounded by a shared per-line timeout, not a fixed thread pool — see [backend.md](backend.md)) → `consensus.vote` → append to `good.txt` or `needs_review.txt`, append per-engine detail to `debug.jsonl`, write crop to `output_dir/crops/{N // 10000}/image_{N:05d}.webp`.
4. Frontend polls `GET /status/{job_id}` until `done`/`error`/`cancelled` (user can `POST /jobs/{id}/cancel` mid-run; if the backend restarts mid-session, `GET /jobs/status_snapshot?output_dir=...` recovers the last known status from disk).
5. User clicks "Перейти к разметке результатов" → `_build_manager_from_output(output_dir)` builds an `AnnotationManager` from `good.txt`/`needs_review.txt`/`debug.jsonl` → session switches to manual mode, defaulting to the "Спорные" (diverged) filter if any lines disagreed.

## No database
All state is flat files. See [data.md](data.md) for exact formats and `docs/architecture.md` (repo root docs) for the original detailed writeup.

## Deployment
`docker compose up --build` runs frontend and backend as two independent containers (no inter-container network dependency beyond the HTTP call above). See `docs/docker.md`. Rebuild + `--force-recreate` after any code change — the containers don't bind-mount source, only `./data:/data`. Frontend additionally ships as a standalone .exe via PyInstaller (`frontend/wrapper.py`).
