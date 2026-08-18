# OCR Markup v2: Modular Refactor + Multi-OCR Consensus Assist

## Problem Statement

The labeling tool has forked into two files (`app.py`, `app1.py`) that have diverged, and all active development lives in one 823-line monolith (`app1.py`) with no module boundaries, no documentation, and heavy inline coupling to `st.session_state`. The sole maintainer (also the sole user) wants to keep shipping new features to this tool but is increasingly at risk of breaking something while doing so, because there is no separation between UI rendering, file I/O, backup logic, and image ops. Separately, manual line-by-line transcription in the tool is slow, and a working offline prototype (`predict.py`) already shows that combining two OCR engines' agreement can pre-fill a meaningful chunk of "good" labels — but that logic only exists as a hardcoded, non-portable one-off script tied to a private local library and absolute Windows paths.

## Evidence

- `app.py` has had zero commits touching it beyond `1036ada`, while the last 5 repo commits are all `app1.py`-only (sidebar, hotkeys, backups, var changes) — confirms `app1.py` is the live codebase and `app.py` is abandoned in place, not actively maintained.
- `app1.py` mixes UI, state, and I/O in ~5 large functions (`render_image_list` L416-499, `render_image_editor` L502-669, `main` L672-823) with dozens of direct `st.session_state[...]` reads scattered throughout — confirmed via codebase exploration, not assumption.
- `predict.py` (L210-260) already implements a real two-engine (Surya + a private Paddle-style pipeline) line-detection + recognition + exact-match-agreement + confidence-threshold routing flow, proving the consensus concept works mechanically — but it depends on a private `ocr_library` package and hardcoded absolute local model paths (L147-158, L160), so none of it can run outside the author's machine today.
- Assumption — needs validation through actual use: that consensus auto-labeling meaningfully reduces manual transcription time. No baseline timing data exists yet; success will be judged subjectively during the spike (per user).

## Proposed Solution

Ship this as one version bump in two tracks. Track A (firm scope): archive `app.py` without migrating any functionality, and refactor `app1.py` into a `src/` package with a thin entry-point script, adding documentation so future features can be added without fear of breaking existing behavior. Track B (firm sub-scope, spike-gated): stand up a separate backend service that runs the classical OCR consensus pipeline (PaddleOCR as line detector, PaddleOCR + SuryaOCR + TesseractOCR as parallel recognizers, 2-of-3 agreement → auto-label, configurable score threshold and manual per-model override otherwise) against the existing `rec.txt`-style annotation format, keeping the heavy ML dependencies out of the Streamlit app and its PyInstaller exe. VLM-based recognizers (PaddleOCR-VL, Hunyuan-OCR, DeepSeek-OCR, etc.) are explicitly deferred past this version pending the outcome of the classical-engine spike.

## Key Hypothesis

We believe a classical 3-engine (PaddleOCR/SuryaOCR/TesseractOCR) detect-then-vote consensus pipeline, run as a separate backend, will reduce the manual-transcription burden enough to be worth keeping.
We'll know we're right when the sole user, after running the spike against a real batch of documents, subjectively judges it as saving noticeable eyeballing/typing time versus labeling from scratch.

## What We're NOT Building

- VLM-based recognizers (PaddleOCR-VL, Hunyuan-OCR, DeepSeek-OCR, etc.) — deferred until the classical-engine consensus spike proves out; revisit as a follow-up version.
- Migrating any `app.py`-only functionality forward — confirmed to have no unique standalone logic beyond what `app1.py` already covers; it is archived as-is, not ported.
- Bundling OCR-consensus ML dependencies (PaddleOCR, Surya, Tesseract) into the Streamlit app's `requirements.txt` or PyInstaller exe — kept in a separate backend service specifically to avoid bloating/destabilizing the packaged labeling tool.
- Formal accuracy benchmarking (precision/recall against ground truth) for the consensus spike — success is judged subjectively in this version; a rigorous eval harness is explicit future work if the spike is kept.
- Multi-user/team features (concurrent editing, roles, RBAC) — current and expected user base is the maintainer alone or a 1-2 person team; not designed for scale.

## Success Metrics

| Metric | Target | How Measured |
|--------|--------|---------------|
| Refactor confidence | Maintainer can add a small new feature to the labeling app without touching unrelated modules | Subjective — first post-refactor feature addition doesn't require cross-cutting edits |
| Consensus spike usefulness | "Saves noticeable time" vs. manual labeling | Subjective — maintainer's judgment after running the spike on a real batch |
| No regressions | All existing app1.py flows (upload, edit, save, rotate, delete, backup/restore, hotkeys) still work post-refactor | Manual click-through of each flow (no test suite exists in this repo) |

## Open Questions

- [ ] What transport/interface connects the Streamlit app to the new OCR-consensus backend service (REST call, shared filesystem drop, message queue)? Needs a decision before Phase 4 implementation.
- [ ] Where does the OCR-consensus backend get PaddleOCR/Tesseract models from in a way that's portable off the author's machine (replacing the hardcoded local paths seen in `predict.py`)?
- [ ] If the classical-engine spike doesn't clearly save time, do we retire the consensus feature entirely or narrow it (e.g., single best engine, no voting)?
- [ ] Does Tesseract need to be added net-new (not present in `predict.py` today, only Surya + a private Paddle-style pipeline) — confirm licensing/install path (pytesseract + system binary) is acceptable for this environment.

---

## Users & Context

**Primary User**
- **Who**: The maintainer themself, working solo (or occasionally with one other person) to label OCR training data.
- **Current behavior**: Runs `app1.py` via Streamlit, manually transcribes/corrects line-level text for each cropped image, saves to `rec.txt`/`rec_gt.txt`, occasionally restores from `.backups/`.
- **Trigger**: Wants to keep extending the labeling tool (new features) without the growing monolith making that risky, and wants to speed up the most tedious part — manual transcription — using existing OCR models.
- **Success state**: Can drop in a new feature confidently; can optionally run a batch through OCR consensus and get a meaningful chunk of lines pre-labeled correctly with minimal review.

**Job to Be Done**
When I need to add a feature to the labeling tool or speed up transcription of a new document batch, I want to work in a codebase with clear module boundaries and (optionally) get automatic high-confidence label suggestions from multiple OCR engines, so I can extend the tool safely and label faster without sacrificing the accuracy I currently get by typing everything by hand.

**Non-Users**
Large annotation teams, external contractors, or any workflow requiring concurrent multi-user editing, review/approval pipelines, or RBAC — this stays a single-operator (or tiny team) tool.

---

## Solution Detail

### Core Capabilities (MoSCoW)

| Priority | Capability | Rationale |
|----------|------------|-----------|
| Must | Archive `app.py` (no functional migration) | Confirmed dead-in-practice; keeping it live invites confusion about which file to edit |
| Must | Split `app1.py` into a `src/` package with a thin entry-point script | Directly addresses the "add features without fear of breaking things" goal |
| Must | Write documentation covering the new module layout and data model (rec.txt/status_cache.txt/handwritten.txt formats) | Needed so the boundaries chosen during refactor stay legible later |
| Must | Manual click-through verification of every existing app1.py flow post-refactor | No test suite exists; this is the only regression safety net available |
| Must | Separate backend service running PaddleOCR (detector) + PaddleOCR/SuryaOCR/TesseractOCR (recognizers) with 2-of-3 agreement auto-labeling, configurable score threshold, and manual per-model override | Firm requirement per user; proves/disproves the consensus hypothesis without destabilizing the shipped app |
| Should | A UI surface (new tab/window) in the Streamlit app to trigger the backend and review/import its output into the existing annotation format | Needed to actually use the consensus results inside the existing labeling workflow, but can start as a manual/CLI trigger if time-constrained |
| Could | Shared constants module for image-extension allowlists (currently duplicated and inconsistent between `app1.py` and `predict.py`) | Small cleanup surfaced during exploration; not required for the core goals |
| Won't | VLM model integration (PaddleOCR-VL, Hunyuan-OCR, DeepSeek-OCR) | Explicitly deferred past this version |
| Won't | Formal precision/recall evaluation harness for consensus output | Success is subjective in this version |

### MVP Scope

Track A (refactor) ships in full — it's a firm, bounded piece of work with a clear regression-check method (manual click-through). Track B (OCR consensus) ships as a spike: a working separate backend service that produces good/needs-review label buckets from a real document batch, wired into the app via at least a manual import step, evaluated subjectively before any further investment (e.g., a real UI, VLM engines, or an eval harness).

### User Flow

Refactor: invisible to the labeling workflow itself — same UI, same click-through, just reorganized code underneath.

Consensus spike: maintainer points the backend at a folder of documents → backend detects lines (PaddleOCR) → runs recognition through all three engines → buckets lines into auto-labeled (2-of-3 agreement) vs. needs-review (disagreement, routed by score threshold or a directly-specified preferred model) → maintainer imports/reviews the auto-labeled bucket inside the existing app1.py labeling flow.

---

## Technical Approach

**Feasibility**: HIGH for Track A, MEDIUM for Track B.

**Architecture Notes**
- Track A: `app1.py`'s existing class boundaries (`BackupManager` L66-161, `AnnotationManager` L174-321, `ImageRecord` dataclass L164-171) already map cleanly to `src/backup.py`, `src/annotations.py`, `src/models.py`. UI rendering (`render_image_list` L416-499, `render_image_editor` L502-669) and the currently-inline sidebar block in `main()` (L749-819) split into `src/ui/*.py`, with `main()` becoming a thin `app1.py` that just wires session-state init + calls into `src/`.
- `BackupManager`/`AnnotationManager` call `st.error`/`st.info` directly (e.g. `AnnotationManager.delete_record` L262, `save_changes` L268/L289) — these stay as-is rather than being purified, since decoupling Streamlit calls from the "model" layer is not required to hit the stated goal (safe feature velocity) and would add scope.
- The `rotate_image` (L342) ↔ `load_and_resize_image` cache-clear coupling (L349) and the JS hotkey injection's dependency on exact button label text (`register_hotkeys` L15-63 vs. buttons in `render_image_editor`) must be preserved explicitly across the module split — call out in docs as known fragile points.
- Track B: reuses `predict.py`'s proven detect → multi-recognize → agreement-route shape (L210-260) but must strip the `ocr_library` private-package dependency and hardcoded absolute paths (L147-158, L160-165), add Tesseract as a third recognizer (net-new, not present today), generalize the 2-way exact-match check into a real 2-of-3 vote, and make score threshold + preferred-model override configurable instead of a hardcoded constant (`filter_score=0.95`, L141).
- Track B ships as an independent backend/service (per user decision) specifically so the Streamlit app's `requirements.txt` and PyInstaller exe (see `pyinst_command.txt`) don't inherit PaddleOCR/Surya/Tesseract's heavy dependency footprint.
- The `rec.txt`-style tab-separated `path\ttext` format is already shared implicitly between `app1.py` (`AnnotationManager.load_from_file` L185, `save_changes` L277) and `predict.py` (`save_txt` L113-134) — the consensus backend's output should conform to this existing format so it can be imported into the labeling app with minimal glue code.

**Technical Risks**

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| No automated tests exist, so the refactor could silently change behavior | M | Manual click-through checklist of every flow (upload, edit, save, rotate, delete, backup/restore, hotkeys) before calling Track A done |
| Hidden coupling (cache-clear between rotate/load, hotkey JS tied to button text) breaks when split across modules | M | Explicitly document and preserve these two couplings during the split; verify via the same click-through |
| Tesseract integration is net-new — unknown install/licensing friction versus the two engines already proven in `predict.py` | M | Time-box the Tesseract integration during the spike; if blocked, fall back to a 2-engine version of the consensus check for this version and revisit 3-engine voting later |
| Backend/service transport design is undecided (open question) | M | Resolve before Phase 4 implementation planning; default to the simplest option (REST over localhost) if no stronger constraint emerges |
| Consensus results never get wired into a real review UI, so the spike stalls at "backend works" without proving the hypothesis | M | Track B's Should-priority import step is treated as part of the spike's definition of done, not optional polish |

---

## Implementation Phases

<!--
  STATUS: pending | in-progress | complete
  PARALLEL: phases that can run concurrently (e.g., "with 3" or "-")
  DEPENDS: phases that must complete first (e.g., "1, 2" or "-")
  PRP: link to generated plan file once created
-->

| # | Phase | Description | Status | Parallel | Depends | PRP Plan |
|---|-------|-------------|--------|----------|---------|----------|
| 1 | Archive app.py | Move `app.py` aside (e.g. `legacy/app.py` or clearly marked), update README/CLAUDE.md references, no functional changes | in-progress | with 2 | - | `.claude/PRPs/plans/refactor-app1-into-src-package.plan.md` |
| 2 | Extract model/backup/annotation layer | Pull `ImageRecord`, `BackupManager`, `AnnotationManager` out of `app1.py` into `src/` modules, preserving the rotate/cache-clear coupling | in-progress | with 1 | - | `.claude/PRPs/plans/refactor-app1-into-src-package.plan.md` |
| 3 | Extract UI layer + thin entry point | Move `render_image_list`, `render_image_editor`, hotkey injection, and the currently-inline sidebar block into `src/ui/`; reduce `app1.py` to session-state init + wiring | in-progress | - | 2 | `.claude/PRPs/plans/refactor-app1-into-src-package.plan.md` |
| 4 | Documentation pass | Document `src/` module layout, data model (rec.txt/status_cache.txt/handwritten.txt), and the two known fragile couplings | in-progress | - | 3 | `.claude/PRPs/plans/refactor-app1-into-src-package.plan.md` |
| 5 | Manual regression click-through | Walk every existing flow end-to-end against the refactored app1.py | pending — checklist written, click-through not yet run | - | 3 | `.claude/PRPs/checklists/app1-regression-checklist.md` |
| 6 | Portable consensus backend skeleton | Strip `ocr_library`/hardcoded-path dependencies from `predict.py`'s detect+recognize flow; stand up as an independent service; PaddleOCR detector + PaddleOCR/Surya recognizers running | code-complete — not yet installed/run against a real batch | - | - | `.claude/PRPs/plans/ocr-consensus-spike-phases-5-9.plan.md` |
| 7 | Add Tesseract + real 2-of-3 vote + configurable threshold/override | Extend the backend from 2-engine exact-match to true 3-engine voting with configurable score threshold and manual preferred-model override | code-complete — `vote()` unit-verified by hand (all 4 branches), Tesseract call not yet run against real `tesseract-ocr`/`rus` install | - | 6 | `.claude/PRPs/plans/ocr-consensus-spike-phases-5-9.plan.md` |
| 8 | Wire spike into labeling app | Minimal import path (manual trigger + import of good/needs-review buckets) from the backend into the existing `rec.txt` workflow | code-complete — UI wired into sidebar, not yet exercised against a running backend | - | 5, 7 | `.claude/PRPs/plans/ocr-consensus-spike-phases-5-9.plan.md` |
| 9 | Subjective evaluation | Run the spike against a real document batch; maintainer judges time-saved; decide go/no-go on further consensus investment | pending — blocked on Phases 5/6/7/8 live validation | - | 8 | - |

### Phase Details

**Phase 1: Archive app.py**
- **Goal**: Remove ambiguity about which file is the live app.
- **Scope**: Relocate or clearly mark `app.py` as archived; update any docs/README pointers.
- **Success signal**: No doc or script references `app.py` as the app to run; `app1.py` is the only documented entry point.

**Phase 2: Extract model/backup/annotation layer**
- **Goal**: Move data/state logic out of the monolith without changing behavior.
- **Scope**: `src/models.py` (`ImageRecord`), `src/backup.py` (`BackupManager`), `src/annotations.py` (`AnnotationManager`); preserve the `st.error`/`st.info` calls as-is inside these modules per the technical approach decision.
- **Success signal**: `app1.py` imports these from `src/` instead of defining them inline; behavior unchanged.

**Phase 3: Extract UI layer + thin entry point**
- **Goal**: Isolate Streamlit rendering from the entry point.
- **Scope**: `src/ui/list_view.py`, `src/ui/editor_view.py`, `src/ui/sidebar.py` (newly named — currently inline in `main()`), `src/hotkeys.py`; `app1.py` shrinks to `init_session_state()` + calling into `src/`.
- **Success signal**: `app1.py` is short (roughly entry-point-sized); each `src/ui` module has a single clear responsibility.

**Phase 4: Documentation pass**
- **Goal**: Make the new structure legible for future changes.
- **Scope**: A doc (README section or `docs/`) covering module map, the rec.txt/status_cache.txt/handwritten.txt formats, and explicit call-outs for the rotate/cache-clear and hotkey/button-label couplings.
- **Success signal**: A future feature addition can be scoped correctly by reading the doc alone.

**Phase 5: Manual regression click-through**
- **Goal**: Confirm no behavior broke during the split.
- **Scope**: Upload, list/filter/paginate, edit/save, autosave-every-10, rotate, delete + restore-from-backup, hotkey nav, sidebar stats/save-all.
- **Success signal**: Every flow works identically to pre-refactor `app1.py`.

**Phase 6: Portable consensus backend skeleton**
- **Goal**: A version of `predict.py`'s detect+recognize logic that runs outside the author's machine, as a standalone service.
- **Scope**: Replace `ocr_library`/hardcoded paths; PaddleOCR as detector; PaddleOCR + SuryaOCR as recognizers (2-engine, matching current proven logic); configurable input folder.
- **Success signal**: Backend runs end-to-end on a real batch without any private-package or hardcoded-path dependency.

**Phase 7: Add Tesseract + real 2-of-3 vote + configurable threshold/override**
- **Goal**: Reach the full 3-engine consensus design described by the user.
- **Scope**: Add TesseractOCR recognizer; replace binary exact-match with a real 2-of-3 vote; make score threshold and manual preferred-model override configurable (not hardcoded).
- **Success signal**: Given disagreement among engines, the backend correctly applies threshold/override rules and produces good/needs-review buckets.

**Phase 8: Wire spike into labeling app**
- **Goal**: Make the consensus output usable inside the existing labeling workflow.
- **Scope**: Manual trigger (CLI or button) + import of the backend's `rec.txt`-format output into `AnnotationManager`'s data.
- **Success signal**: Maintainer can go from "batch of raw documents" to "pre-labeled entries visible in app1.py" without hand-editing files.

**Phase 9: Subjective evaluation**
- **Goal**: Decide whether to keep investing in the consensus feature.
- **Scope**: Run against a real batch, compare felt effort/time against manual labeling.
- **Success signal**: A clear go/no-go call, recorded, on whether to pursue a real review UI, an eval harness, or VLM engines next.

### Parallelism Notes

Phases 1 and 2 touch disjoint parts of the codebase (archiving `app.py` vs. extracting from `app1.py`) and can run concurrently. Track B (Phases 6-9) has no dependency on Track A and can be worked in parallel with the refactor if desired, since the consensus backend is a separate service by design — Phase 8's import step is the only point where the two tracks need to meet (it depends on both the refactored annotation format still being compatible, Phase 5, and the backend being ready, Phase 7).

---

## Decisions Log

| Decision | Choice | Alternatives | Rationale |
|----------|--------|--------------|-----------|
| Fate of app.py | Archive, no migration | Port missing features first, then archive; keep both indefinitely | Exploration confirmed no unique standalone logic in app.py beyond what app1.py covers |
| New code location | `src/` package + thin `app1.py` entry point | Rename app1.py to app.py after archiving old one | User wants app1.py to stay as the recognizable entry point |
| OCR consensus deployment | Separate backend service | Bundle into main Streamlit app/exe | Avoids bloating the packaged labeling tool with heavy ML dependencies |
| VLM engine scope | Deferred past this version | Include VLM engines now alongside classical ones | User explicitly split classical (firm) vs. VLM (later) |
| Success measurement for consensus spike | Subjective time-saved judgment | Formal precision/recall benchmark | User confirmed subjective is sufficient for this version; no ground-truth eval infra exists yet |
| Phases 5-9 implementation scope (2026-08-18) | Write all code (backend/, src/ui/consensus_view.py) and the Phase 5 checklist doc; skip installing heavy ML deps (paddleocr, surya-ocr, pytesseract) and skip live click-through/batch runs in this session | Also install deps and run everything live in-session | Maintainer chose to review/install/run manually rather than have an agent pip-install multi-GB ML packages and drive the Streamlit UI; `backend/consensus.py::vote()` was still unit-verified by hand since it requires no heavy deps |

---

## Research Summary

**Market Context**
Not researched — this is an internal single-operator tool; competitive/market analysis was judged not relevant by the nature of the request (personal codebase evolution, not a market-facing product decision).

**Technical Context**
Grounded directly in the codebase via commit history and a targeted code exploration pass: confirmed `app1.py` is the sole actively-developed file (last 5 commits), mapped `app1.py`'s natural module boundaries with line-level references, and traced `predict.py`'s existing two-engine detect/recognize/agreement pipeline (L210-260) as the direct, provable precursor to the requested 3-engine consensus feature — including which parts are portable (Surya, format conventions) versus tied to a private local library and hardcoded paths (`ocr_library`, absolute Windows model paths).

---

*Generated: 2026-08-18*
*Status: DRAFT - needs validation*
