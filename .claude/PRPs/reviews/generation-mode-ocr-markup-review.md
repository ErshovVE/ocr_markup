# Code Review: generation-mode-ocr-markup (local, uncommitted)

**Reviewed**: 2026-08-19
**Scope**: uncommitted changes in worktree `generation-mode-ocr-markup` implementing
`.claude/PRPs/plans/completed/generation-mode-ocr-markup.plan.md`
**Decision**: APPROVE with comments

## Summary
Clean, plan-conformant implementation. New backend model-status module and
endpoints correctly keep heavy ML imports lazy and follow the existing
in-memory job-state pattern; frontend split into a thin router plus
manual/generation view modules with no behavioral change to the manual flow.
One completeness gap (silently swallowed HTTP errors on the "Скачать" button)
and one minor test-isolation nit — neither blocks merge.

## Findings

### CRITICAL
None.

### HIGH
None.

### MEDIUM
- **`frontend/src/ui/generation_view.py:47-57`** — **[FIXED]** the
  `POST /models/prepare` call in the "Скачать" button handler didn't check
  `resp.raise_for_status()` (unlike every other backend call in this file and
  the old `consensus_view.py`), so a non-2xx response would silently clear
  the cache and rerun as if it succeeded. Fixed by capturing the response and
  calling `resp.raise_for_status()` before clearing the cache, matching the
  `/run` and `/status` calls above it.

### LOW
- **`backend/tests/test_models_status.py`** — **[FIXED]** tests mutated the
  shared module-level `models_status._state` dict directly without resetting
  it between tests. Added an `autouse` fixture that resets `_state` to a
  fresh two-key dict before and after every test.
- **`backend/main.py:33`** — `job_id = start_job(req.input_dir, req.output_dir, req.score_threshold, req.preferred_model)`
  is a pre-existing line that `ruff format` would wrap but `ruff check`
  doesn't flag (no `E501` in the configured ruleset); harmless, just noting
  it's not newly introduced by this change and not worth a separate fix.

## Validation Results

| Check | Result |
|---|---|
| Lint (`ruff check .`) | Pass — 0 errors |
| Format (`ruff format --check .`, touched files only) | Pass |
| Format (`ruff format --check .`, whole repo) | Pre-existing failures on 8 untouched files (confirmed via git-stash diff against the original checkout) — not introduced by this change |
| Tests (`pytest backend/`) | Pass — 11/11 (5 existing + 6 new) |
| Tests (`pytest`, full suite) | Blocked — pre-existing `streamlit`/`starlette` version mismatch in the local environment breaks collection of `frontend/tests/test_annotations.py` and `test_backup.py`; reproduces identically on the unmodified main checkout, unrelated to this change |
| Build | N/A (no compiled build step); `python -c "from backend.main import app"` imports cleanly |
| Module import laziness | Pass — `from backend.models_status import check_tesseract, get_status, prepare` does not pull `paddleocr`/`surya` into `sys.modules` |

## Files Reviewed
- `backend/main.py` — Modified (2 new endpoints)
- `backend/models_status.py` — Added
- `backend/tests/test_models_status.py` — Added
- `backend/README.md` — Modified (API docs)
- `frontend/app.py` — Modified (rewritten as thin router)
- `frontend/src/ui/manual_mode.py` — Added
- `frontend/src/ui/generation_view.py` — Added
- `frontend/src/ui/sidebar.py` — Modified (removed consensus section)
- `frontend/src/ui/consensus_view.py` — Deleted
- `docs/architecture.md` — Modified (module table)
- `CLAUDE.md` — Modified (project structure list)
