<!-- Generated: 2026-08-21 | Files scanned: 4 | Token estimate: ~400 -->

# Data

No database. All persistence is flat files on disk, shared by convention between frontend and backend. Full detail in `docs/architecture.md` (repo root docs) — this is the token-lean index.

## Frontend-owned files (per labeling working dir)
- `rec.txt` / uploaded `.txt` — tab-separated `relative_path\tannotation`, one row per image
- `status_cache.txt` — marked filenames, one per line; path is `base_dir/<first_path_segment>/status_cache.txt`
- `handwritten.txt` — append-only; dedup by exact line match
- `.backups/metadata.json` — JSON `{"backups": [...]}`, rotated to 5 entries (`src/backup.py::BackupManager`)

## Backend-owned files (per OCR-consensus job output dir)
- `good.txt` — consensus-passed rows, overwritten each pipeline run
- `needs_review.txt` — below-threshold rows, overwritten each pipeline run
- `crops/{N // 10000}/image_{N:05d}.webp` — sequential-id crop images (`backend/config.py::CROPS_PER_FOLDER`), predict.py's old convention, not uuid4; never overwritten — a rerun on the same output_dir resumes N from the max found on disk (`backend/pipeline.py::_resume_img_count`)
- `debug.jsonl` — one JSON line per recognized crop: `{crop, bucket, engine, diverged, engines: {paddle|surya|tesseract: {text, score}}}`; overwritten each run alongside good.txt/needs_review.txt; the only surviving record of per-engine texts/scores (vote() keeps only the winner) — consumed by `frontend/src/annotations.py::AnnotationManager._load_debug_file`
- `_job_status.json` — snapshot of the running/last job's status_dict (backend/jobs.py::_write_snapshot), written on every processed file and at job end; lets `GET /jobs/status_snapshot?output_dir=...` report what happened even after a backend restart, when the in-memory job registry (below) is gone

## Cross-service link
Backend output (`good.txt` + `needs_review.txt` + optional `debug.jsonl`) is the direct input to `frontend/src/ui/generation_view.py::_build_manager_from_output`, which builds a frontend `AnnotationManager` reading those files. This is the only place the two services' file formats must agree.

## In-memory state (not persisted)
- `backend/jobs.py::_jobs` — job status/results, one job at a time by design; lost on backend restart **except** the last-written `_job_status.json` snapshot per output_dir (see above) — data itself (good.txt/needs_review.txt/debug.jsonl/crops) is never at risk since those are flushed to disk per line, only the *tracking* of a job's progress is memory-only
- `backend/models_status.py` — model-readiness state, lost on backend restart (though re-derived from on-disk model caches on next check)

## Migration history
None — no schema, no migrations. Flat-file formats are stable by convention (see `docs/architecture.md` for exact parsing rules if changing them).
