# OCR Markup Tool

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/python-3.12-blue">
  <img alt="Streamlit" src="https://img.shields.io/badge/frontend-Streamlit-FF4B4B">
  <img alt="FastAPI" src="https://img.shields.io/badge/backend-FastAPI-009688">
  <img alt="Docker" src="https://img.shields.io/badge/deploy-Docker%20Compose-2496ED">
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-Apache%202.0-blue.svg"></a>
</p>

<p align="center">
  <strong>Language:</strong>
  <b>English</b> |
  <a href="docs/ru/README.md">🇷🇺 Русский</a>
</p>

A two-service Python toolkit for building OCR training data: a **Streamlit** app for manually labeling image→text pairs, and a **FastAPI** backend that auto-labels a batch of documents — either by running three classic OCR engines per line and voting on the result, or (**VLM mode**) by sending whole pages to OpenAI-compatible vision-language models.

> Local, single-user tool — no auth, no multi-tenant deployment. See [`backend/README.md`](backend/README.md) and [`docs/RUNBOOK.md`](docs/RUNBOOK.md) for the operational scope this is designed for.

## Features

**✍️ Manual labeling**
- Load a working directory + a tab-separated `path\ttext` annotation file
- Paginated, filterable image list (all / unmarked / marked / **disputed** — see below)
- Edit annotation text, rotate, delete (with automatic backup), mark as handwritten
- Keyboard navigation (←/→), autosave every 10 edits + manual save
- Backup history with one-click restore

**🤖 Auto-labeling (OCR consensus)**
- Runs **PaddleOCR + SuryaOCR + Tesseract** on every detected text line (batched per page, engines in parallel) and votes on the result: with 2-of-N schemes a line is "good" only if engines return character-for-character identical text
- Selectable line-detection engine, adjustable confidence threshold
- Direct PDF text-layer extraction — skips OCR entirely when a PDF already has one
- Live progress tracker while a job runs, with cooperative cancellation
- Resilient to a hung engine call: a stuck OCR call can't strand future calls, it just times out and the job keeps going
- Per-file/line errors are visible in the UI, not just backend logs
- Job status survives a backend restart (disk snapshot), even though the in-memory tracker doesn't
- Lines where two engines disagreed are flagged **"disputed"** and can be reviewed with each engine's individual text/confidence shown side by side

**🧠 Auto-labeling (VLM mode)**
- Alternative path (`mode="vlm"`): OCR vision-language models — **PaddleOCR-VL 1.6, HunyuanOCR, GLM-OCR, dots.ocr, Unlimited-OCR**. PaddleOCR-VL and HunyuanOCR return text lines with boxes for the whole page; GLM-OCR, dots.ocr and Unlimited-OCR read line crops found by the line detector
- With several models selected, lines are matched across models by box IoU and voted on (`vlm_min_agree`); same `good.txt`/`needs_review.txt`/`debug.jsonl` output as the classic path
- One engine for all models — **llama.cpp**, on CPU or GPU, one model in memory at a time; an optional Docker Compose profile (`vlm-cpu` / `vlm-gpu`) or `scripts/vlm/setup.{sh,ps1}`; readiness is shown in the "📦 Models" tab

**🌐 Localized UI**
- Interface strings are localized (RU/EN); switch languages any time via the flag buttons at the top of the page

## Quickstart

**Docker Compose (recommended)** — runs both services as independent containers:
```bash
docker compose up --build
```
Frontend: http://localhost:8501 · Backend: http://localhost:8756
Put your working data under `./data` on the host — it's mounted at `/data` inside both containers; enter paths like `/data/your-folder` in the UI. Details: [`docs/docker.md`](docs/docker.md).

**+ VLM mode (optional)** — the model server (llama.cpp, one engine for all five models) is *not* started by plain `docker compose up`; enable it with one of the profiles:
```bash
docker compose --profile vlm-cpu up -d --build   # CPU
docker compose --profile vlm-gpu up -d --build   # GPU (NVIDIA + nvidia-container-toolkit)
```
or `./scripts/vlm/setup.sh --cpu|--gpu|--native` (Linux/macOS/WSL) / `.\scripts\vlm\setup.ps1 -Cpu|-Gpu|-Native` (Windows). The first start downloads several GB of GGUF weights (`VLM_MODELS` picks a subset, see `.env.example`). Details: [`docs/docker.md#vlm-mode--optional-companion-services`](docs/docker.md#vlm-mode--optional-companion-services), API: [`backend/README.md`](backend/README.md#vlm-mode-modevlm).

**Native (no Docker)**:
```bash
# Frontend
pip install -r frontend/requirements.txt
cd frontend && streamlit run app.py --server.enableXsrfProtection=false

# Backend (from repo root — uses absolute backend.* imports)
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload
```
The backend additionally needs a system Tesseract install with the `rus`/`eng` language packs (`tesseract --list-langs`). PaddleOCR/SuryaOCR models download automatically on first use.

**Frontend-only (no backend)** — a fully working scenario: manual labeling (list/editor/sidebar, backups, hotkeys) needs no backend at all. Only the auto-labeling (OCR consensus) generation mode requires `backend/` to be running; skip it if you're bringing your own image→text pairs and just want to label them by hand.

A standalone frontend executable can be built via PyInstaller:
```bash
cd frontend
pip install -r requirements-build.txt
python build_exe.py
```
This wraps the raw command documented in `frontend/pyinst_command.txt` (bundles `app.py` via `wrapper.py`; produces a native executable for the host OS, `.exe` on Windows).

## Project structure

```
frontend/            Streamlit labeling app
  app.py                mode router (landing screen → generation/manual mode)
  src/                   models, backup, annotations, image ops, hotkeys, i18n, ui/
  tests/
backend/              FastAPI OCR-consensus service
  main.py, jobs.py, pipeline.py, detector.py, recognizers.py, consensus.py, ...
  pipeline_vlm.py, vlm_client.py, vlm_adapters.py, vlm_consensus.py, vlm_layout.py, vlm_geometry.py   (VLM mode)
  tests/
scripts/vlm/          models.ini (llama.cpp presets), fetch_models.py, setup.sh / setup.ps1
docs/                 architecture, Docker, testing, runbook — see below
  ru/                   Russian translations of everything under docs/, backend/README.md, and this README
```

`predict.py`/`predict.ipynb` (an offline data-generation script referenced in `backend/README.md`'s crop-naming scheme) are not part of this repository — deliberately gitignored, since they pull in a heavier, unlisted dependency set and hardcode local model paths.

## Documentation

| Doc | Covers |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | Module map, on-disk data formats, known fragile couplings (frontend side) |
| [`backend/README.md`](backend/README.md) | Full backend API reference (incl. VLM mode), PDF handling, model-readiness checks |
| [`docs/docker.md`](docs/docker.md) | Docker Compose setup, volumes, VLM compose profiles, individual `docker build`/`run` |
| [`docs/testing.md`](docs/testing.md) | What's unit-tested vs. not, and why; lint config |
| [`docs/RUNBOOK.md`](docs/RUNBOOK.md) | Deploy/redeploy procedure, health checks, common issues, rollback |

Each doc above has a Russian translation under `docs/ru/` (same filename), linked from the top of the English version.

## Development

```bash
pip install -r requirements-dev.txt   # pytest, ruff
pytest                                 # frontend/tests/ + backend/tests/
ruff check . && ruff format .
```

No CI is configured in this repo; no enforced commit convention beyond informal `feat:`/`fix:` prefixes; single `main` branch, direct commits, no PR workflow.

## License

[Apache License 2.0](LICENSE).
