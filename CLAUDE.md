# Project Instructions

## Tech Stack
- Two independent Python services, each with its own dependency set: `frontend/` (Streamlit data-labeling app, Pillow for image handling) and `backend/` (FastAPI OCR-consensus spike, PaddleOCR/SuryaOCR/Tesseract)
- No package manifest beyond `frontend/requirements.txt` (streamlit==1.36.0, Pillow==10.4.0, requests==2.32.3) and `backend/requirements.txt`; no lockfile, no venv config committed
- Frontend packaged to a standalone .exe via PyInstaller (`frontend/wrapper.py` + `frontend/pyinst_command.txt`)
- `predict.py` / `predict.ipynb` (repo root) are separate offline OCR-labeling-data generation scripts with a heavier, unlisted dependency set (`opencv-python`, `surya-ocr`, `tqdm`, and a private `ocr_library` package) and hardcoded local model paths — they are not part of either service and not installable from either `requirements.txt` alone

## Code Style
- `frontend/src/` package holds all frontend logic (models, backup, annotations, image ops, hotkeys, UI rendering); `frontend/app.py` is a thin entry point that wires session-state init + `frontend/src/` calls together — see `docs/architecture.md` for the module map
- Russian-language UI strings, comments, and docstrings throughout — keep new code consistent with this
- Heavy use of `st.session_state` as the primary state container in the frontend (no external state management)
- `frontend/app.py` is the sole frontend entry point; `backend/main.py` is the FastAPI entry point
- No type annotations modernization (`Dict`/`List`/`Optional` from `typing`, not `dict`/`list`/`X | None`) and no `frozen=True` on dataclasses — preserved intentionally, see `docs/architecture.md`

## Testing
- `pytest` covers `frontend/src/` (models, backup, annotations — in `frontend/tests/`) and `backend/consensus.py` (in `backend/tests/`); no CI config present in this repo
- `backend/detector.py`/`backend/recognizers.py` are not unit-tested (lazily import heavy ML deps requiring real models/system Tesseract) — see `docs/testing.md`
- Manual verification still required for the Streamlit UI flow itself: run the app and click through the labeling flow

## Build & Run
- Dev (frontend): `cd frontend && streamlit run app.py --server.enableXsrfProtection=false`
- Dev (backend, run from repo root — `backend/main.py` uses absolute `backend.*` imports): `uvicorn backend.main:app --reload` — see `backend/README.md`
- Install deps: `pip install -r frontend/requirements.txt` and/or `pip install -r backend/requirements.txt`; install dev deps (pytest, ruff, shared across both): `pip install -r requirements-dev.txt`
- Docker: `docker compose up --build` runs the Streamlit frontend and the `backend/` consensus spike as separate containers — see `docs/docker.md`
- Build standalone frontend exe: see `frontend/pyinst_command.txt` (PyInstaller, run from `frontend/`, bundles `app.py` via `wrapper.py`)
- Lint/format: `ruff check .` / `ruff format .` (config in `pyproject.toml`, applies repo-wide) — see `docs/testing.md`
- Tests: `pytest` from the repo root runs both `frontend/tests/` and `backend/tests/` (configured via `testpaths` in `pyproject.toml`)

## Project Structure
- `frontend/` — Streamlit labeling app
  - `app.py` — sole entry point: page config, CSS, session-state init, file upload/working-dir wiring, calls into `src/`
  - `src/models.py` — `ImageRecord` dataclass
  - `src/backup.py` — `BackupManager`: create/rotate/restore backups
  - `src/annotations.py` — `AnnotationManager` (load/save/delete annotations, status cache) + `save_as_handwritten`
  - `src/image_ops.py` — `load_and_resize_image` (cached) + `rotate_image` (clears that cache) — see `docs/architecture.md` for the fragile coupling between them
  - `src/hotkeys.py` — `register_hotkeys`, JS ←/→ handler matched to literal button text in `src/ui/editor_view.py`
  - `src/ui/list_view.py` — `render_image_list`: filtered, paginated image list
  - `src/ui/editor_view.py` — `render_image_editor`: text edit, delete, rotate, nav
  - `src/ui/sidebar.py` — `render_sidebar`: stats, save-all, backup list/restore
  - `src/ui/consensus_view.py` — `render_consensus_section`: import OCR-consensus results produced by `backend/`
  - `wrapper.py` — PyInstaller entry point that launches Streamlit headless from a bundled exe
  - `pyinst_command.txt` — the exact PyInstaller build command
  - `tests/` — pytest suite for `src/`
- `backend/` — FastAPI OCR-consensus spike (PaddleOCR/SuryaOCR/Tesseract); see `backend/README.md` for the API and module map
  - `tests/` — pytest suite for `backend/consensus.py`
- `docs/architecture.md` — module map, on-disk data formats (`rec.txt`, `status_cache.txt`, `handwritten.txt`, `.backups/metadata.json`), and known fragile couplings
- `docs/docker.md` — the two-container Docker setup
- `docs/testing.md` — lint/test tooling
- `predict.py` / `predict.ipynb` — standalone scripts to auto-generate OCR training crops + label candidates from PDFs/images using an external `ocr_library`, `surya`, and ONNX models (hardcoded absolute paths, not portable as-is)
- Data model: see `docs/architecture.md` for full detail on `rec.txt`, `status_cache.txt`, `handwritten.txt`, and `.backups/metadata.json`

## Conventions
- No enforced commit message convention (recent history mixes `fix:`/`feat:` prefixes informally)
- No PR workflow — single `main` branch, direct commits
- Error handling: broad `try/except` around file I/O with `st.error`/`st.warning` surfaced directly in the UI
