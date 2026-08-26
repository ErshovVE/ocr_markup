# Development

<p align="center">
  <strong>Language:</strong>
  <b>English</b> |
  <a href="ru/CONTRIBUTING.md">🇷🇺 Русский</a>
</p>

<!-- AUTO-GENERATED: the section below is synced with pyproject.toml, requirements*.txt, and docker-compose.yml.
     Do not edit by hand — it's regenerated via /update-docs. NOTE: /update-docs regenerates
     Russian prose into docs/ru/CONTRIBUTING.md; re-translate this section by hand afterward
     to keep it in sync. -->

## Requirements

- Python 3.12 (see `frontend/Dockerfile`/`backend/Dockerfile` — `python:3.12-slim`; ruff's `target-version = "py311"` in `pyproject.toml` is only the linter's syntax-compatibility floor, not the actual requirement)
- A system Tesseract binary with the `rus`/`eng` language packs if you're working on `backend/` (see `backend/README.md`)
- Docker + Docker Compose — optional, for running both services without installing dependencies locally (see `docs/docker.md`)

## Installation

Frontend and backend are independent services with separate dependency sets:

```bash
pip install -r frontend/requirements.txt   # the Streamlit app
pip install -r backend/requirements.txt    # the FastAPI OCR-consensus spike
pip install -r requirements-dev.txt        # pytest, ruff — shared by both
```

No `venv` config and no lockfile in the repo — set up the environment manually.

## Available commands

| Command | Purpose |
|---|---|
| `cd frontend && streamlit run app.py --server.enableXsrfProtection=false` | Run the frontend in dev mode |
| `uvicorn backend.main:app --reload` (from the repo root) | Run the backend in dev mode |
| `pytest` | Run all tests (`frontend/tests/` + `backend/tests/`, see `testpaths` in `pyproject.toml`) |
| `pytest --cov=src --cov=backend --cov-report=term-missing` | Tests with coverage |
| `ruff check .` | Linter (whole repo) |
| `ruff format .` | Formatter |
| `docker compose up --build` | Run both services in containers, see `docs/docker.md` |

<!-- END AUTO-GENERATED -->

## Testing

Full details in `docs/testing.md`. In short: `backend/detector.py` and
`backend/recognizers.py` are deliberately not covered by unit tests (they
lazily import heavy ML dependencies, need real models/a system Tesseract).
The Streamlit app's manual UI flow still needs to be checked by hand — run
the app and click through the labeling flow.

## Code style

- `ruff` — both the linter and the formatter, configured in `pyproject.toml`
- The `pyupgrade` rules (`UP`) are deliberately disabled — the project keeps
  `Dict`/`List`/`Optional` from `typing`, don't rewrite them to
  `dict`/`list`/`X | None`
- User-facing UI strings go through `frontend/src/i18n.py::t()` (RU/EN) —
  new UI strings need a key in both languages, not a hardcoded literal. Code
  comments and docstrings stay Russian-language, per existing convention
- No `frozen=True` on dataclasses — kept intentionally (see `docs/architecture.md`)

## Pre-PR checklist

- [ ] `ruff check .` and `ruff format .` pass with no errors
- [ ] `pytest` is green
- [ ] If a data format changed (`rec.txt`, `status_cache.txt`, `handwritten.txt`,
      `.backups/metadata.json`, `good.txt`/`needs_review.txt`) — `docs/architecture.md`
      and/or `docs/CODEMAPS/data.md` is updated
- [ ] If `backend/main.py` routes changed — `backend/README.md` and/or
      `docs/CODEMAPS/backend.md` is updated
- [ ] If a UI string was added or changed — a key was added to `frontend/src/i18n.py::STRINGS`
      for both `ru` and `en`
- [ ] Manual check of the UI flow in Streamlit if `frontend/src/ui/` changed

There's no separate PR template and no CI in this repo — commits go straight
to `main`.
