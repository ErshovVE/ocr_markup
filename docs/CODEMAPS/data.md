<!-- Generated: 2026-10-06 | Files scanned: pipeline.py, pipeline_vlm.py, jobs.py, degrade.py, frontend/src/{annotations,backup,models}.py | Token estimate: ~650 -->

# Data

No database, no migrations. Everything is flat files with conventions shared by frontend and backend (full parsing
rules in `docs/architecture.md`). This is the token-lean index.

## Backend output (per job `output_dir`)
- `good.txt` / `needs_review.txt` — `crops/…/image_NNNNN.webp\ttext[\tw\th]` (`append_crop_size` adds crop width/height);
  overwritten each run, written+flushed per line. `normalize_labels` maps typographic variants (labels.py);
  `alphabet_file` sends lines with out-of-dictionary symbols to needs_review.
- `crops/{N // 10000}/image_{N:05d}.webp` — lossless WebP, N continues from the max on disk (`_resume_img_count`),
  never overwritten.
- `debug.jsonl` — per OCR/VLM line `{crop, bucket, engine, diverged, engines: {name: {text, score}}}` (VLM score = 1.0);
  not written for text-layer lines (no vote). Read by `frontend/src/annotations.py::_load_debug_file`.
- `degrade.jsonl` — only with `degrade_page_share > 0`: per line of a degraded page `{crop, source, degraded}`,
  `degraded` true (degraded crop) | false (unreadable → clean crop) | null (no effect touched the line).
- `_job_status.json` — `status_dict` snapshot written per processed file and at job end (`/jobs/status_snapshot`).

## Preview output (`python -m backend.degrade`)
`<stem>_pNNN.webp` (lossless, whole pages) + `pages.jsonl` `{file, page, image, degraded}`.

## Frontend-owned files (labeling working dir)
- `rec.txt` / uploaded `.txt` — `relative_path\tannotation[\tw\th]` (crop size kept and swapped on 90° rotation)
- `status_cache.txt` — marked filenames · `handwritten.txt` — append-only, dedup by line
- `.backups/metadata.json` — `{"backups": [...]}`, rotated to 5 (`BackupManager`)
- `ImageRecord`: relative_path, absolute_path, annotation, is_marked, diverged (from debug.jsonl), crop_size

## Cross-service link
`generation_view._build_manager_from_output(output_dir)` reads good.txt + needs_review.txt (+ debug.jsonl) into an
`AnnotationManager` — the only place both services' formats must agree.

## In-memory only
`jobs._jobs` (job registry, lost on restart except `_job_status.json`), `models_status` state (re-derived from model
caches), VLM endpoint status cache (TTL 8 s).
