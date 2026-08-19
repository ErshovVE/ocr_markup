<!-- Generated: 2026-08-19 | Files scanned: 8 | Token estimate: ~500 -->

# Backend (FastAPI OCR-consensus spike)

Entry point: `backend/main.py`. Run from repo root: `uvicorn backend.main:app --reload` (uses absolute `backend.*` imports).

## Routes
POST /run                  → main.run(RunRequest)            → jobs.start_job → pipeline.run (daemon thread)
GET  /status/{job_id}      → main.status                     → jobs.get_job (404 if unknown)
GET  /result/{job_id}      → main.result                     → jobs.get_job (404 if unknown/not "done")
GET  /models/status        → main.models_status_endpoint     → models_status.get_status
POST /models/prepare       → main.models_prepare(PrepareRequest) → models_status.prepare(name) (404→ValueError→400)

RunRequest: input_dir, output_dir, score_threshold=0.95, preferred_model, lang="ru"|"latin", latin_model_size
PrepareRequest: model

## Key files
backend/main.py (89) — route definitions, no auth (deliberate: single-user local spike)
backend/jobs.py (84) — in-memory `_jobs: Dict[str, JobState]`; start_job/get_job/_run_job; one job at a time, no persistence across restart
backend/pipeline.py (104) — run(input_dir, output_dir, threshold, preferred_model, lang, latin_model_size) -> (good_count, review_count); glob → Detector.detect → recognize x3 → consensus.vote → good.txt/needs_review.txt (overwritten per run) + crops/*.webp (uuid-named)
backend/detector.py (16) — Detector wraps PaddleOCR TextDetection (PP-OCRv6), lazy import, enable_mkldnn=False (workaround for a paddlepaddle build crash)
backend/recognizers.py (93) — _Engines lazy holder (Paddle cyrillic/latin + Surya); recognize_paddle, recognize_paddle_latin, recognize_surya, recognize_tesseract; LATIN_MODEL_SIZES=("tiny","small","medium"), DEFAULT_LATIN_MODEL_SIZE="small"
backend/consensus.py (34) — vote(results, threshold, preferred_model) -> (bucket, text, engine); majority vote among 3 engines, falls back to preferred_model if score≥threshold else best-score engine. Only backend file with pytest coverage.
backend/models_status.py (69) — ModelState(status, detail) dataclass; get_status(), prepare(name) (spawns thread), check_tesseract() via subprocess/shutil.which
backend/config.py (4) — IMAGE_EXTENSIONS, DEFAULT_SCORE_THRESHOLD=0.95, DEFAULT_HOST/PORT

## Not unit-tested
detector.py / recognizers.py lazily import heavy ML deps requiring real models/system Tesseract — see `docs/testing.md`.

## Dependencies
- PaddleOCR (TextDetection PP-OCRv6, TextRecognition cyrillic_PP-OCRv5_mobile_rec + latin PP-OCRv6)
- SuryaOCR
- Tesseract (system binary via pytesseract/subprocess, requires `rus`/`eng` lang packs)
- FastAPI + uvicorn
