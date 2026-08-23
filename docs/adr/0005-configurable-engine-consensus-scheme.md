# ADR-0005: Configurable engine/consensus scheme instead of hardcoded 3-engine majority vote

**Date**: 2026-08-23
**Status**: accepted
**Deciders**: Vladislav Ershov

## Context

`backend/pipeline.py` and `backend/consensus.py` always ran all three
recognition engines (PaddleOCR, SuryaOCR, Tesseract) on every detected line
and required exactly 2 of 3 matching texts to auto-accept as "good" — both
the engine set and the agreement threshold were hardcoded. Surya recognition
alone can take up to ~20s/line (`backend/README.md`), so users had no way to
trade accuracy for speed (e.g. a quick single-engine pass) or to require
stricter agreement (all 3 must match) without code changes.

## Decision

Made `engines` (which recognizers run per line) and `min_agree` (how many
must produce matching text to auto-accept) explicit request params on
`POST /run`, threaded through `pipeline.run` → `_process_boxes`/`_process_pdf`
→ `consensus.vote()`. The frontend exposes four presets — 1 из 1, 1 из 2,
2 из 2, 2 из 3 (`frontend/src/ui/generation_view.py::CONSENSUS_SCHEMES`) —
mapping to `(engines_count, min_agree)` pairs; default (`2 из 3`) reproduces
the old hardcoded behavior exactly.

## Alternatives Considered

### Alternative 1: Keep hardcoded 3-engine consensus, add a "skip Surya" flag
- **Pros**: minimal change
- **Cons**: one binary toggle, doesn't generalize to "require all 3" or "any 2 of 2"
- **Why not**: doesn't give real control over the speed/accuracy trade-off

### Alternative 2: Free-form N-of-M controls, no presets (raw multiselect + numeric min_agree)
- **Pros**: maximum flexibility
- **Cons**: exposes invalid/confusing combinations (e.g. `min_agree=3` with 1 engine selected), forces users to understand consensus-voting mechanics
- **Why not**: the 4 presets cover the combinations that are actually useful; server still validates arbitrary `engines`/`min_agree` via the API, so nothing is lost, just not surfaced in the UI

### Alternative 3: Per-project persisted config instead of a per-request param
- **Pros**: could remember a default scheme
- **Cons**: adds a new persistence surface for a local single-user spike that otherwise stores no config (see ADR-0001 — flat files only for annotation/job state)
- **Why not**: request-scoped choice is sufficient; no evidence users need a saved default yet

## Consequences

### Positive
- Users trade off speed vs. confidence per run (skip Surya for speed, or require all 3 for maximum confidence)
- `vote()`'s `min_agree` generalizes cleanly — the same function path handles N-way majority vote and single-best-engine fallback (`min_agree <= 1`), no special-casing per scheme
- Backward-compatible default (`engines=["paddle","surya","tesseract"], min_agree=2`) matches prior hardcoded behavior exactly

### Negative
- More combinations to reason about/test in `vote()` (branches on `min_agree >= 2` vs. `<= 1`)
- `debug.jsonl` records now vary in which engine keys are present per job — any future tooling reading it must not assume all 3 keys are always there (current `frontend/src/annotations.py` debug loader is already generic, no fixed-key assumption found)

### Risks
- **Invalid engines/min_agree combos reaching the pipeline** — mitigated by `POST /run` validation in `backend/main.py` (non-empty subset of known engines, `1 <= min_agree <= len(engines)`), returns 400 before a job starts
