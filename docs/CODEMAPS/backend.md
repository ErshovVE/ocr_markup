<!-- Generated: 2026-08-20 | Files scanned: 9 | Token estimate: ~650 -->

# Backend (FastAPI OCR-consensus spike)

Entry point: `backend/main.py`. Run from repo root: `uvicorn backend.main:app --reload` (uses absolute `backend.*` imports).

## Routes
POST /run                  → main.run(RunRequest)            → jobs.start_job → pipeline.run (daemon thread); 409 if another job is already active
GET  /jobs/active          → main.active_job                 → jobs.get_active_job_id (lets frontend re-attach its tracker after a page reload)
GET  /status/{job_id}      → main.status                     → jobs.get_job (404 if unknown)
GET  /result/{job_id}      → main.result                     → jobs.get_job (404 if unknown/not "done")
GET  /models/status        → main.models_status_endpoint     → models_status.get_status
POST /models/prepare       → main.models_prepare(PrepareRequest) → models_status.prepare(name) (404→ValueError→400)

RunRequest: input_dir, output_dir, score_threshold=0.95, preferred_model, lang="ru"|"latin", latin_model_size, extract_pdf_text_layer=true, detector_engine="paddle"|"surya"|"tesseract"
PrepareRequest: model ("paddle"|"surya"|"paddle_detector"|"surya_detector")

## Key files
backend/main.py (122) — route definitions, no auth (deliberate: single-user local spike); validates lang/latin_model_size/detector_engine → HTTPException(400); /run → HTTPException(409) if jobs.start_job rejects a concurrent run; /status also returns live progress tracker fields (docs_found/docs_processed/good_count/review_count/diverged_count)
backend/jobs.py (155) — in-memory `_jobs: Dict[str, JobState]` + `_active_job_id` (module-level, single active job enforced — start_job raises RuntimeError if one is already running); start_job/get_job/get_active_job_id/_run_job; no persistence across restart; positionally threads detector_engine (last param) through to pipeline.run; JobState mutated in place via on_found/on_file_done/on_line_done callbacks so GET /status sees live progress while status=="running" — on_line_done fires per recognized line (not per file), since a single Surya line can take up to ~20s
backend/pipeline.py (~300) — run(input_dir, output_dir, threshold, preferred_model, lang, latin_model_size, extract_pdf_text_layer, detector_engine, on_found=None, on_file_done=None, on_line_done=None) -> (good_count, review_count); glob images+PDFs → on_found(total) → Detector.detect (lazy get_detector() closure, engine selectable) → recognize x3 → consensus.vote → on_line_done(bucket, diverged) per line → write_line() writes+flushes the line to good.txt/needs_review.txt immediately (files opened once, truncated per run) so already-recognized lines survive a mid-run crash + crops/*.webp saved immediately too (uuid-named), on_file_done() per file (no args — just increments docs_processed). PDFs with an extractable text layer (pdf_extract) skip OCR entirely per-document; extracted lines still fire on_line_done("good", False).
backend/detector.py (115) — Detector(engine="paddle"|"surya"|"tesseract", tesseract_lang="rus") — selectable line-detection engine, independent of recognition consensus; `_Engines` lazy holder (Paddle TextDetection PP-OCRv6 enable_mkldnn=False workaround / Surya DetectionPredictor); `_detect_tesseract` groups pytesseract word boxes by (block,par,line) into line boxes; all heavy imports lazy (module imports cleanly without paddleocr/surya/pytesseract installed)
backend/recognizers.py (111) — _Engines lazy holder (Paddle cyrillic/latin + Surya); recognize_paddle, recognize_paddle_latin, recognize_surya, recognize_tesseract; LATIN_MODEL_SIZES=("tiny","small","medium"), DEFAULT_LATIN_MODEL_SIZE="small"
backend/consensus.py (42) — vote(results, threshold, preferred_model) -> (bucket, text, engine, diverged); majority vote among 3 engines, falls back to preferred_model if score≥threshold else best-score engine; diverged=True when 2+ engines are each individually confident (score≥threshold) but disagree on text — a stats-only signal for the progress tracker, doesn't change bucket selection. Only backend file with pytest coverage.
backend/models_status.py (120) — ModelState(status, detail) dataclass; _state keys: paddle, surya, paddle_detector, surya_detector (tesseract checked live, not stored); get_status() also cross-checks on-disk model cache (paddlex/datalab dirs) to promote "not_checked"→"ready" across backend restarts; prepare(name) spawns thread → _prepare() dispatches to recognizers._Engines or detector._Engines by name
backend/pdf_extract.py (105) — document_has_text_layer/page_has_text_layer/extract_page_text_boxes/render_page; direct PDF text-layer extraction via pypdfium2, used by pipeline.py to skip OCR when a PDF already has text
backend/config.py (5) — IMAGE_EXTENSIONS, PDF_EXTENSIONS, DEFAULT_SCORE_THRESHOLD=0.95, DEFAULT_HOST/PORT

## Not unit-tested
detector.py / recognizers.py lazily import heavy ML deps requiring real models/system Tesseract — see `docs/testing.md`.

## Dependencies
- PaddleOCR (TextDetection PP-OCRv6 for detection, TextRecognition cyrillic_PP-OCRv5_mobile_rec + latin PP-OCRv6 for recognition — detection and recognition are separate downloadable models)
- SuryaOCR (DetectionPredictor for detection, FoundationPredictor+RecognitionPredictor for recognition — also separate downloads)
- Tesseract (system binary via pytesseract/subprocess, requires `rus`/`eng` lang packs; shared binary for both detection line-grouping and recognition)
- pypdfium2 (PDF rendering + text-layer extraction)
- FastAPI + uvicorn
