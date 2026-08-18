# Project Instructions

## Tech Stack
- Python + Streamlit (single-page data-labeling app), Pillow for image handling
- No package manifest beyond `requirements.txt` (streamlit==1.36.0, Pillow==10.4.0); no lockfile, no venv config committed
- Packaged to a standalone .exe via PyInstaller (`wrapper.py` + `pyinst_command.txt`)
- `predict.py` / `predict.ipynb` are separate offline OCR-labeling-data generation scripts with a heavier, unlisted dependency set (`opencv-python`, `surya-ocr`, `tqdm`, and a private `ocr_library` package) and hardcoded local model paths — they are not part of the Streamlit app and not installable from `requirements.txt` alone

## Code Style
- `src/` package holds all logic (models, backup, annotations, image ops, hotkeys, UI rendering); `app1.py` is a thin entry point that wires session-state init + `src/` calls together — see `docs/architecture.md` for the module map
- Russian-language UI strings, comments, and docstrings throughout — keep new code consistent with this
- Heavy use of `st.session_state` as the primary state container (no external state management)
- `app1.py` is the sole live entry point; the old `app.py` is archived at `legacy/app.py` for reference only and is not runnable as documented
- No type annotations modernization (`Dict`/`List`/`Optional` from `typing`, not `dict`/`list`/`X | None`) and no `frozen=True` on dataclasses — preserved intentionally, see `docs/architecture.md`

## Testing
- `pytest` covers `src/` (models, backup, annotations) and `backend/consensus.py`; no CI config present in this repo
- `backend/detector.py`/`backend/recognizers.py` are not unit-tested (lazily import heavy ML deps requiring real models/system Tesseract) — see `docs/testing.md`
- Manual verification still required for the Streamlit UI flow itself: run the app and click through the labeling flow

## Build & Run
- Dev: `streamlit run app1.py --server.enableXsrfProtection=false`
- Install deps: `pip install -r requirements.txt`; install dev deps (pytest, ruff): `pip install -r requirements-dev.txt`
- Docker: `docker compose up --build` runs the Streamlit frontend and the `backend/` consensus spike as separate containers — see `docs/docker.md`
- Build standalone exe: see `pyinst_command.txt` (PyInstaller, bundles `app.py` via `wrapper.py`) — **stale**: `wrapper.py`/`pyinst_command.txt` still reference the now-archived `app.py` path, not `app1.py`/`legacy/app.py`; needs fixing before the next `.exe` build (see `docs/architecture.md`)
- Lint/format: `ruff check .` / `ruff format .` (config in `pyproject.toml`) — see `docs/testing.md`

## Project Structure
- `app1.py` — sole Streamlit entry point: page config, CSS, session-state init, file upload/working-dir wiring, calls into `src/`
- `legacy/app.py` — archived, non-runnable-as-documented older entry point, kept for reference only
- `src/models.py` — `ImageRecord` dataclass
- `src/backup.py` — `BackupManager`: create/rotate/restore backups
- `src/annotations.py` — `AnnotationManager` (load/save/delete annotations, status cache) + `save_as_handwritten`
- `src/image_ops.py` — `load_and_resize_image` (cached) + `rotate_image` (clears that cache) — see `docs/architecture.md` for the fragile coupling between them
- `src/hotkeys.py` — `register_hotkeys`, JS ←/→ handler matched to literal button text in `src/ui/editor_view.py`
- `src/ui/list_view.py` — `render_image_list`: filtered, paginated image list
- `src/ui/editor_view.py` — `render_image_editor`: text edit, delete, rotate, nav
- `src/ui/sidebar.py` — `render_sidebar`: stats, save-all, backup list/restore
- `docs/architecture.md` — module map, on-disk data formats (`rec.txt`, `status_cache.txt`, `handwritten.txt`, `.backups/metadata.json`), and the two fragile couplings above
- `predict.py` / `predict.ipynb` — standalone scripts to auto-generate OCR training crops + label candidates from PDFs/images using an external `ocr_library`, `surya`, and ONNX models (hardcoded absolute paths, not portable as-is)
- `wrapper.py` — PyInstaller entry point that launches Streamlit headless from a bundled exe
- `pyinst_command.txt` — the exact PyInstaller build command
- Data model: see `docs/architecture.md` for full detail on `rec.txt`, `status_cache.txt`, `handwritten.txt`, and `.backups/metadata.json`

## Conventions
- No enforced commit message convention (recent history mixes `fix:`/`feat:` prefixes informally)
- No PR workflow — single `main` branch, direct commits
- Error handling: broad `try/except` around file I/O with `st.error`/`st.warning` surfaced directly in the UI
