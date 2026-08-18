# Implementation Report: OCR Markup v2 — Regression Sign-off + Consensus Backend Spike (Phases 5-9)

## Summary
Wrote the Phase 5 regression checklist doc, built the full Phase 6-8 consensus
backend (`backend/`) and its `app1.py` sidebar integration (`src/ui/consensus_view.py`),
and updated the PRD's phase table and Decisions Log. By explicit scope agreement
with the maintainer at the start of this session, this pass did **not**: run the
Phase 5 click-through, install the heavy ML dependencies (paddleocr, surya-ocr,
pytesseract), run the backend against a real document batch, or perform Phase 9's
subjective evaluation. Those remain for the maintainer to complete manually.

## Assessment vs Reality

| Metric | Predicted (Plan) | Actual |
|---|---|---|
| Complexity | XL | XL — matched; code volume and file count landed close to the plan's estimate |
| Confidence | N/A (plan didn't state one) | High for code correctness against the plan's patterns; unverified for live ML behavior |
| Files Changed | ~14 | 13 (see table below) |

## Tasks Completed

| # | Task | Status | Notes |
|---|---|---|---|
| 5.1 | Write regression checklist | ✅ Complete | `.claude/PRPs/checklists/app1-regression-checklist.md` created |
| 5.2 | Execute checklist | ⬜ Not done | Requires the maintainer to run `streamlit run app1.py` and click through — out of this session's scope per agreed answer |
| 5.3 | Update PRD phase status | Partial | Marked "pending — checklist written, click-through not yet run" rather than "complete" |
| 6.1 | Scaffold backend package + requirements | ✅ Complete | `backend/__init__.py`, `backend/requirements.txt`, `backend/README.md` |
| 6.2 | Config module | ✅ Complete | `backend/config.py` |
| 6.3 | Detector module | ✅ Complete (code only) | Not run against a real PaddleOCR install |
| 6.4 | Recognizer functions (Paddle + Surya) | ✅ Complete (code only) | Written together with Tesseract (Task 7.1) since both live in one file per the plan |
| 6.5 | Consensus vote (binary, generalized in 7.2) | ✅ Complete, superseded by 7.2's version directly | Implemented the final 3-engine `vote()` from the start since it's a strict superset and the plan explicitly allows keeping it pure/testable without engine calls |
| 6.6 | Pipeline orchestration | ✅ Complete (code only) | `backend/pipeline.py` — writes crops + `good.txt`/`needs_review.txt` |
| 6.7 | Job store + background execution | ✅ Complete | `backend/jobs.py` |
| 6.8 | FastAPI app | ✅ Complete (code only) | `backend/main.py` — not started/curled live |
| 6.9 | Update PRD phase status | Partial | Marked "code-complete — not yet installed/run against a real batch" |
| 7.1 | Tesseract recognizer | ✅ Complete (code only) | In `backend/recognizers.py` |
| 7.2 | Generalize `vote()` to 3-engine majority | ✅ Complete and unit-verified | All 4 branches manually exercised, see Validation Results |
| 7.3 | Wire Tesseract + threshold/override into pipeline/API | ✅ Complete (code only) | `backend/pipeline.py`, `backend/main.py` |
| 7.4 | Update PRD phase status | Partial | Marked "code-complete", Tesseract not live-tested |
| 8.1 | Add `requests` to root requirements.txt | ✅ Complete | Only new root-`requirements.txt` line, no ML packages added |
| 8.2 | Consensus UI section | ✅ Complete (code only) | `src/ui/consensus_view.py` |
| 8.3 | Wire into sidebar | ✅ Complete | `src/ui/sidebar.py` updated |
| 8.4 | Update PRD phase status | Partial | Marked "code-complete — UI wired... not yet exercised against a running backend" |
| 9.1-9.3 | Subjective evaluation + PRD update | ⬜ Not done | Requires a real document batch and the maintainer's judgment — explicitly out of this session |

## Validation Results

| Level | Status | Notes |
|---|---|---|
| Static Analysis | ✅ Pass | `python -m py_compile` on all new/changed `.py` files — zero syntax errors |
| Unit Tests | ✅ Pass (manual, no framework) | `backend.consensus.vote()` manually exercised for all 4 branches from Task 7.2 plus 2 edge cases (missing `preferred_model`, original binary-match example) — all matched expected output |
| Build | N/A | No build step in this project (Streamlit app, no bundler) |
| Integration | ⬜ Not run | Requires installing `backend/requirements.txt` and running `uvicorn`/`streamlit` live — deferred to maintainer per agreed scope |
| Edge Cases | Partial | `vote()`'s edge cases verified (see above); folder/file-level edge cases (empty input dir, corrupt image, filename collisions on import) are covered structurally by the try/except-and-continue code but not exercised live |

## Files Changed

| File | Action | Lines |
|---|---|---|
| `.claude/PRPs/checklists/app1-regression-checklist.md` | CREATED | +100 |
| `backend/__init__.py` | CREATED | +0 |
| `backend/requirements.txt` | CREATED | +8 |
| `backend/config.py` | CREATED | +4 |
| `backend/detector.py` | CREATED | +18 |
| `backend/recognizers.py` | CREATED | +76 |
| `backend/consensus.py` | CREATED | +29 |
| `backend/pipeline.py` | CREATED | +80 |
| `backend/jobs.py` | CREATED | +67 |
| `backend/main.py` | CREATED | +37 |
| `backend/README.md` | CREATED | +38 |
| `src/ui/consensus_view.py` | CREATED | +79 |
| `src/ui/sidebar.py` | UPDATED | +3 |
| `requirements.txt` | UPDATED | +1 |
| `.claude/PRPs/prds/ocr-markup-v2.prd.md` | UPDATED | phase table + Decisions Log rows |

## Deviations from Plan

1. **Combined Task 6.5 and 7.2** — implemented the final 3-engine `Counter`-based
   `vote()` directly instead of first writing a binary 2-engine version and
   rewriting it. The plan explicitly frames 7.2 as a logic-only extension of the
   same pure function, and doing it once avoided throwaway code. No behavior
   difference vs. the plan's intent.
2. **Combined Task 6.4 and 7.1** — `recognize_paddle`, `recognize_surya`, and
   `recognize_tesseract` were all written into `backend/recognizers.py` in one
   pass rather than adding Tesseract in a separate edit, for the same reason.
3. **Did not archive the plan file to `completed/`** — per the `/prp-implement`
   template's Phase 5 step. Since Phase 5's click-through and Phase 9's
   evaluation are still outstanding (not merely "pending review" but literally
   not executed), archiving would misrepresent the plan as finished. Left it at
   `.claude/PRPs/plans/ocr-consensus-spike-phases-5-9.plan.md` and pointed the
   PRD's "PRP Plan" column there instead of a `completed/` path.
4. **PRD phase statuses use "code-complete" / "pending" language instead of
   flipping straight to `complete`** — per the plan's own success signals
   (e.g. Phase 6: "Backend runs end-to-end on a real batch"), which this
   session did not verify by design (see Scope agreement below).

## Scope Agreement (from this session's clarifying questions)
- Manual phases (5 click-through, 9 evaluation): code/checklist only, left for
  the maintainer to run.
- ML install: write code only, did not `pip install -r backend/requirements.txt`
  or run any live OCR call.

## Issues Encountered
None — no blockers hit while writing the code. All modules matched the plan's
specified patterns and mirrored the existing codebase's dataclass/error-handling
conventions without needing deviation beyond the two consolidations noted above.

## Tests Written

| Test File | Tests | Coverage |
|---|---|---|
| None (no test framework in repo, per `CLAUDE.md`) | N/A | `vote()`'s 4 branches + 2 edge cases verified via ad-hoc `python -c` calls during this session (not persisted as a test file) |

## Post-Implementation Code Review Fixes

A `/code-review` pass over the uncommitted diff found one HIGH correctness bug
and three lower-severity issues, all fixed before commit:

| Severity | File | Issue | Fix |
|---|---|---|---|
| HIGH | `src/ui/consensus_view.py` | Importing `good.txt` marked **every** currently-loaded record as done, not just the newly-imported ones (`get_image_list("all")` iterates the whole manager, not the just-loaded file) | Now marks only the filenames actually present in the imported file (parsed from its lines and intersected with `manager.records`) |
| MEDIUM | `backend/pipeline.py` | Re-running against the same `output_dir` silently overwrote `crop_NNNNNN.webp` files by sequential index, corrupting content behind already-imported annotations | Crop filenames now use `uuid4()` instead of a per-run sequential counter, so reruns against the same `output_dir` never collide |
| MEDIUM | `backend/main.py` | No input validation on `input_dir`/`output_dir`; a bad path silently produced an empty result | Added an `os.path.isdir(input_dir)` check returning HTTP 400 with a clear message; full auth/CORS deliberately left out per the PRD's explicit "Won't Building" localhost-spike scope decision, now called out in a code comment and `backend/README.md` |
| LOW | `backend/consensus.py` | `vote({})` raised an unhandled `ValueError` from `max()` on empty input | Added an explicit empty-dict guard returning `("needs_review", "", "")` |

All fixes re-verified with `python -m py_compile` and the same manual `vote()` branch checks as before.

## Next Steps
- [ ] Run Phase 5's checklist (`.claude/PRPs/checklists/app1-regression-checklist.md`) against a real `rec.txt` + image batch
- [ ] `pip install -r backend/requirements.txt` in a separate venv; install system `tesseract-ocr` + `rus` language pack
- [ ] Smoke-test `uvicorn backend.main:app --host 127.0.0.1 --port 8756` and `curl .../docs`
- [ ] Run the full pipeline against a real folder and spot-check `good.txt`/`needs_review.txt` + generated crops
- [ ] Run `streamlit run app1.py` and exercise the new "🤖 Консенсус OCR" sidebar section end-to-end
- [ ] Complete Phase 9's subjective evaluation and record the go/no-go decision in the PRD's Decisions Log
- [ ] Once all of the above pass, flip Phases 5-9 to `complete` in the PRD and archive the plan to `completed/`
- [ ] Code review via `/code-review`
