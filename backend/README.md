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
original hardcoded behavior. With `min_agree >= 2` the only way into
`good.txt` is ≥ `min_agree` engines returning **character-for-character
identical** text; otherwise the line goes to `needs_review.txt` no matter how
confident a single engine is (its text — `preferred_model` if it returned
something, else the best by score — is kept as a hint). `score_threshold`
only matters when `min_agree <= 1`: the single confident engine wins (or
`preferred_model`/best by score, see `backend/consensus.py::vote`).
`preferred_model` must be included in `engines`.

Recognition is batched per page: the detected lines are cropped once
(bbox over all polygon vertices, clamped to the image) and every selected
engine gets the same list of crops in one call per batch of
`RECOGNITION_BATCH_SIZE` lines (`backend/config.py`); engines run in
parallel. The timeout budget is `ENGINE_CALL_TIMEOUT_SECONDS` × batch size;
the line detector has its own `DETECTOR_CALL_TIMEOUT_SECONDS`, and a hung
detector or engine is dropped for the rest of the job after 3 consecutive
timeouts. Input files are matched by extension case-insensitively
(`.JPG`, `.TIF`, ...), non-recursively, in sorted order. Crops are saved as
**lossless** WebP.

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
pip install uv && uv pip install -r backend/requirements.txt --override backend/overrides.txt  # uv: see backend/overrides.txt
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

The service only listens on `127.0.0.1` — no authentication and, by default,
no restriction on the accepted `input_dir`/`output_dir` (any path the process
can reach will be read/overwritten). This is a deliberate trade-off for a
local, single-user spike (see the PRD, "Won't Building" section, and
`docs/adr/0002`); don't run it on a shared/multi-user machine as-is.

Set `OCR_DATA_ROOT` (env var) to a directory to confine `input_dir`/`output_dir`
to it — `/run` and `/jobs/status_snapshot` then reject paths that resolve
outside it. Docker Compose sets `OCR_DATA_ROOT=/data` and binds every port to
`127.0.0.1`.

## API

- `POST /run` — `{"input_dir": str, "output_dir": str, "score_threshold": float (0..1), "preferred_model": str | null, "lang": "ru" | "latin", "latin_model_size": "tiny" | "small" | "medium", "extract_pdf_text_layer": bool, "pdf_ocr_fallback": bool, "detector_engine": "paddle" | "surya" | "tesseract", "engines": ["paddle" | "surya" | "tesseract", ...], "min_agree": int, "append_crop_size": bool}` → `{"job_id": str, "warnings": [str]}` (`append_crop_size`, default `false`, both modes: append the crop width and height in pixels to every `good.txt`/`needs_review.txt` line — `crop\ttext\tw\th`); **422** if a field is out of range or the cross-field checks fail (`engines` empty/unknown, `min_agree` outside `[1, len(engines)]`, `preferred_model` not in `engines`, `iou_threshold` outside `(0, 1]`, …); 400 if `input_dir` doesn't exist, `output_dir` isn't writable, or a path is outside `OCR_DATA_ROOT`; 409 if another job is already running (only one is supported at a time, see backend/jobs.py). `warnings` — engines from `engines` (and the detector) whose model isn't ready yet (`not_checked`/`checking`/`error` in `/models/status`); the job starts anyway. Readiness is checked **before** the job is spawned, so a slow check delays the response rather than detaching from it.
- `GET /jobs/active` → `{"job_id": str | null}` — id of the currently running job (or null); needed by the frontend to restore the progress tracker after a page reload
- `GET /status/{job_id}` → `{"status": "running" | "done" | "error" | "cancelled", "error": str | null, "docs_found": int, "docs_processed": int, "good_count": int, "review_count": int, "diverged_count": int, "error_count": int, "errors": [str]}` — the progress tracker updates line by line as the job runs (see backend/jobs.py), not only when a whole file completes (a single Surya line can take up to ~20s to recognize); `diverged_count` — lines where 2+ engines are independently confident (score >= threshold) but disagreed on the text (see backend/consensus.py); `error_count`/`errors` — files/lines that failed with an exception or an engine timeout (see `ENGINE_CALL_TIMEOUT_SECONDS` below) — `error_count` grows unbounded, `errors` holds only the last `MAX_STORED_ERRORS` (default 50) messages
- `POST /jobs/{job_id}/cancel` → `{"status": "cancelling"}`; 404 — unknown `job_id`, 409 — the job is no longer running. Cancellation is cooperative: the thread can't be killed directly, so the job stops at the nearest check between files/pages/lines, without losing what's already written; once stopped, `/status` will show `"status": "cancelled"`
- `GET /jobs/status_snapshot?output_dir=...` → the same shape as `/status/{job_id}`, but keyed by `output_dir` instead of `job_id` — reads `output_dir/_job_status.json` (written on every processed file and on completion, see backend/jobs.py). Needed to find out how a job ended after a backend restart — `_jobs`/`job_id` in memory are already lost by then, but the on-disk snapshot survives a restart. 404 if there's no snapshot yet for that `output_dir`
- `GET /result/{job_id}` → `{"output_dir": str, "good_count": int, "needs_review_count": int}`; 404 — unknown `job_id`; 409 if the job is still running / errored / cancelled (not `done`)
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
finish in the background. A per-engine lock keeps the abandoned call from
racing the next one inside the shared (non-thread-safe) predictor, and an
engine that times out 3 times in a row is dropped for the rest of the job
(an `errors[]` message says so; restart the backend to re-enable it).

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

The input folder (`input_dir`) can contain `.pdf` files alongside images.
With `extract_pdf_text_layer=true` (the default) every page of a PDF is
decided separately (`pdf_extract.page_text_layer_usable`):

- **Clean text layer** — text and coordinates are pulled directly via
  `pypdfium2` (no OCR), each line goes straight into `good.txt`. Line boxes
  get a random margin so crops don't clip glyph edges: 1–3 px left/right
  (`TEXT_BOX_PAD_X_RANGE`), 0–2 px top/bottom (`TEXT_BOX_PAD_Y_RANGE`),
  drawn independently per side and per line.
- **No text layer, or a poor one** — the page is processed as a regular
  raster image, through the same OCR consensus with the selected
  `engines`/`min_agree`. One document can mix both: clean body pages from the
  layer, the title page, tables and badly recognised pages through OCR.
  With `pdf_ocr_fallback=false` such pages are skipped instead — a
  text-layer-only run without slow CPU OCR (images in `input_dir` are still
  OCR'd; `pdf_ocr_fallback=false` together with `extract_pdf_text_layer=false`
  is rejected with 422).

**Text-layer quality**: a scan's text layer is usually the scanner's own OCR
(a searchable PDF) and can be inaccurate or outright garbage — typewritten
pages especially. `backend/text_layer_quality.py` scores each page as the
share of plausible words (no mixed alphabets, no Latin inside Russian text
except upper-case acronyms like `ISO`, no long vowel-less words, no stray
symbols, no runs of 3+ single letters — letter-spaced text or specks read as
letters). A page is taken from the layer at ≥ 0.98 (`PAGE_MIN_QUALITY`):
on 16 scanned Soviet standards, pages at ≥ 0.98 had ~3% bad lines, at
0.95–0.98 already ~12%. Pages with fewer than 5 words can't be judged and are
taken from the layer if they have any text. The heuristic has no dictionary,
so plausible-looking misspellings still pass — for folders known to have bad
layers, explicitly turn off `extract_pdf_text_layer`.

**Line style, as a library call**: `pdf_extract.extract_page_text_lines(page,
width, height, rng=None)` returns the same boxes and texts as
`extract_page_text_boxes` (which is built on it, with the same `rng` draw
order), plus a `TextStyle` per line: `font_name` (base font name without the
`ABCDEF+` subset prefix), `font_size` in points, `bold`, `italic`. A PDF text
object has one font and size, so the first non-blank character's style is the
whole line's. Bold is read from the font name (`Bold`/`Black`/`Heavy`/
`Semibold`/`Demi`), weight ≥ 600 or the ForceBold flag — pdfium reports weight
400 even for `LiberationSans-Bold` in LibreOffice PDFs; italic from the name
(`Italic`/`Oblique`) or the Italic flag. The service pipeline doesn't use it —
it's for dataset generators outside this repo (doc-generator's line balancer
imports `backend/pdf_extract.py` directly) that need to know which font each
crop was printed in.

## VLM mode (`mode="vlm"`)

A second auto-labeling path (`backend/pipeline_vlm.py`). Instead of the
per-line pipeline (detector → line crop → `recognize_*` → `vote`), a
vision-language model processes the **whole page in a single forward** and
returns `(line polygon, text)` itself. The output is the same
`good.txt` / `needs_review.txt` / `debug.jsonl` / `crops/`, so the handoff
into manual labeling is unchanged.

All models are reached over one **OpenAI-compatible HTTP** endpoint
(`POST {endpoint}/v1/chat/completions` with an `image_url`) served by
llama.cpp (see below) — the backend adds only one dependency, `httpx`, and
pulls no VLM ML weights.

### `/run` fields

`{"mode": "vlm", "input_dir": str, "output_dir": str, "vlm_engines": [str, ...], "vlm_min_agree": int, "iou_threshold": float}`
→ `{"job_id": str, "warnings": [str]}`.

- `vlm_engines` — non-empty subset of the table below; 400 otherwise.
- `vlm_min_agree` — how many engines must return an IoU-matching box with the
  same text for the line to count as `good` (analogue of `min_agree`, but over
  boxes — VLMs give no per-line confidence). Must be `1..len(vlm_engines)`.
- `iou_threshold` — box-match threshold when reconciling several engines.
  Must be in `(0, 1]`.
- The classic fields (`engines` / `min_agree` / `detector_engine` / `lang`)
  are ignored when `mode="vlm"`. `mode` defaults to `"consensus"`, so old
  clients are unaffected.

The progress tracker (`GET /status/{job_id}`) and `JobState` are shared with
the classic path — the same `good_count` / `review_count` / `diverged_count`
counters.

### Engines

All five models are served by **one llama.cpp `llama-server` in router mode**
(the `llama-vlm` compose service; presets in `scripts/vlm/models.ini`): one
address (`VLM_ENDPOINT`, default `http://localhost:8080`, in compose
`http://llama-vlm:8080`), the model is picked by the request's `model` field
and loaded on demand. llama.cpp runs the same GGUF files on CPU
(`vlm-cpu` profile) and GPU (`vlm-gpu`). **At most one model is kept in memory**
(`--models-max 1`, `VLM_MODELS_MAX`): the next one evicts the previous.

| id | preset | GGUF | lines from |
|---|---|---|---|
| `paddleocr_vl` | `paddleocr-vl` | `PaddlePaddle/PaddleOCR-VL-1.6-GGUF` (official) | the model: `Spotting:` |
| `hunyuan_ocr` | `hunyuan-ocr` | `ggml-org/HunyuanOCR-GGUF` | the model: spotting |
| `glm_ocr` | `glm-ocr` | `ggml-org/GLM-OCR-GGUF` | line detector + `Text Recognition:` |
| `dots_ocr` | `dots-ocr` | `ggml-org/dots.ocr-GGUF` | line detector + `prompt_ocr` |
| `unlimited_ocr` | `unlimited-ocr` | `sahilchachra/Unlimited-OCR-GGUF` (community) | line detector + `Free OCR.` |

- **native** (`paddleocr_vl`, `hunyuan_ocr`) — the model returns text lines with
  boxes for the whole page. PaddleOCR-VL 1.6 `Spotting:` answers
  `<|TEXT_START|>text<|TEXT_END|><|LOC_BEGIN|><|LOC_n|>×8<|LOC_END|>` (4 points),
  HunyuanOCR — `text(x1,y1),(x2,y2)`; both in [0, 1000]. Pages whose both sides
  are < 1500 px are upscaled ×2 for PaddleOCR-VL, as the official pipeline does.
- **layout** (`glm_ocr`, `dots_ocr`, `unlimited_ocr`) — boxes come from
  `backend/vlm_layout.py` (the same `paddle` line detector as the classic path);
  every line is sent as its own request (a crop from the full-resolution page).
  dots.ocr has no per-line mode (`prompt_layout_all_en` returns paragraphs and
  tables), Unlimited-OCR's box mode relies on special tokens the server strips.
- Prompts are the models' official ones, verbatim (they're trained on fixed
  instructions) — see `backend/vlm_adapters.py::PROMPTS` for sources.
- Order: **model by model** — the whole folder with the first model, then the
  next one; earlier models' lines are kept in memory, the last model writes
  lines as it goes. That's exactly `len(vlm_engines)` model switches instead of
  one per page. Document progress (`docs_processed`) moves during the last pass.
- Models see a copy of the page downscaled to ≤ `VLM_MAX_IMAGE_SIDE`; boxes are
  mapped back and crops are cut from the **original** resolution.
- If a model returns nothing, its lines are skipped and a message with the
  reason (`HTTP 404`, response timeout, service unreachable, or "no lines in
  the model's answer") goes into `error_count`/`errors`.

Bring it up with `scripts/vlm/setup.sh --cpu` (`scripts\vlm\setup.ps1 -Cpu` on
Windows) or `docker compose --profile vlm-cpu up -d` (see `docs/docker.md`).
The one-shot `vlm-models` container downloads the GGUF files (pinned to HF
commits, `scripts/vlm/fetch_models.py`; `VLM_MODELS` picks a subset) and patches
PaddleOCR-VL's mmproj (`clip.vision.image_max_pixels = 1605632`, required for
`Spotting:`). Each engine shows up in `GET /models/status` as `vlm_<id>`: one
`GET /v1/models` to llama-server (cached for `VLM_STATUS_CACHE_TTL_SECONDS`) —
`ready` when the preset exists (detail "loads on first request" until it's
loaded), `error` when the server is unreachable, the preset is missing or the
model failed to load. `/models/prepare` is **not** supported for VLM engines.

### `debug.jsonl` for VLM

Same shape as the classic path, but `score` is always `1.0` (VLMs give no
per-line confidence). `diverged` is set when ≥2 engines returned a non-empty
but different text for the same box.

### Limitations

- PDF pages are always rasterised — the text layer is not used in VLM mode
  (use `mode="consensus"` for text-layer PDFs).
- `layout` strategy yields one line per line the detector found.
- Tables/formulas are stored as plain text lines (the dataset is per-line).
