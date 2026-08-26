# OCR Consensus Backend (spike)

<p align="center">
  <strong>Language:</strong>
  <b>English</b> |
  <a href="../docs/ru/backend-README.md">🇷🇺 Русский</a>
</p>

A separate FastAPI service for 3-engine consensus (PaddleOCR detector +
PaddleOCR/SuryaOCR/TesseractOCR recognizers). Not included in
`frontend/requirements.txt` and not part of the `.exe` build — the heavy ML
dependencies are deliberately isolated.

The line detector uses PaddleOCR PP-OCRv6 (detection is language-independent).

The text-line detector engine is chosen independently from the recognition
consensus — `detector_engine` in `/run` accepts `paddle` (default), `surya`,
or `tesseract`, and only affects which engine finds the line boxes.

Which recognition engines to run on a line, and how many of them must agree
on the same text to accept it without manual review, is set by the
`engines`/`min_agree` field pair in `/run` — an "N of M" scheme (see
`frontend/src/ui/generation_view.py::CONSENSUS_SCHEME_KEYS` for the ready-made
presets: 1 of 1, 1 of 2, 2 of 2, 2 of 3). Default — all 3 engines, any 2
agreeing (`engines=["paddle","surya","tesseract"]`, `min_agree=2`) — the
original hardcoded behavior. When `min_agree <= 1`, cross-checking most texts
is skipped: the single confident engine wins (or `preferred_model`/best by
score, see `backend/consensus.py::vote`). `preferred_model` remains a
tie-break only for the recognition vote and must be included in `engines`.

With `detector_engine="surya"` the line detector sometimes merges 2-3 text
lines into a single box instead of one (the cause hasn't been tracked down).
The tell is a newline (`\n`) in the text any recognition engine returned for
that box. In that case the line doesn't end up in either `good.txt` or
`needs_review.txt`, the crop isn't saved — it's simply skipped, and a message
about it goes into `error_count`/`errors` (`GET /status/{job_id}`, see below)
and into the backend console (see `backend/pipeline.py::_process_boxes`).
With other `detector_engine` values this check doesn't run.

Recognition by default (`lang="ru"`) uses the Cyrillic model
`cyrillic_PP-OCRv5_mobile_rec` — PP-OCRv6 doesn't replace it, since its 50
languages are Chinese/Japanese/English and 46 Latin-script languages, Cyrillic
isn't supported. For Latin-script documents, pass `lang="latin"` to `/run` —
then instead of the Cyrillic model, PaddleOCR PP-OCRv6 is used
(`latin_model_size`: `tiny` | `small` (default) | `medium`), and Tesseract
switches to `lang="eng"`.

## Installation

A separate virtual environment is recommended:

```bash
python -m venv .venv-backend
.venv-backend\Scripts\activate  # Windows
pip install -r backend/requirements.txt
```

A system Tesseract binary with the Russian language pack is additionally
required (not installed via `pip install pytesseract` — that's just the
Python wrapper):

- Install `tesseract-ocr` for your OS.
- Make sure `tesseract --list-langs` includes `rus`.

PaddleOCR and Surya models are downloaded and cached automatically on first
use — no need to hardcode local paths.

## Running

```bash
uvicorn backend.main:app --host 127.0.0.1 --port 8756
```

The service only listens on `127.0.0.1` — no authentication and no
restriction on the accepted `input_dir`/`output_dir` (any path the process
can reach will be read/overwritten). This is a deliberate trade-off for a
local, single-user spike (see the PRD, "Won't Building" section); don't run
it on a shared/multi-user machine as-is.

## API

- `POST /run` — `{"input_dir": str, "output_dir": str, "score_threshold": float, "preferred_model": str | null, "lang": "ru" | "latin", "latin_model_size": "tiny" | "small" | "medium", "extract_pdf_text_layer": bool, "detector_engine": "paddle" | "surya" | "tesseract", "engines": ["paddle" | "surya" | "tesseract", ...], "min_agree": int}` → `{"job_id": str, "warnings": [str]}`; 400 if `engines` is empty/contains an unknown engine, or `min_agree` is outside `[1, len(engines)]`; 409 if another job is already running (only one is supported at a time, see backend/jobs.py). `warnings` — engines from `engines` (and the detector) whose model isn't ready yet (`not_checked`/`checking`/`error` in `/models/status`) — the job starts anyway, the warning just explains why the first lines might "hang" downloading weights
- `GET /jobs/active` → `{"job_id": str | null}` — id of the currently running job (or null); needed by the frontend to restore the progress tracker after a page reload
- `GET /status/{job_id}` → `{"status": "running" | "done" | "error" | "cancelled", "error": str | null, "docs_found": int, "docs_processed": int, "good_count": int, "review_count": int, "diverged_count": int, "error_count": int, "errors": [str]}` — the progress tracker updates line by line as the job runs (see backend/jobs.py), not only when a whole file completes (a single Surya line can take up to ~20s to recognize); `diverged_count` — lines where 2+ engines are independently confident (score >= threshold) but disagreed on the text (see backend/consensus.py); `error_count`/`errors` — files/lines that failed with an exception or an engine timeout (see `ENGINE_CALL_TIMEOUT_SECONDS` below) — `error_count` grows unbounded, `errors` holds only the last `MAX_STORED_ERRORS` (default 50) messages
- `POST /jobs/{job_id}/cancel` → `{"status": "cancelling"}`; 404 — unknown `job_id`, 409 — the job is no longer running. Cancellation is cooperative: the thread can't be killed directly, so the job stops at the nearest check between files/pages/lines, without losing what's already written; once stopped, `/status` will show `"status": "cancelled"`
- `GET /jobs/status_snapshot?output_dir=...` → the same shape as `/status/{job_id}`, but keyed by `output_dir` instead of `job_id` — reads `output_dir/_job_status.json` (written on every processed file and on completion, see backend/jobs.py). Needed to find out how a job ended after a backend restart — `_jobs`/`job_id` in memory are already lost by then, but the on-disk snapshot survives a restart. 404 if there's no snapshot yet for that `output_dir`
- `GET /result/{job_id}` → `{"output_dir": str, "good_count": int, "needs_review_count": int}`
- `GET /models/status` → `{"paddle": {...}, "surya": {...}, "paddle_detector": {...}, "surya_detector": {...}, "tesseract": {...}}`, each value — `{"status": "not_checked"|"checking"|"ready"|"error", "detail": str|null}`. `paddle`/`surya` — recognition models; `paddle_detector`/`surya_detector` — separate, independently downloaded line-detection models for those same engines; `tesseract` — shared (detection and recognition use the same system binary)
- `POST /models/prepare` — `{"model": "paddle"|"surya"|"paddle_detector"|"surya_detector"}` → `{"status": "started"}` (asynchronously instantiates the engine in a background thread, which triggers downloading/caching the models; Tesseract isn't accepted here — it's installed manually, see the "Installation" section)

Job state (in-memory counters/status, `_jobs`/`job_id`) doesn't survive a
backend restart — see `backend/jobs.py`. The results themselves aren't lost:
`good.txt`/`needs_review.txt`/`debug.jsonl` are written to disk line by line
with `flush()` as the job runs, not all at once at the end, and the status is
additionally duplicated to `output_dir/_job_status.json` on every processed
file — see `GET /jobs/status_snapshot` above.

A single recognize_* call (paddle/surya/tesseract on one line) is bounded by
`ENGINE_CALL_TIMEOUT_SECONDS` (default 30s, `backend/config.py`) — if an
engine hangs (not just slow — recognize_* itself catches exceptions and
returns an empty result, see `backend/recognizers.py`), that line is treated
as empty rather than blocking the whole job. The timeout doesn't kill the
engine's thread — it just stops waiting on it; the call itself may still
finish in the background.

## Crop naming (`crops/`)

Crops are named after this pipeline's predecessor's scheme
(`predict.py::save_image`), not opaque `uuid4`:
`crops/{N // CROPS_PER_FOLDER}/image_{N:05d}.webp`, where `N` is the crop's
running number and `CROPS_PER_FOLDER = 10000` (`backend/config.py`) — i.e. no
more than 10000 files per subfolder (`crops/0/`, `crops/1/`, ...). On a
re-run against the same `output_dir`, numbering continues from the max
already found on disk (`backend/pipeline.py::_resume_img_count`) rather than
restarting from 1 — otherwise a re-run would overwrite crops already
saved/imported from previous runs under the same names.

## Auto-labeling debug data (`debug.jsonl`)

Alongside `good.txt`/`needs_review.txt` in `output_dir`, `debug.jsonl` is
written — one JSON record per line:

```json
{"crop": "crops/0/image_00001.webp", "bucket": "good", "engine": "paddle", "diverged": false,
 "engines": {"paddle": {"text": "...", "score": 0.97}, "surya": {"text": "...", "score": 0.93}, "tesseract": {"text": "...", "score": 0.81}}}
```

The `engines` field in a record only contains the engines that were actually
run on that line (see `engines`/`min_agree` in `/run` above) — not always all
3. Without this file, the winning text in `good.txt`/`needs_review.txt` is
all that's left of the vote (`backend/consensus.py::vote`); neither the
winning engine's name nor the losing variants are stored anywhere else. The
frontend uses `debug.jsonl` to show details to the labeler (see
`frontend/src/annotations.py::AnnotationManager._load_debug_file`) — if the
file is missing (e.g. for purely manual labeling), that's not an error, there
are just no details to show. PDF pages with an extracted text layer (no OCR)
don't end up in `debug.jsonl` — `vote()` isn't called for them.

## PDF

The input folder (`input_dir`) can contain `.pdf` files alongside images. For
each PDF, the first 2 pages are checked for an extractable text layer first
(`extract_pdf_text_layer=true`, the default):

- **Has a text layer** — text and coordinates are pulled directly via
  `pypdfium2` (no OCR), each line goes straight into `good.txt`. Pages
  without text inside such a document are skipped (not sent to the
  OCR fallback).
- **No text layer** (including when text only appears from page 3 onward —
  only the first 2 pages are checked) — the document is processed page by
  page as a regular raster image, through the same OCR consensus with the
  selected `engines`/`min_agree`.

**Known limitation**: a "text layer" isn't distinguished from text added by
the scanner itself (a searchable PDF from scanning software) — such a layer
can be inaccurate (the scanner's own OCR), but will be trustingly marked as
`good`. For folders with such scans, explicitly turn off
`extract_pdf_text_layer`.
