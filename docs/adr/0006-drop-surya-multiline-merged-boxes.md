# ADR-0006: Drop lines where the Surya line detector appears to have merged multiple text lines

**Date**: 2026-08-23
**Status**: accepted
**Deciders**: Vladislav Ershov

## Context

When `detector_engine="surya"`, the line detector occasionally merges 2-3
text lines into a single box instead of one (root cause not identified).
There's no independent ground truth to detect this at detection time — the
only available signal is a recognizer returning a newline (`\n`) inside its
text for that box, observed specifically with Surya's own recognizer output.

## Decision

In `_process_boxes` (`backend/pipeline.py`), when `detector_engine=="surya"`
and any recognizer's output for a box contains `\n`, the line is dropped
entirely: no crop is saved, nothing is written to `good.txt`/`needs_review.txt`/
`debug.jsonl`. The event is logged via the existing `on_error` channel
(surfaced in `error_count`/`errors` on `GET /status/{job_id}`). The check
only runs when `detector_engine=="surya"` — it's the only detector this has
been observed with.

## Alternatives Considered

### Alternative 1: Route to `needs_review` instead of dropping
- **Pros**: preserves the crop and the (garbled, `\n`-joined) text for manual review, no silent data loss
- **Cons**: pollutes the review queue with boxes that are known-bad merges, not genuine recognition disagreements — the labeler would have to re-detect these lines by hand anyway
- **Why not**: chose to keep `needs_review` meaning "recognition was uncertain," not "detection was wrong"; a merged-box crop isn't useful to review as a single unit

### Alternative 2: Run the multiline check regardless of `detector_engine`
- **Pros**: simpler code, one fewer conditional
- **Cons**: no evidence other detectors (paddle, tesseract) produce this failure mode; would silently drop lines on a heuristic that's unverified for those detectors, and a legitimately multiline recognizer response from a *correctly* single-line box (if that's even possible) would be misclassified
- **Why not**: scope the heuristic to where it's actually been observed

## Consequences

### Positive
- Corrupted multi-line-merged crops never enter `good.txt` or the review queue mislabeled as single lines
- Visible in job status (`error_count`) rather than silently vanishing from the count

### Negative
- **Data loss**: genuine text on the page for a merged-box line is never captured anywhere in this run — no fallback path re-splits or re-queues it
- Only mitigated for `detector_engine="surya"`; the same underlying detector bug (if it exists in paddle/tesseract detectors too) would go undetected

### Risks
- **False positives**: a box whose *correct* single-line text legitimately contains a newline character (unlikely for this dataset, but not provably impossible) would be dropped instead of recognized — no known real-world instance of this yet
