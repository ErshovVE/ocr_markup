<!-- Generated: 2026-08-21 | Files scanned: 9 | Token estimate: ~800 -->

# Backend (FastAPI OCR-consensus spike)

Entry point: `backend/main.py`. Run from repo root: `uvicorn backend.main:app --reload` (uses absolute `backend.*` imports).

## Routes
POST /run                  → main.run(RunRequest)            → jobs.start_job → pipeline.run (daemon thread); 409 if another job is already active; returns {job_id, warnings} — warnings lists engines whose model isn't "ready" yet (main._readiness_warnings), job still starts
GET  /jobs/active          → main.active_job                 → jobs.get_active_job_id (lets frontend re-attach its tracker after a page reload)
GET  /status/{job_id}      → main.status                     → jobs.status_dict(job) (404 if unknown); status: running|done|error|cancelled
POST /jobs/{job_id}/cancel → main.cancel_job_endpoint         → jobs.cancel_job (404 unknown, 409 not running); cooperative — pipeline checks a flag between files/pages/boxes, status becomes "cancelled" at the next checkpoint, nothing already written is lost
GET  /jobs/status_snapshot → main.job_status_snapshot(output_dir) → jobs.get_status_snapshot (404 if none); reads output_dir/_job_status.json — survives a backend restart, unlike /status/{job_id} whose job_id is lost with process memory
GET  /result/{job_id}      → main.result                     → jobs.get_job (404 if unknown/not "done")
GET  /models/status        → main.models_status_endpoint     → models_status.get_status
POST /models/prepare       → main.models_prepare(PrepareRequest) → models_status.prepare(name) (404→ValueError→400)

RunRequest: input_dir, output_dir, score_threshold=0.95, preferred_model, lang="ru"|"latin", latin_model_size, extract_pdf_text_layer=true, detector_engine="paddle"|"surya"|"tesseract"
PrepareRequest: model ("paddle"|"surya"|"paddle_detector"|"surya_detector")
status_dict shape (GET /status, GET /jobs/status_snapshot): status, error, docs_found, docs_processed, good_count, review_count, diverged_count, error_count, errors (list, capped at jobs.MAX_STORED_ERRORS=50; error_count itself is uncapped)

## Key files
backend/main.py (174) — route definitions, no auth (deliberate: single-user local spike); validates lang/latin_model_size/detector_engine → HTTPException(400); _readiness_warnings(req) checks models_status per engine actually needed by the request
backend/jobs.py (246) — in-memory `_jobs: Dict[str, JobState]` + `_active_job_id` (module-level, single active job enforced — start_job raises RuntimeError if one is already running); JobState adds error_count/errors (on_error callback, capped list) and cancel_event (threading.Event, checked via should_cancel callback); _write_snapshot(output_dir, state) persists status_dict(state) to output_dir/_job_status.json on every on_file_done + at job end — the only part of job state that survives a backend restart, since _jobs itself doesn't; status_dict() copies `errors` (list(...)) rather than returning the live mutable list, since it can be read from a different thread than the one appending to it
backend/pipeline.py (496) — run(input_dir, output_dir, threshold, preferred_model, lang, latin_model_size, extract_pdf_text_layer, detector_engine, on_found=, on_file_done=, on_line_done=, on_error=, should_cancel=) -> (good_count, review_count); glob images+PDFs → on_found(total) → Detector.detect (lazy get_detector() closure, engine selectable) → recognize x3 via _run_engines_with_timeout (one throwaway thread per engine call + a *shared* deadline across all 3, not a fixed pool — a genuine hang only ever loses its own one-off thread instead of permanently starving future calls of the same engine) → consensus.vote → on_line_done(bucket, diverged) per line → write_line() writes+flushes immediately (good.txt/needs_review.txt opened once, truncated per run) so already-recognized lines survive a mid-run crash; write_debug() likewise appends one JSON line per recognized line to debug.jsonl (engine texts+scores — the only place that data survives past vote(), which keeps only the winner) → crops saved via allocate_crop_path()/_save_crop to crops/{N // CROPS_PER_FOLDER}/image_{N:05d}.webp (CROPS_PER_FOLDER=10000, backend/config.py — predict.py::save_image's old convention, not the interim uuid4 scheme), N resumed from the max already on disk (_resume_img_count) so a rerun on the same output_dir can't collide with earlier crops. should_cancel() checked before each file/PDF-page/box; on_error(msg) fires on any caught exception or per-engine timeout — the only way those become visible outside the backend's own console (previously print()-only). PDFs with an extractable text layer (pdf_extract) skip OCR entirely per-document; extracted lines still fire on_line_done("good", False) but skip write_debug (vote() isn't called for them).
backend/detector.py (115) — Detector(engine="paddle"|"surya"|"tesseract", tesseract_lang="rus") — selectable line-detection engine, independent of recognition consensus; `_Engines` lazy holder (Paddle TextDetection PP-OCRv6 enable_mkldnn=False workaround / Surya DetectionPredictor); `_detect_tesseract` groups pytesseract word boxes by (block,par,line) into line boxes; all heavy imports lazy (module imports cleanly without paddleocr/surya/pytesseract installed)
backend/recognizers.py (111) — _Engines lazy holder (Paddle cyrillic/latin + Surya); recognize_paddle, recognize_paddle_latin, recognize_surya, recognize_tesseract — each already catches its own exceptions and returns ("", 0.0), so pipeline's per-engine timeout only matters for a genuine hang, not a raised error; LATIN_MODEL_SIZES=("tiny","small","medium"), DEFAULT_LATIN_MODEL_SIZE="small"
backend/consensus.py (44) — vote(results, threshold, preferred_model) -> (bucket, text, engine, diverged); majority vote among 3 engines, falls back to preferred_model if score≥threshold else best-score engine; diverged=True when 2+ engines are each individually confident (score≥threshold) but disagree on text
backend/models_status.py (129) — ModelState(status, detail) dataclass; _state keys: paddle, surya, paddle_detector, surya_detector (tesseract checked live, not stored); get_status() also cross-checks on-disk model cache (paddlex/datalab dirs) to promote "not_checked"→"ready" across backend restarts; prepare(name) spawns thread → _prepare() dispatches to recognizers._Engines or detector._Engines by name; consumed by main._readiness_warnings for the new /run warnings
backend/pdf_extract.py (105) — document_has_text_layer/page_has_text_layer/extract_page_text_boxes/render_page; direct PDF text-layer extraction via pypdfium2, used by pipeline.py to skip OCR when a PDF already has text
backend/config.py (14) — IMAGE_EXTENSIONS, PDF_EXTENSIONS, DEFAULT_SCORE_THRESHOLD=0.95, DEFAULT_HOST/PORT, ENGINE_CALL_TIMEOUT_SECONDS=30, CROPS_PER_FOLDER=10000, CROP_FILENAME_DIGITS=5

## Test coverage
backend/tests/: test_consensus.py (vote), test_pipeline_timeout.py (_run_engines_with_timeout — bounded wait, no cross-call degradation after a hang), test_crop_paths.py (_crop_paths/_resume_img_count/_save_crop), test_jobs.py (start_job/cancel_job/error accumulation/snapshot write+read, with pipeline.run monkeypatched — no real ML calls), test_models_status.py, test_pdf_extract.py. detector.py/recognizers.py themselves remain untested (lazy heavy ML imports, real models/system Tesseract required) — see `docs/testing.md`.

## Dependencies
- PaddleOCR (TextDetection PP-OCRv6 for detection, TextRecognition cyrillic_PP-OCRv5_mobile_rec + latin PP-OCRv6 for recognition — detection and recognition are separate downloadable models)
- SuryaOCR (DetectionPredictor for detection, FoundationPredictor+RecognitionPredictor for recognition — also separate downloads)
- Tesseract (system binary via pytesseract/subprocess, requires `rus`/`eng` lang packs; shared binary for both detection line-grouping and recognition)
- pypdfium2 (PDF rendering + text-layer extraction)
- FastAPI + uvicorn
