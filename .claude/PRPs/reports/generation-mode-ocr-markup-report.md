# Implementation Report: Стартовая страница с режимами «Авторазметка» / «Ручная разметка»

## Summary
Frontend entry point split into two explicit modes selectable from a landing
screen: **Авторазметка** (model status for Paddle/Surya/Tesseract + OCR-consensus
run controls + programmatic handoff into manual mode) and **Ручная разметка**
(the pre-existing editing flow, unchanged). Backend gained two new endpoints
(`GET /models/status`, `POST /models/prepare`) backed by an in-memory model
status module mirroring the existing `jobs.py` pattern.

## Assessment vs Reality

| Metric | Predicted (Plan) | Actual |
|---|---|---|
| Complexity | Large | Large — matched estimate |
| Confidence | N/A (no PRD phase) | High — implementation matched plan almost exactly |
| Files Changed | 9 (+3 docs) | 11 (2 backend created, 2 frontend created, 5 updated, 1 deleted, 2 docs updated) |

## Tasks Completed

| # | Task | Status | Notes |
|---|---|---|---|
| 1 | `backend/models_status.py` | Complete | |
| 2 | Endpoints in `backend/main.py` | Complete | Added `from e` to satisfy ruff B904 (not specified in plan snippet) |
| 3 | `backend/tests/test_models_status.py` | Complete | 6/6 tests pass |
| 4 | `backend/README.md` | Complete | |
| 5 | `frontend/src/ui/manual_mode.py` | Complete | |
| 6 | `frontend/src/ui/generation_view.py` | Complete | |
| 7 | `frontend/src/ui/sidebar.py` | Complete | Removed consensus import/call |
| 8 | Delete `frontend/src/ui/consensus_view.py` | Complete | No remaining references |
| 9 | `frontend/app.py` — thin router | Complete | |
| 10 | Docs (`docs/architecture.md`, `CLAUDE.md`) | Complete | |

## Validation Results

| Level | Status | Notes |
|---|---|---|
| Static Analysis (`ruff check .`) | Pass | 0 errors |
| Static Analysis (`ruff format`) | Partial | Files touched by this change are formatted; 8 pre-existing files elsewhere in the repo already failed `ruff format --check` before this change (confirmed by diffing against the untouched main checkout) — not a regression, left as-is (out of scope) |
| Unit Tests | Pass | `backend/tests/` — 11/11 passed (5 pre-existing `test_consensus.py` + 6 new `test_models_status.py`) |
| Build | N/A | No compiled build step; `py_compile` on all touched files succeeds, `from backend.main import app` imports cleanly |
| Integration | Not run | Requires a live Streamlit session + manual click-through per the plan's Manual Validation checklist — not exercised in this pass (see Next Steps) |
| Edge Cases | Pass (logic-level) | Backend-unreachable and empty-output-dir paths are covered by existing `try/except`/`if not manager.records` guards mirrored from the plan; not manually exercised in a browser |

## Files Changed

| File | Action | Lines |
|---|---|---|
| `backend/models_status.py` | CREATED | +67 |
| `backend/tests/test_models_status.py` | CREATED | +44 |
| `backend/main.py` | UPDATED | +24 / -2 |
| `backend/README.md` | UPDATED | +2 |
| `frontend/src/ui/manual_mode.py` | CREATED | +65 |
| `frontend/src/ui/generation_view.py` | CREATED | +141 |
| `frontend/src/ui/consensus_view.py` | DELETED | -88 |
| `frontend/src/ui/sidebar.py` | UPDATED | +0 / -8 |
| `frontend/app.py` | UPDATED | rewritten as thin router |
| `docs/architecture.md` | UPDATED | module table refreshed |
| `CLAUDE.md` | UPDATED | Project Structure list refreshed |

## Deviations from Plan
- `backend/main.py`: added `from e` to the `raise HTTPException(400, str(e))` in
  `models_prepare` — the plan's code snippet omitted it, but `ruff check .`
  (via the `B` ruleset already enabled in `pyproject.toml`) flags bare
  re-raises inside `except` blocks. Kept behavior identical, just satisfies
  the lint gate.
- `backend/tests/test_models_status.py`: ran `ruff format` on this new file,
  which reflowed two multi-context-manager `with` statements into parenthesized
  form — purely cosmetic, no behavior change.

## Issues Encountered
- **Pre-existing, unrelated to this change**: `pytest` (full suite) fails to
  collect `frontend/tests/test_annotations.py` and `frontend/tests/test_backup.py`
  with a `streamlit`/`starlette` version-mismatch `ImportError`/`RuntimeError`
  in the local environment. Reproduced identically on the unmodified main
  checkout outside the worktree, confirming it predates this implementation
  and is an environment/dependency issue, not something introduced here.
  Worked around by running `backend/` tests directly, which are unaffected
  (they don't import `streamlit`).
- **Pre-existing, unrelated to this change**: `ruff format --check .` flags 8
  files this implementation never touched (`backend/consensus.py`,
  `backend/recognizers.py`, `frontend/src/backup.py`, `frontend/src/image_ops.py`,
  `frontend/src/ui/editor_view.py`, `frontend/src/ui/list_view.py`,
  `frontend/tests/test_annotations.py`, `frontend/wrapper.py`) — confirmed via
  a git-stash comparison that these fail identically before this change.
  Left untouched (out of scope for this plan).

## Tests Written

| Test File | Tests | Coverage |
|---|---|---|
| `backend/tests/test_models_status.py` | 6 tests | `check_tesseract` (missing binary, missing `rus` lang, ready), `_prepare` (success → ready, failure → error+detail), `prepare` (unknown model → `ValueError`) |

## Next Steps
- [ ] Manual validation per plan's checklist: `streamlit run app.py` with and
      without the backend running, verify landing screen, mode switch, model
      status panel, and the "📥 Перейти к разметке результатов" handoff into
      manual mode with real `good.txt`/`needs_review.txt` output.
- [ ] Code review via `/code-review`
- [ ] Create PR via `/prp-pr`
