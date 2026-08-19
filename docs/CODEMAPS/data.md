<!-- Generated: 2026-08-19 | Files scanned: 4 | Token estimate: ~300 -->

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
- `crops/*.webp` — uuid-named crop images, never overwritten (accumulate across runs)

## Cross-service link
Backend output (`good.txt` + `needs_review.txt`) is the direct input to `frontend/src/ui/generation_view.py::_build_manager_from_output`, which builds a frontend `AnnotationManager` reading those two files. This is the only place the two services' file formats must agree.

## In-memory state (not persisted)
- `backend/jobs.py::_jobs` — job status/results, lost on backend restart, one job at a time by design
- `backend/models_status.py` — model-readiness state, lost on backend restart

## Migration history
None — no schema, no migrations. Flat-file formats are stable by convention (see `docs/architecture.md` for exact parsing rules if changing them).
