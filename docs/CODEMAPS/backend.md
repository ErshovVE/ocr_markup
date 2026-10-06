<!-- Generated: 2026-10-06 | Files scanned: 20 py (backend) + 19 tests | Token estimate: ~1150 -->

# Backend (FastAPI auto-labeling)

Entry point `backend/main.py`; run from repo root: `uvicorn backend.main:app --reload` (absolute `backend.*` imports).
No auth (single-user local service, ADR-0002); optional `OCR_DATA_ROOT` confines input/output/alphabet paths.

## Routes
POST /run                   → main.run(RunRequest) → jobs.start_job → thread: pipeline.run | pipeline_vlm.run; 409 busy; {job_id, warnings}
GET  /jobs/active           → jobs.get_active_job_id (frontend re-attaches after F5)
GET  /status/{job_id}       → jobs.status_dict (404); status running|done|error|cancelled
POST /jobs/{job_id}/cancel  → jobs.cancel_job (404/409); cooperative, checked between files/pages/lines/VLM calls
GET  /jobs/status_snapshot  → jobs.get_status_snapshot(output_dir) ← output_dir/_job_status.json (survives restart)
GET  /result/{job_id}       → jobs.get_job (404 unknown, 409 not done)
GET  /models/status         → models_status.get_status (paddle, surya, *_detector, tesseract, vlm_<id>)
POST /models/prepare        → models_status.prepare(name) (download in a thread; VLM names → 400)

RunRequest: input_dir, output_dir, score_threshold, preferred_model, lang ru|latin, latin_model_size,
  extract_pdf_text_layer, pdf_ocr_fallback, append_crop_size, normalize_labels, alphabet_file, detector_engine,
  engines + min_agree ("N of M"), mode consensus|vlm, vlm_engines + vlm_min_agree, iou_threshold,
  degrade_page_share/_seed/_min_contrast/_effects (text-layer pages only). Cross-field checks → 422.

## Key files
main.py (365) — RunRequest validation, degrade_options(), _readiness_warnings, routes
jobs.py (347) — JobState registry (_jobs, one _active_job_id), _run_job picks pipeline by mode, _write_snapshot
pipeline.py (935) — run(...) → (good, review): list_input_files → images: detect → _process_boxes (batched
  recognize_* via _run_engines_with_timeout, shared deadline) → consensus.vote → write_line/_finalize_line;
  PDFs: _process_pdf → per page _process_pdf_page (text layer + _degraded_page/choose_crop, or OCR);
  crops: _crop_paths/_resume_img_count/_save_crop (lossless WebP), _dataset_line (+w/h)
pipeline_vlm.py (462) — run(...) same callbacks: model-by-model passes, last pass resolves per page and writes;
  reuses pipeline's crop/write privates (fragile coupling, docs/architecture.md)
vlm_client.py (213) — OpenAI-compatible chat (httpx, retries, size cap, downscale_page, VLM_ENDPOINT)
vlm_adapters.py (205) — prompts + parsers: native spotting (paddleocr_vl, hunyuan_ocr) / layout (glm, dots, unlimited)
vlm_layout.py (52) — region_boxes via backend.detector for "layout" models
vlm_consensus.py (88) — group_by_iou, resolve (vlm_min_agree, no score fallback)
vlm_geometry.py (68) — rect_polygon, polygon_bbox, iou, clamped_bbox, scale_polygon (shared with crop_by_polygon)
degrade.py (430) — DegradeOptions, DEFAULT_EFFECTS, effects_errors/spec_errors, page_seed, maybe_degrade_page/
  degrade_page (Augraphy, geometry-preserving, GeometryChangedError), legible/choose_crop, preview CLI
pdf_extract.py (257) — render_page, extract_page_text_lines (TextStyle), extract_page_text_boxes, page_text_layer_usable
text_layer_quality.py (142) — word_ok/text_quality/page_is_usable (≥0.98), diagnose_layer (shared with scrapers)
labels.py (59) — LABEL_NORMALIZATION, normalize_label, load_alphabet, out_of_alphabet (shared with doc-generator)
detector.py (120) — Detector(engine paddle|surya|tesseract), lazy heavy imports
recognizers.py (155) — recognize_{paddle,paddle_latin,surya,tesseract}_batch; errors → ("", 0.0)
consensus.py (66) — vote(results, threshold, preferred_model, min_agree) → bucket, text, engine, diverged
models_status.py (228) — ModelState, disk-cache cross-check, check_tesseract, check_vlm_endpoint (cached TTL)
config.py (108) — engines, timeouts, batch size, CROPS_PER_FOLDER=10000, VLM_ENGINES/VLM_ENGINE_META, limits

## Tests (backend/tests, 19 files)
consensus, pipeline (timeout, crop paths, multiline, pdf), jobs, main (API), models_status, pdf_extract,
text_layer_quality, labels, degrade, vlm_{adapters,client,consensus,pipeline,presets}. Untested by design:
detector.py/recognizers.py/vlm_layout.py (real models). Augraphy-dependent degrade tests: importorskip.
