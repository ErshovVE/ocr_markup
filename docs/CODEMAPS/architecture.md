<!-- Generated: 2026-10-06 | Files scanned: 64 py (backend 20, frontend 14, scripts 3, tests) + compose/Dockerfiles | Token estimate: ~750 -->

# Architecture

Two independent Python services, no shared code, no DB, connected by HTTP (frontend → backend) and a flat-file
convention on disk. Plus an optional third container: llama.cpp `llama-server` for the VLM mode.

```
frontend/ (Streamlit)  ──HTTP (CONSENSUS_BACKEND_URL, default http://127.0.0.1:8756)──▶  backend/ (FastAPI)
  generation tab: POST /run, GET /status/{id},                                         jobs.py (1 active job)
  POST /jobs/{id}/cancel, GET /jobs/status_snapshot,                                     ├─ mode=consensus → pipeline.py
  GET /models/status, POST /models/prepare, GET /jobs/active                            └─ mode=vlm       → pipeline_vlm.py
                                                                                             └─HTTP─▶ llama-server (VLM_ENDPOINT)
                  flat files in output_dir: good.txt / needs_review.txt / debug.jsonl /
                  degrade.jsonl / crops/{N//10000}/image_NNNNN.webp / _job_status.json
                  + labeling files: rec.txt / status_cache.txt / handwritten.txt / .backups/
```

## Service boundaries
- **frontend/** — labeling UI: "Авторазметка" (talks to backend) and "Ручная разметка" (edits label files). RU/EN UI
  via `src/i18n.py::t()`. See [frontend.md](frontend.md).
- **backend/** — auto-labeling. Two pipelines behind one job tracker. See [backend.md](backend.md).
  - **consensus**: detector → crop → 1–3 recognizers (Paddle/Surya/Tesseract, "N of M" scheme) → vote. PDF pages with a
    clean text layer skip OCR (text + boxes from the PDF), optionally degraded first (Augraphy, `degrade_*`).
  - **vlm**: whole page → one or more VLMs over HTTP → boxes + text → IoU consensus across models.
- **Library surface for doc-generator** (sibling repo, imported via `sys.path`): `pdf_extract.py` (render, text-layer
  lines with font style), `labels.py` (label normalization), `degrade.py` (page degradation).

## Data flow (consensus mode, text-layer PDF)
1. `generation_view` → `POST /run` (validated by `RunRequest`; `warnings` = models not ready yet).
2. `jobs.start_job` → daemon thread → `pipeline.run` → per PDF page `_page_uses_text_layer` (quality ≥ 0.98).
3. Text layer: `render_page` → [`degrade.maybe_degrade_page` if `degrade_page_share`] → `extract_page_text_boxes` →
   per line crop (clean or degraded via `degrade.choose_crop`) → `good.txt` (+ `degrade.jsonl`).
   No/poor layer: render → `Detector.detect` → recognizers (shared per-line timeout) → `consensus.vote` →
   good/needs_review + `debug.jsonl`. `pdf_ocr_fallback=false` skips such pages.
4. Frontend polls `/status/{id}`; after a backend restart `/jobs/status_snapshot?output_dir=` reads `_job_status.json`.
5. "Перейти к разметке" → `_build_manager_from_output` → manual mode (filter "Спорные" when lines diverged).

## Deployment
`docker compose up --build`: frontend + backend containers (`./data:/data`, model-cache volumes). GPU backend:
`-f docker-compose.gpu.yml`. VLM: profiles `vlm-cpu` / `vlm-gpu` (`vlm-models` downloads GGUF, `llama-vlm[-gpu]` serves
them; or `scripts/vlm/setup.sh`). Containers don't bind-mount source — rebuild + `--force-recreate` after code changes.
Frontend also ships as a PyInstaller .exe (`frontend/wrapper.py`). Optional `OCR_DATA_ROOT` limits `/run` paths.
