# Runbook

<p align="center">
  <strong>Language:</strong>
  <b>English</b> |
  <a href="ru/RUNBOOK.md">🇷🇺 Русский</a>
</p>

A local spike with no production deployment, CI/CD, or alerting system — this
runbook covers only what actually exists: startup, health checks, and common
issues. It has no escalation/on-call procedures, since the project has none.

## Startup

### Locally (no Docker)
```bash
# Frontend
cd frontend && streamlit run app.py --server.enableXsrfProtection=false

# Backend (from repo root — absolute backend.* imports)
uvicorn backend.main:app --reload
```
Important: working directories are entered in the UI as `/data/...` — that's
the Docker-mount convention (see below); such a path doesn't exist under a
native run. Either enter the real path on the host, or run via Docker Compose
so `/data/...` resolves as usual.

### Docker Compose
```bash
docker compose up -d --build --force-recreate
```
Frontend: http://localhost:8501, backend: http://localhost:8756. Details on
mounting `./data` and the model volumes — in `docs/docker.md`.

**`--build --force-recreate` are required for any code change** — plain
`docker compose up -d` isn't enough: `docker-compose.yml` mounts only
`./data:/data` as a volume, the sources (`frontend/src`, `app.py`, all of
`backend/`) are copied into the image at build time. Without a
rebuild+recreate, the container keeps running the old code — the command
succeeds, but the changes don't apply, with no error at all.

Redeploying a single service (faster than rebuilding both):
```bash
docker compose build frontend && docker compose up -d --force-recreate --no-deps frontend
docker compose build backend  && docker compose up -d --force-recreate --no-deps backend
```

Verifying the redeploy actually took — don't rely on the command's output,
check the container's contents directly:
```bash
docker exec ocr_markup-frontend-1 grep -c "<changed_symbol>" /app/src/<file>.py
docker exec ocr_markup-backend-1  grep -c "<changed_symbol>" /app/backend/<file>.py
```

## Health check

The backend has no dedicated `/health`, but `GET /models/status` gives an
equivalent readiness signal:

```bash
curl http://127.0.0.1:8756/models/status
```
Response: `{"paddle": {...}, "surya": {...}, "tesseract": {...}}`, each one —
`{"status": "not_checked"|"checking"|"ready"|"error", "detail": ...}`.
The frontend polls this same endpoint in `generation_view.py::_render_model_status`.

Job status for a specific run: `GET /status/{job_id}` →
`{"status": "running"|"done"|"error"|"cancelled", "error": ..., "error_count": ...,
"errors": [...]}` — `errors` holds the last 50 line/file error/timeout
messages (`error_count` itself is unbounded).

Active job with an unknown `job_id`: `GET /jobs/active` →
`{"job_id": str|null}`. Status of the last run for a specific `output_dir`,
surviving a backend restart (unlike the previous two — job_id and `_jobs` are
lost with the process's memory): `GET /jobs/status_snapshot?output_dir=...`
(404 if there have been no runs yet for that folder).

## Common issues

| Symptom | Cause | What to do |
|---|---|---|
| After a redeploy the code looks unchanged | The container was recreated from a stale image — `up -d` without `--build`/`--force-recreate` doesn't pick up source changes (see "Startup" above) | Rebuild the image and recreate the container (`--build --force-recreate`), verify the container's contents with `docker exec ... grep` |
| The `/data/...` path suddenly "isn't found", the working folder seems to be gone | The app is running as a native process outside Docker Compose — `./data` on the host is intact, but `/data` doesn't exist outside the container | Check `ls ./data` on the host (the data is there), bring the containers up via `docker compose up -d` |
| Port 8501/8756 already in use, or `netstat -ano` shows two processes on the same port | In practice, an orphaned `wslrelay.exe` (Docker Desktop's WSL2 port forwarding) alongside a native process on the same port | First `tasklist /FI "PID eq <pid>"` to see what the process actually is before stopping it; then bring things up cleanly via Docker Compose |
| `models/status.tesseract == "error"` | System Tesseract isn't installed, or the language pack is missing | Install `tesseract-ocr`, check that `tesseract --list-langs` includes `rus`/`eng` (see `backend/README.md`) |
| The backend's first run is very slow | PaddleOCR/SuryaOCR download models on first use | Wait it out; on repeated runs via Docker — make sure the `paddleocr-models`/`surya-models` volumes weren't recreated. `POST /run` now returns `warnings` if a needed model isn't ready yet — the same info is visible in the UI right after starting a run |
| A job is "stuck" in `running` after a backend restart | Job status is held in the process's memory (`backend/jobs.py::_jobs`), lost on restart | `good.txt`/`needs_review.txt`/`debug.jsonl`/`crops/` themselves aren't lost (written to disk line by line) — check how the job actually ended via `GET /jobs/status_snapshot?output_dir=...` (a status snapshot that survives a restart) |
| A job needs to be stopped manually | — | `POST /jobs/{job_id}/cancel` (or the "⏹ Cancel" button in the UI). Cancellation is cooperative — checked between files/pages/lines, not instant; anything already written isn't lost |
| One engine (Paddle/Surya/Tesseract) consistently times out on specific lines, `error_count` keeps growing | Expected for a genuinely hung call — `_run_engines_with_timeout` (`backend/pipeline.py`) returns an empty result for that line and moves on; each call is a one-off thread, a hang doesn't take capacity away from future lines/jobs | Check `errors` in `/status`/`/jobs/status_snapshot` for the specific messages. If the whole job looks frozen (`docs_processed` not growing for minutes) — that's no longer an engine timeout, check `docker logs ocr_markup-backend-1` |
| The ←/→ hotkeys don't work | The JS handler matches by literal button text, easily broken by cosmetic changes | See the fragile coupling in `docs/architecture.md`; check whether the button text in `editor_view.py` changed |
| A rotated image shows a stale preview | `st.cache_data` wasn't cleared correctly | See the fragile coupling in `docs/architecture.md` (the `image_ops.py` coupling) |
| `POST /run` accepts an arbitrary path and overwrites files there | A deliberate lack of path validation — a local, single-user, unauthenticated spike | Don't run the backend on a shared/multi-user machine as-is (see `backend/README.md`) |

## Rollback

No CI/CD and no tagged releases — rollback means `git revert`/`git checkout`
of the target commit on `main`. For Docker images — rebuild and recreate the
containers after rolling back the code:
```bash
docker compose build && docker compose up -d --force-recreate
```
The named model volumes don't need rolling back (the model cache format isn't
versioned in this repo). Data under `./data` — labeled files,
`good.txt`/`needs_review.txt`/`debug.jsonl`/`crops/` — is unaffected by a code
rollback, it isn't versioned with the code. Rolling back the code for an
in-progress job doesn't make sense — cancel the job first
(`POST /jobs/{job_id}/cancel`), then roll back and redeploy.

## Monitoring and alerting

Not configured. The only signal is manually polling `/models/status`,
`/status/{job_id}` / `/jobs/status_snapshot` (see above), or the process logs
(`docker logs ocr_markup-frontend-1` / `ocr_markup-backend-1`, or the
`uvicorn`/`streamlit` stdout for a native run).
