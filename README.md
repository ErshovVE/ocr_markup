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

A two-service Python toolkit for building OCR training data: a **Streamlit** app for manually labeling image→text pairs, and a **FastAPI** backend that auto-labels a batch of documents by running three OCR engines in parallel and voting on the result.

> Local, single-user tool — no auth, no multi-tenant deployment. See [`backend/README.md`](backend/README.md) and [`docs/RUNBOOK.md`](docs/RUNBOOK.md) for the operational scope this is designed for.

## Features

**✍️ Manual labeling**
- Load a working directory + a tab-separated `path\ttext` annotation file
- Paginated, filterable image list (all / unmarked / marked / **disputed** — see below)
- Edit annotation text, rotate, delete (with automatic backup), mark as handwritten
- Keyboard navigation (←/→), autosave every 10 edits + manual save
- Backup history with one-click restore

**🤖 Auto-labeling (OCR consensus)**
- Runs **PaddleOCR + SuryaOCR + Tesseract** on every detected text line and votes on the result (majority vote → preferred-engine tiebreak → best score)
- Selectable line-detection engine, adjustable confidence threshold
- Direct PDF text-layer extraction — skips OCR entirely when a PDF already has one
- Live progress tracker while a job runs, with cooperative cancellation
- Resilient to a hung engine call: a stuck OCR call can't strand future calls, it just times out and the job keeps going
- Per-file/line errors are visible in the UI, not just backend logs
- Job status survives a backend restart (disk snapshot), even though the in-memory tracker doesn't
- Lines where two engines disagreed are flagged **"disputed"** and can be reviewed with each engine's individual text/confidence shown side by side

**🌐 Localized UI**
- Interface strings are localized (RU/EN); switch languages any time via the flag buttons at the top of the page

## Quickstart

**Docker Compose (recommended)** — runs both services as independent containers:
```bash
docker compose up --build
```
Frontend: http://localhost:8501 · Backend: http://localhost:8756
Put your working data under `./data` on the host — it's mounted at `/data` inside both containers; enter paths like `/data/your-folder` in the UI. Details: [`docs/docker.md`](docs/docker.md).

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
  tests/
docs/                 architecture, Docker, testing, runbook — see below
  ru/                   Russian translations of everything under docs/, backend/README.md, and this README
```

`predict.py`/`predict.ipynb` (an offline data-generation script referenced in `backend/README.md`'s crop-naming scheme) are not part of this repository — deliberately gitignored, since they pull in a heavier, unlisted dependency set and hardcode local model paths.

## Documentation

| Doc | Covers |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | Module map, on-disk data formats, known fragile couplings (frontend side) |
| [`backend/README.md`](backend/README.md) | Full backend API reference, PDF handling, model-readiness checks |
| [`docs/docker.md`](docs/docker.md) | Docker Compose setup, volumes, individual `docker build`/`run` |
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
