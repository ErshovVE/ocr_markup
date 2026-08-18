# Plan: OCR Markup v2 — Regression Sign-off + Consensus Backend Spike (Phases 5-9)

## Summary
Closes out Track A of the v2 PRD with a manual regression pass over the already-refactored `app1.py`/`src/` app (Phase 5), then builds and evaluates Track B: a standalone FastAPI backend that runs a 3-engine (PaddleOCR detector + PaddleOCR/SuryaOCR/TesseractOCR recognizers) consensus pipeline over a folder of documents, exposes it over localhost REST, and wires a minimal trigger/import UI into `app1.py` so consensus output lands in the existing `rec.txt` annotation format (Phases 6-9). Ends with a subjective go/no-go call on the consensus feature.

## User Story
As the sole maintainer of the OCR labeling tool,
I want confirmation that the src/ refactor didn't break anything, plus a working (if rough) OCR-consensus backend that pre-labels a real batch of documents,
So that I can keep shipping features safely and judge whether multi-engine consensus is worth investing in further.

## Problem → Solution
Track A's code split (Phases 1-4) is done in the working tree but has never been regression-tested end-to-end (Phase 5). Track B doesn't exist yet — `predict.py` proves the detect→recognize→agree shape works, but it's tied to a private `ocr_library` package, hardcoded Windows model paths, and only 2 engines with a hardcoded threshold. This plan takes that proven shape, ports it onto public packages (`paddleocr`, `surya-ocr`, `pytesseract`) behind a FastAPI service, adds Tesseract as a true third vote, makes threshold/override configurable, and gives the maintainer a way to pull results into `app1.py` and judge whether it saved time.

## Metadata
- **Complexity**: XL (spans a no-code manual QA phase and a new multi-dependency backend service with 3 ML engines)
- **Source PRD**: `.claude/PRPs/prds/ocr-markup-v2.prd.md`
- **PRD Phases**: 5, 6, 7, 8, 9
- **Estimated Files**: ~14 (1 checklist doc, 9 new backend files, 2 new app files, 2 updated app files)

---

## Current State (verified against working tree, not the PRD text)

Phases 1-4 are further along than the PRD's `in-progress` status suggests — confirmed by reading the actual files, not assuming from the PRD:

- `app1.py` is already thin (117 lines): `init_session_state()`, `main()`, imports from `src/`. Verified via `git diff app1.py` (712 deletions from the last commit) and a direct read.
- `src/models.py` — `ImageRecord` dataclass (11 lines).
- `src/backup.py` — `BackupManager` (105 lines), byte-identical logic to the old inline class.
- `src/annotations.py` — `AnnotationManager` + `save_as_handwritten` (195 lines), imports `BackupManager`/`ImageRecord` from the sibling modules.
- `src/image_ops.py` — `load_and_resize_image` + `rotate_image` (35 lines), with an explicit comment calling out the cache-clear coupling (see Patterns to Mirror).
- `src/hotkeys.py` — `register_hotkeys` (53 lines), with an explicit comment calling out the button-label-text coupling.
- `src/ui/list_view.py`, `src/ui/editor_view.py`, `src/ui/sidebar.py` — the three render functions, wired via imports in `app1.py`.
- `legacy/app.py` — old `app.py` moved here (git-tracked rename), `README.md` updated to point at `app1.py` and note the archive.
- **Not yet present**: no `docs/` folder despite `src/image_ops.py:23`'s comment referencing "docs/architecture.md" — Phase 4's documentation deliverable is not fully done. This plan does not redo Phase 4 (out of scope — it belongs to the existing `refactor-app1-into-src-package.plan.md`), but Phase 5's checklist doc doubles as partial documentation of expected behavior.
- No backend/, no `ocr_library` usage outside `predict.py`, no test framework anywhere in the repo (confirmed via `CLAUDE.md` and direct inspection).

This means Phase 5 can run immediately against the real current code, and Phases 6-9 are fully greenfield (no prior backend scaffolding to reuse).

---

## UX Design

### Before
```
┌────────────────────────────────────────────┐
│ Maintainer uploads rec.txt, labels every    │
│ line by hand in app1.py. No pre-fill.       │
│ predict.py exists but only runs on the      │
│ author's machine with private packages.     │
└────────────────────────────────────────────┘
```

### After
```
┌────────────────────────────────────────────┐
│ Maintainer runs `uvicorn backend.main:app`  │
│ once, points it at a folder of documents     │
│ via a new "Консенсус OCR" sidebar section    │
│ in app1.py, clicks "Запустить" → polls       │
│ status → clicks "Импортировать" to merge     │
│ good/needs-review buckets into the current   │
│ AnnotationManager. Auto-labeled lines show   │
│ up already marked; needs-review lines show   │
│ up unmarked, same as any other unlabeled row. │
└────────────────────────────────────────────┘
```

### Interaction Changes
| Touchpoint | Before | After | Notes |
|---|---|---|---|
| Sidebar | Stats + save-all + backups only | Adds a "🤖 Консенсус OCR" expander: input dir, output dir, threshold slider, preferred-model dropdown, Запустить/Статус/Импортировать buttons | New `src/ui/consensus_view.py`, called from `render_sidebar` |
| New process | N/A | `uvicorn backend.main:app --port 8756` run manually alongside `streamlit run app1.py` | Two processes, not bundled into the exe |

---

## Mandatory Reading

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | `app1.py` | 1-119 | Current thin entry point — shows exactly what Phase 5 must click-through and where Phase 8's UI call gets wired in |
| P0 | `src/annotations.py` | 1-59, 115-160 | `load_from_file` parsing rules and `save_changes` output format — the consensus backend's output must be importable through the same shape |
| P0 | `src/image_ops.py` | 23, 24-35 | The documented rotate/cache-clear coupling Phase 5 must specifically re-verify |
| P0 | `src/hotkeys.py` | 1 | The documented button-label-text coupling (JS matches literal `←`/`→`) Phase 5 must specifically re-verify |
| P0 | `predict.py` | 137-265 | The proven 2-engine detect→recognize→agree shape Phase 6/7 port and generalize — read in full, it's the direct source of the consensus logic |
| P1 | `src/ui/sidebar.py` | 1-81 | Exact pattern for adding a new sidebar section (Phase 8) |
| P1 | `src/backup.py` | 1-106 | Shows the project's dataclass-free, plain-class + `Optional`/`Dict`/`List` typing style to mirror in backend code |
| P2 | `CLAUDE.md` | all | Russian-UI-strings convention, no-test-framework reality, broad try/except + `st.error` convention |
| P2 | `.claude/PRPs/prds/ocr-markup-v2.prd.md` | 92-186 | Full technical approach and phase details this plan implements |

## External Documentation

| Topic | Source | Key Takeaway |
|---|---|---|
| PaddleOCR text detection module usage | https://paddlepaddle.github.io/PaddleOCR/main/en/version3.x/module_usage/text_detection.html | PaddleOCR 3.x exposes the detector as an independently usable module (`paddleocr.TextDetection` / CLI `paddleocr text_detection`) — recognition is not required to get line boxes, so the public `paddleocr` package can fully replace `ocr_library`'s detector role without pulling in its recognition model too |
| pytesseract confidence scoring | `pytesseract.image_to_data(image, output_type=Output.DICT)` | Returns per-word text + `conf` (0-100 int, `-1` for non-text rows); for a single-line crop, join non-`-1` words and average their `conf`/100 to get a comparable `[0,1]` score against Paddle/Surya's confidence scores |
| PaddleOCR/Surya model distribution | Both `paddleocr` and `surya-ocr` auto-download and cache their own models on first use (HF Hub / PaddleX hub cache dirs) | Resolves PRD open question #2 — no hardcoded local model paths needed once `ocr_library`'s custom ONNX pipeline is dropped in favor of the public packages; this is *why* Phase 6 explicitly requires dropping `ocr_library` |
| Tesseract licensing | Apache License 2.0 (both `pytesseract` wrapper and the `tesseract-ocr` system binary) | Resolves PRD open question #4 — no licensing blocker to adding it as a third recognizer |

---

## Patterns to Mirror

### DATACLASS_MODEL
```python
# SOURCE: src/models.py:1-11
from dataclasses import dataclass


@dataclass
class ImageRecord:
    """Структура данных для одной записи изображения"""

    relative_path: str
    absolute_path: str
    annotation: str
    is_marked: bool = False
```
Backend request/response and per-line-result types follow this same plain-`@dataclass`-with-docstring shape (no Pydantic-first modeling even though FastAPI supports it directly — use `@dataclass` for internal pipeline types, Pydantic `BaseModel` only at the FastAPI request/response boundary since FastAPI requires it there).

### ERROR_HANDLING
```python
# SOURCE: src/annotations.py:23-25, 57-58
def load_from_file(self, file_contents: str) -> Tuple[bool, str]:
    """Загружает данные из файла"""
    try:
        ...
    except Exception as e:
        return False, f"Ошибка загрузки: {e}"
```
Broad `try/except Exception as e` returning a `(bool, str)` or `Optional[...]` result, message in Russian — mirror this in every backend pipeline function that touches the filesystem or calls an OCR engine, per `CLAUDE.md`'s documented convention. Do not introduce custom exception classes — the codebase has none.

### FILE_FORMAT (rec.txt)
```python
# SOURCE: src/annotations.py:129-134
lines = []
for record in self.records.values():
    lines.append(f"{record.relative_path}\t{record.annotation}\n")

self.annotation_file.write_text("".join(lines), encoding="utf-8")
```
```python
# SOURCE: predict.py:113-134 (save_txt) — same tab-separated shape, different bucket names
txt.write("".join(good_preds))  # each entry already formatted as f"{path}\t{text}\n"
```
The consensus backend's `good.txt`/`needs_review.txt` output MUST use this exact `path\ttext\n` shape so Phase 8's import step can feed it through `AnnotationManager.load_from_file` with zero format translation.

### DETECT_RECOGNIZE_VOTE_SHAPE
```python
# SOURCE: predict.py:210-258 — the whole loop is the shape to port and generalize
for crop_idx, box in enumerate(surya_bboxes):
    try:
        surya_predictions = recognition_predictor(...)
        surya_text = surya_predictions[0].text_lines[0].text
        surya_score = surya_predictions[0].text_lines[0].confidence

        img_crop = image[box[0][1] : box[2][1], box[0][0] : box[2][0]]
        paddle_predictions = ocr(np.array([img_crop]))
        paddle_text = paddle_predictions[0][0][0]
        paddle_score = paddle_predictions[0][0][1]
        ...
        if surya_text == paddle_text and paddle_text != "":
            good_preds.append(f"{image_save_path}\t{paddle_text}\n")
        else:
            if paddle_score >= filter_score:
                bad_highscore_preds.append(f"{image_save_path}\t{paddle_text}\n")
            elif surya_score >= filter_score:
                bad_highscore_preds.append(f"{image_save_path}\t{surya_text}\n")
            else:
                bad_underscore_preds.append(f"{image_save_path}\t{paddle_text}\n")
    except Exception as err:
        print(f"Ошибка {err} на {file_path}")
```
Phase 6 ports this per-crop try/except-and-continue shape as-is with 2 engines (Paddle + Surya, using the public packages); Phase 7 extends the `if a == b` binary check into a real 3-way `Counter`-based majority vote and replaces the hardcoded `filter_score = 0.95` with a constructor/request parameter. Preserve the "log and skip this crop, keep going" resilience — one bad crop must never abort the whole batch, matching the existing tool's tolerance for partial failure.

### CONFIG_CONSTANTS
```python
# SOURCE: predict.py:137-144
SCAN = ["pdf"]
IMAGE = ["jpg", "jpeg", "png", "tif", "tiff", "gif", "giff", "bmp", "webp"]
allowed_extensions = SCAN + IMAGE + DOC
filter_score = 0.95
images_one_folder = 10000
random_padding = 7
min_image_pix = 10
```
```python
# SOURCE: src/annotations.py:27 — the app's own (slightly different) extension allowlist
image_extensions = (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp")
```
Note the two allowlists already disagree (`predict.py` has `tif`/`gif`/`giff` without dots; `annotations.py` has `.tiff` with a dot, no `.tif`/`.gif`). The PRD's Could-priority "shared constants module" item is out of scope for this plan (Won't Building, see below) — Phase 6's backend defines its own `IMAGE_EXTENSIONS` tuple matching `annotations.py`'s dotted style (since its output must round-trip through `AnnotationManager`), not `predict.py`'s.

### SIDEBAR_SECTION_PATTERN
```python
# SOURCE: src/ui/sidebar.py:1-9, 35-37
from src.annotations import AnnotationManager


def render_sidebar(manager: AnnotationManager):
    """Отрисовывает сайдбар: статистика, сохранение, управление бэкапами"""
    ...
    st.sidebar.divider()
    st.sidebar.header("🗂️ Бэкапы")
```
Phase 8's new consensus section is a sibling function `render_consensus_section()` in a new `src/ui/consensus_view.py`, called from `render_sidebar` after the existing backup section, following the same `st.sidebar.divider()` + `st.sidebar.header(emoji + Russian title)` opening.

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `.claude/PRPs/checklists/app1-regression-checklist.md` | CREATE | Phase 5's click-through checklist, filled in with pass/fail during execution |
| `backend/__init__.py` | CREATE | Makes `backend` importable for `uvicorn backend.main:app` |
| `backend/requirements.txt` | CREATE | Isolates heavy ML deps (paddleocr, surya-ocr, pytesseract, opencv-python, fastapi, uvicorn) from the app's `requirements.txt` per PRD's explicit "Won't Building" item |
| `backend/config.py` | CREATE | `IMAGE_EXTENSIONS`, default score threshold, default port — the one config module for the service |
| `backend/detector.py` | CREATE | PaddleOCR-based line detector, wraps the public `paddleocr` package (Phase 6) |
| `backend/recognizers.py` | CREATE | Three recognizer functions: Paddle, Surya (Phase 6), Tesseract (Phase 7) |
| `backend/consensus.py` | CREATE | `vote()` — generalized 2-of-3 majority + threshold/override logic (Phase 6 binary, extended in Phase 7) |
| `backend/pipeline.py` | CREATE | Orchestrates folder → detect → recognize×3 → vote → good.txt/needs_review.txt (Phase 6/7) |
| `backend/jobs.py` | CREATE | In-memory job store (dict) + background-thread runner so `/run` returns immediately and `/status/{id}` can be polled (Phase 6) |
| `backend/main.py` | CREATE | FastAPI app: `POST /run`, `GET /status/{job_id}`, `GET /result/{job_id}` (Phase 6/7) |
| `src/ui/consensus_view.py` | CREATE | `render_consensus_section()` — trigger/status/import UI (Phase 8) |
| `src/ui/sidebar.py` | UPDATE | Call `render_consensus_section(manager)` after the backups section | (Phase 8) |
| `requirements.txt` | UPDATE | Add `requests==2.32.3` (HTTP client for the app→backend call) — the only new app-side dependency, deliberately not an ML package | (Phase 8) |
| `.claude/PRPs/prds/ocr-markup-v2.prd.md` | UPDATE | Flip phase 5-9 statuses as each completes; fill in Phase 9's go/no-go decision in the Decisions Log | (all phases) |

## NOT Building

- Redoing Phase 4's documentation pass (the missing `docs/architecture.md`) — that belongs to the existing `refactor-app1-into-src-package.plan.md`, not this plan.
- The Could-priority shared image-extension constants module unifying `predict.py` and `annotations.py` — explicitly out of scope per the PRD's MoSCoW table; noted as a discovered inconsistency only.
- VLM-based recognizers (PaddleOCR-VL, Hunyuan-OCR, DeepSeek-OCR) — explicitly deferred past this version per the PRD.
- Formal precision/recall evaluation harness for consensus output — Phase 9 is subjective by design per the PRD.
- Any authentication/authorization on the FastAPI backend — single-operator, localhost-only, matches the "no multi-user features" scope decision.
- A job queue, persistence layer, or database for backend jobs — an in-memory dict is sufficient for a single concurrent job on one machine; the process restarting loses job history, which is acceptable for a spike.
- Migrating `predict.py`/`predict.ipynb` themselves — they stay as-is; the backend is new code inspired by them, not a refactor of them.
- Batch cancellation, progress percentages, or ETA display in the UI — Phase 8's UI only needs run/poll/import, not a full job-management console.

---

## Step-by-Step Tasks

### Phase 5 — Manual Regression Click-Through

#### Task 5.1: Write the regression checklist doc
- **ACTION**: Create `.claude/PRPs/checklists/app1-regression-checklist.md` listing every flow from the PRD's Phase 5 scope, each as a checkbox with the exact button/key it exercises.
- **IMPLEMENT**: One row per flow: upload rec.txt → set working dir; list filter (all/unmarked/marked) + pagination (◀/▶); click a list row to jump `current_idx`; edit textarea + "✓ Подтвердить" (advances index, increments `unsaved_changes`, autosaves at 10); "✍ Рукописный" (writes to `handwritten.txt` + copies file, dedupes on exact-line match); "🗑️" → confirm modal → "✓ Да" (deletes file + record + creates backup) and "✗ Отмена" (aborts); "↶"/"↷" rotate (image updates immediately — this specifically verifies `load_and_resize_image.clear()` in `src/image_ops.py:31` actually busts the Streamlit cache across the module boundary); "←"/"→" nav buttons AND physical arrow keys (verifies `src/hotkeys.py`'s literal-text button matching survived the module split); sidebar stats (total/marked%/remaining); sidebar "💾 Сохранить всё"; sidebar backup list (📋 toggle, last-3 display, ↩️ restore + reload).
- **MIRROR**: N/A — this is a new checklist doc, not code.
- **IMPORTS**: N/A.
- **GOTCHA**: The two coupling points called out in the PRD's Technical Approach (rotate/cache-clear, hotkey/button-label) are the highest-risk regressions from the module split — give them their own explicit rows, don't bury them in a generic "editing works" row.
- **VALIDATE**: Every row has a concrete pass/fail outcome recorded after actually running `streamlit run app1.py --server.enableXsrfProtection=false` against a real small image batch.

#### Task 5.2: Execute the checklist
- **ACTION**: Run `streamlit run app1.py --server.enableXsrfProtection=false`, walk every row in the Task 5.1 checklist against a real (or representative test) `rec.txt` + image folder.
- **IMPLEMENT**: For each row, perform the action, observe the result, mark ✅/❌ with a one-line note in the checklist doc. For any ❌, file it as a bug and fix it in the relevant `src/` module before continuing (small, targeted fix — not a re-refactor).
- **MIRROR**: N/A.
- **IMPORTS**: N/A.
- **GOTCHA**: Test rotate on an image, then immediately confirm the *displayed* thumbnail changes without a manual page refresh — a passing "rotate saves to disk" check can still hide a cache-clear regression if you don't look at the rendered image itself.
- **VALIDATE**: All rows ✅, or all ❌ rows have linked fixes committed and re-verified.

#### Task 5.3: Update PRD phase status
- **ACTION**: Flip Phase 5's row in `ocr-markup-v2.prd.md`'s Implementation Phases table from `pending` to `complete` (or `blocked` with notes if unresolved regressions remain), add the checklist doc path as its PRP Plan reference.
- **VALIDATE**: PRD table and checklist doc agree on status.

---

### Phase 6 — Portable Consensus Backend Skeleton

#### Task 6.1: Scaffold the backend package and its own dependency file
- **ACTION**: Create `backend/__init__.py` (empty), `backend/requirements.txt`.
- **IMPLEMENT**:
  ```
  fastapi==0.115.0
  uvicorn[standard]==0.30.6
  paddleocr==2.9.1
  paddlepaddle==2.6.2
  surya-ocr==0.8.3
  pytesseract==0.3.13
  opencv-python==4.10.0.84
  Pillow==11.1.0
  ```
  (Pin the same `Pillow` version as the main app's `requirements.txt` since crops flow through both; pin others to the latest stable at implementation time — verify with `pip index versions <pkg>` since these move fast.)
- **MIRROR**: `requirements.txt` (root) — same flat `pkg==version` format, no extras beyond what's used.
- **IMPORTS**: N/A (this is the dependency manifest).
- **GOTCHA**: This file is deliberately separate from the root `requirements.txt` and never referenced by `pyinst_command.txt`/`wrapper.py` — installing it is a manual `pip install -r backend/requirements.txt` step, documented in a short "Running the consensus backend" section in `README.md` (or a `backend/README.md`, maintainer's call at implementation time).
- **VALIDATE**: `pip install -r backend/requirements.txt` succeeds in a fresh venv; root `requirements.txt` is untouched by this task.

#### Task 6.2: Config module
- **ACTION**: Create `backend/config.py`.
- **IMPLEMENT**:
  ```python
  IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp")
  DEFAULT_SCORE_THRESHOLD = 0.95
  DEFAULT_HOST = "127.0.0.1"
  DEFAULT_PORT = 8756
  ```
- **MIRROR**: `src/annotations.py:27`'s dotted-extension tuple — deliberately matches this, not `predict.py`'s undotted list, since output must round-trip through `AnnotationManager.load_from_file`.
- **GOTCHA**: Do not import this into `predict.py` or vice versa — no cross-dependency between the backend and the standalone script per the PRD's scope.
- **VALIDATE**: `python -c "from backend.config import IMAGE_EXTENSIONS; print(IMAGE_EXTENSIONS)"` prints the tuple.

#### Task 6.3: Detector module (PaddleOCR, detection-only)
- **ACTION**: Create `backend/detector.py`.
- **IMPLEMENT**: A `Detector` class wrapping `paddleocr`'s text-detection module (per the PP-OCRv5 detection module docs), with a `detect(image: np.ndarray) -> List[List[Tuple[int, int]]]` method returning polygon boxes, mirroring `predict.py:216-218`'s `detection_predictor([image])[0].bboxes` shape but backed by PaddleOCR instead of Surya (per the PRD: "PaddleOCR as detector").
  ```python
  class Detector:
      """Детектор строк текста на основе PaddleOCR"""

      def __init__(self):
          from paddleocr import PaddleOCR

          self._ocr = PaddleOCR(use_angle_cls=False, lang="ru", rec=False)

      def detect(self, image) -> List[List[Tuple[int, int]]]:
          """Возвращает список полигонов (боксов) строк текста"""
          try:
              result = self._ocr.ocr(image, rec=False)
              return result[0] if result else []
          except Exception as e:
              print(f"Ошибка детекции: {e}")
              return []
  ```
- **MIRROR**: predict.py:216-218 (call shape), and the try/except-and-return-empty resilience from `CONFIG_CONSTANTS`/`ERROR_HANDLING` patterns above.
- **IMPORTS**: `paddleocr.PaddleOCR` (lazy import inside `__init__` so `backend.config`/`backend.consensus` stay importable — and unit-inspectable — without the heavy model download firing).
- **GOTCHA**: PaddleOCR's `lang` parameter must match the target documents' language (Russian per the app's UI strings and `predict.py`'s `ru_dict_ext100124.txt`); confirm `lang="ru"` is actually supported by the installed PaddleOCR version at implementation time — fall back to a custom dict path only if not.
- **VALIDATE**: `Detector().detect(<test image array>)` returns a non-empty list of 4-point polygons on a real scanned page.

#### Task 6.4: Recognizer functions (Paddle + Surya only, this phase)
- **ACTION**: Create `backend/recognizers.py` with `recognize_paddle(crop) -> (text, score)` and `recognize_surya(image, box) -> (text, score)`.
- **IMPLEMENT**: Port `predict.py:230-233` (Paddle) and `predict.py:222-228` (Surya) call shapes 1:1, swapping the private `ocr` (`TextRecClsPipeline`) for the public `paddleocr.PaddleOCR(rec=True, det=False)` recognition-only call, and keeping `surya.recognition.RecognitionPredictor` / `surya.detection.DetectionPredictor` imports as-is (Surya is already public in `predict.py`, no swap needed there — the PRD's portability issue is specifically about `ocr_library`, not Surya).
- **MIRROR**: `DETECT_RECOGNIZE_VOTE_SHAPE` pattern above.
- **IMPORTS**: `paddleocr.PaddleOCR`, `surya.foundation.FoundationPredictor`, `surya.recognition.RecognitionPredictor` — all lazily instantiated once at module load inside a small `_Engines` holder (mirrors `predict.py:147-158`'s module-level instantiation, but without the hardcoded paths).
- **GOTCHA**: `predict.py` instantiates its models at import time (`ocr = TextRecClsPipeline(...)` etc. at module scope, `predict.py:147-158`) which loads weights on every import. Do the same lazy-once pattern but guard it so `backend/consensus.py`'s pure-logic functions can be exercised (manually, given no test framework) without forcing a multi-GB model download — instantiate engines inside `Detector.__init__`/a `Recognizers` class `__init__`, not at `backend/recognizers.py` module scope.
- **VALIDATE**: Given a single line-crop image, both functions return a `(str, float)` tuple with `0.0 <= score <= 1.0`.

#### Task 6.5: Consensus vote (binary agreement, this phase — generalized in Phase 7)
- **ACTION**: Create `backend/consensus.py` with `vote(results: Dict[str, Tuple[str, float]], threshold: float) -> Tuple[str, str, str]` returning `(bucket, chosen_text, chosen_engine)` where `bucket` is `"good"` or `"needs_review"`.
- **IMPLEMENT**: For this phase, port the exact binary check from `predict.py:244-258` (`if surya_text == paddle_text and paddle_text != ""`) generalized only to accept a `results` dict keyed by engine name, still 2-engine (`paddle`, `surya`) — Phase 7 adds the third vote and true majority logic on top of this same function signature.
- **MIRROR**: `DETECT_RECOGNIZE_VOTE_SHAPE` pattern above, `ERROR_HANDLING` pattern for any malformed input.
- **GOTCHA**: Keep `vote()` a pure function (no I/O, no Streamlit, no engine calls) so Phase 7's extension is a logic-only diff — this is the one module in the backend worth keeping side-effect-free even without a test framework, since it's the part most likely to need tweaking during the Phase 9 evaluation.
- **VALIDATE**: Manually call `vote({"paddle": ("привет", 0.9), "surya": ("привет", 0.8)}, 0.95)` → `("good", "привет", "paddle")`; call with disagreeing texts and a high/low score to confirm threshold routing.

#### Task 6.6: Pipeline orchestration
- **ACTION**: Create `backend/pipeline.py` with `run(input_dir: str, output_dir: str, threshold: float) -> Tuple[int, int]` (returns counts of good/needs-review lines).
- **IMPLEMENT**: Glob `input_dir` for `IMAGE_EXTENSIONS` files (this phase: images only, no PDF-page rendering — `predict.py`'s PDF text-layer path, `predict.py:26-99`, is out of scope; note as a known gap for Phase 9's evaluation if the real batch is PDFs), run `Detector.detect()` per image, crop each box (mirror `predict.py:230` cropping arithmetic, no random padding needed since this consumes existing crops rather than generating new training images), run both recognizers per crop, `vote()`, append to in-memory `good_lines`/`needs_review_lines` lists in the `FILE_FORMAT` shape, then write `output_dir/good.txt` and `output_dir/needs_review.txt`.
- **MIRROR**: `predict.py:167-261` overall loop shape; `FILE_FORMAT` pattern for the two output files; `save_image` (`predict.py:102-110`) for writing crops if the maintainer wants crop images alongside the txt files (needed only if Phase 8's import step re-crops rather than pointing at original page images — decide at implementation time based on whether `rec.txt`'s paths should point at original documents or generated crops; default to writing crops, since that's what makes the output directly importable as a fresh `rec.txt`-style folder matching the existing data model).
- **IMPORTS**: `backend.detector.Detector`, `backend.recognizers`, `backend.consensus.vote`, `backend.config`.
- **GOTCHA**: Wrap each per-image and per-crop iteration in its own try/except-and-continue (per `ERROR_HANDLING`/`DETECT_RECOGNIZE_VOTE_SHAPE`) — one corrupt image or one engine exception must not abort the whole batch, exactly matching `predict.py:259-260`'s existing tolerance.
- **VALIDATE**: `run()` against a small real folder produces non-empty `good.txt`/`needs_review.txt` in the expected `path\ttext\n` format; spot-check a few lines by opening the referenced crop images.

#### Task 6.7: Job store + background execution
- **ACTION**: Create `backend/jobs.py`.
- **IMPLEMENT**: A minimal in-memory `Dict[str, JobState]` (`JobState` as a `@dataclass` with `status: Literal["running","done","error"]`, `result: Optional[dict]`, `error: Optional[str]`), a `start_job(input_dir, output_dir, threshold) -> str` that generates a `uuid4` job id, launches `pipeline.run()` on a background `threading.Thread`, and updates the dict on completion/exception.
- **MIRROR**: `DATACLASS_MODEL` pattern.
- **GOTCHA**: No persistence — a backend restart loses in-flight job state, which is acceptable per NOT-Building above; document this explicitly in a module docstring so it isn't mistaken for a bug later.
- **VALIDATE**: `start_job(...)` returns immediately (non-blocking) even though `pipeline.run()` takes real wall-clock time; polling the dict shows `"running"` then `"done"`.

#### Task 6.8: FastAPI app
- **ACTION**: Create `backend/main.py`.
- **IMPLEMENT**:
  ```python
  from fastapi import FastAPI, HTTPException
  from pydantic import BaseModel

  from backend.config import DEFAULT_SCORE_THRESHOLD
  from backend.jobs import get_job, start_job

  app = FastAPI(title="OCR Consensus Backend")


  class RunRequest(BaseModel):
      input_dir: str
      output_dir: str
      score_threshold: float = DEFAULT_SCORE_THRESHOLD


  @app.post("/run")
  def run(req: RunRequest):
      job_id = start_job(req.input_dir, req.output_dir, req.score_threshold)
      return {"job_id": job_id}


  @app.get("/status/{job_id}")
  def status(job_id: str):
      job = get_job(job_id)
      if job is None:
          raise HTTPException(404, "Job not found")
      return {"status": job.status, "error": job.error}


  @app.get("/result/{job_id}")
  def result(job_id: str):
      job = get_job(job_id)
      if job is None or job.status != "done":
          raise HTTPException(404, "Result not ready")
      return job.result
  ```
- **MIRROR**: This is the one file that deliberately does NOT mirror the Russian-docstring/broad-try-except app convention — it's a thin FastAPI routing layer; keep it that way and put all real logic (including error messages, which CAN stay Russian) in `pipeline.py`/`jobs.py`.
- **IMPORTS**: `fastapi`, `pydantic`, `backend.jobs`, `backend.config`.
- **GOTCHA**: Bind to `127.0.0.1` only (never `0.0.0.0`) when documenting the run command — this is a localhost-only spike with no auth, per NOT-Building.
- **VALIDATE**: `uvicorn backend.main:app --host 127.0.0.1 --port 8756`, then `curl -X POST localhost:8756/run -d '{"input_dir": "...", "output_dir": "..."}' -H "Content-Type: application/json"` returns a `job_id`; polling `/status/{job_id}` reaches `"done"`.

#### Task 6.9: Update PRD phase status
- **ACTION**: Flip Phase 6's row to `complete` once Task 6.8's validation passes end-to-end on a real batch (2-engine only).
- **VALIDATE**: PRD table reflects reality.

---

### Phase 7 — Add Tesseract + Real 2-of-3 Vote + Configurable Threshold/Override

#### Task 7.1: Tesseract recognizer
- **ACTION**: Add `recognize_tesseract(crop) -> Tuple[str, float]` to `backend/recognizers.py`.
- **IMPLEMENT**:
  ```python
  def recognize_tesseract(crop) -> Tuple[str, float]:
      """Распознавание текста через Tesseract"""
      try:
          import pytesseract
          from pytesseract import Output

          data = pytesseract.image_to_data(
              crop, lang="rus", output_type=Output.DICT
          )
          words = [
              (w, c) for w, c in zip(data["text"], data["conf"]) if int(c) != -1 and w.strip()
          ]
          if not words:
              return "", 0.0
          text = " ".join(w for w, _ in words)
          avg_conf = sum(int(c) for _, c in words) / len(words) / 100.0
          return text, avg_conf
      except Exception as e:
          print(f"Ошибка Tesseract: {e}")
          return "", 0.0
  ```
- **MIRROR**: `ERROR_HANDLING`, `DETECT_RECOGNIZE_VOTE_SHAPE`.
- **GOTCHA**: Requires the system `tesseract-ocr` binary AND the `rus` language pack installed separately from `pip install pytesseract` (pytesseract is a wrapper, not a bundled binary) — document this as a manual OS-level install step in `backend/requirements.txt`'s neighboring README note, and confirm with `tesseract --list-langs` includes `rus` before relying on it.
- **VALIDATE**: On a known-text crop, `recognize_tesseract()` returns non-empty text with a score in `[0, 1]`.

#### Task 7.2: Generalize `vote()` to true 3-engine majority
- **ACTION**: Rewrite `backend/consensus.py::vote()` to accept `results: Dict[str, Tuple[str, float]]` with 3 entries and a `preferred_model: Optional[str]`.
- **IMPLEMENT**:
  ```python
  from collections import Counter


  def vote(
      results: Dict[str, Tuple[str, float]],
      threshold: float,
      preferred_model: Optional[str] = None,
  ) -> Tuple[str, str, str]:
      """Голосование по результатам трёх движков: (bucket, text, engine)"""
      texts = [text for text, _ in results.values() if text]
      if texts:
          counts = Counter(texts)
          winner_text, winner_count = counts.most_common(1)[0]
          if winner_count >= 2:
              winner_engine = next(
                  eng for eng, (text, _) in results.items() if text == winner_text
              )
              return "good", winner_text, winner_engine

      if preferred_model and preferred_model in results:
          text, score = results[preferred_model]
          if score >= threshold:
              return "good", text, preferred_model

      best_engine = max(results, key=lambda eng: results[eng][1])
      best_text, best_score = results[best_engine]
      if best_score >= threshold:
          return "good", best_text, best_engine

      return "needs_review", best_text, best_engine
  ```
- **MIRROR**: `DETECT_RECOGNIZE_VOTE_SHAPE` pattern's routing structure, generalized from binary to `Counter`-based majority per the PRD's explicit "generalize the 2-way exact-match check into a real 2-of-3 vote" requirement.
- **GOTCHA**: Preserve `vote()`'s pure-function property from Task 6.5 — still no I/O, still fully unit-callable by hand. The `preferred_model` override must only kick in when there's NO 2-of-3 majority (i.e., all three engines disagree) — a genuine majority always wins over the override, matching the PRD's "2-of-3 agreement → auto-label ... otherwise [threshold/override]" phrasing.
- **VALIDATE**: Manually exercise all four branches: (a) 2-of-3 exact match → `"good"` via majority; (b) full disagreement + `preferred_model` above threshold → `"good"` via override; (c) full disagreement, no override, best score above threshold → `"good"` via threshold; (d) full disagreement, everything below threshold → `"needs_review"`.

#### Task 7.3: Wire Tesseract + threshold/override into the pipeline and API
- **ACTION**: Update `backend/pipeline.py::run()` to call all three recognizers per crop and pass `preferred_model` through; update `backend/main.py`'s `RunRequest` to add `preferred_model: Optional[str] = None`.
- **IMPLEMENT**: `results = {"paddle": recognize_paddle(crop), "surya": recognize_surya(...), "tesseract": recognize_tesseract(crop)}`, then `vote(results, threshold, preferred_model)`.
- **MIRROR**: Task 6.6/6.8 shapes, extended.
- **GOTCHA**: Running 3 recognizers per crop roughly triples per-line latency versus Phase 6 — if this makes real-batch runs impractically slow during Phase 9, that's a legitimate finding to note in the Phase 9 evaluation, not something to silently optimize away here (no perf work is in scope for this plan).
- **VALIDATE**: End-to-end run against the same batch used in Task 6.6's validation now produces different (presumably better-routed) `good.txt`/`needs_review.txt` splits reflecting the 3-way vote.

#### Task 7.4: Update PRD phase status
- **ACTION**: Flip Phase 7's row to `complete`.
- **VALIDATE**: PRD table reflects reality; note in the Decisions Log whether Tesseract integration hit the "time-box, fall back to 2-engine" mitigation from the PRD's Technical Risks table, or shipped clean.

---

### Phase 8 — Wire Spike Into the Labeling App

#### Task 8.1: Add `requests` to the app's requirements
- **ACTION**: Update `requirements.txt` (root).
- **IMPLEMENT**: Append `requests==2.32.3`.
- **GOTCHA**: This is the ONLY root-`requirements.txt` change in this entire plan — do not add any backend package here, per the PRD's explicit "Won't Building" scope boundary.
- **VALIDATE**: `pip install -r requirements.txt` still succeeds and stays free of ML packages.

#### Task 8.2: Consensus UI section
- **ACTION**: Create `src/ui/consensus_view.py`.
- **IMPLEMENT**:
  ```python
  import requests
  import streamlit as st

  from src.annotations import AnnotationManager

  BACKEND_URL = "http://127.0.0.1:8756"


  def render_consensus_section(manager: AnnotationManager):
      """Отрисовывает секцию запуска и импорта OCR-консенсуса"""
      st.sidebar.divider()
      st.sidebar.header("🤖 Консенсус OCR")

      input_dir = st.sidebar.text_input("Папка с документами", key="consensus_input")
      output_dir = st.sidebar.text_input("Папка вывода", key="consensus_output")
      threshold = st.sidebar.slider(
          "Порог уверенности", 0.0, 1.0, 0.95, key="consensus_threshold"
      )
      preferred = st.sidebar.selectbox(
          "Предпочитаемая модель (при разногласии)",
          [None, "paddle", "surya", "tesseract"],
          key="consensus_preferred",
      )

      if st.sidebar.button("▶ Запустить", key="consensus_run"):
          try:
              resp = requests.post(
                  f"{BACKEND_URL}/run",
                  json={
                      "input_dir": input_dir,
                      "output_dir": output_dir,
                      "score_threshold": threshold,
                      "preferred_model": preferred,
                  },
                  timeout=5,
              )
              resp.raise_for_status()
              st.session_state.consensus_job_id = resp.json()["job_id"]
              st.sidebar.success("Запущено")
          except Exception as e:
              st.sidebar.error(f"Ошибка запуска: {e}")

      if st.session_state.get("consensus_job_id"):
          if st.sidebar.button("🔄 Статус", key="consensus_status"):
              try:
                  resp = requests.get(
                      f"{BACKEND_URL}/status/{st.session_state.consensus_job_id}",
                      timeout=5,
                  )
                  resp.raise_for_status()
                  st.sidebar.info(resp.json()["status"])
              except Exception as e:
                  st.sidebar.error(f"Ошибка статуса: {e}")

          if st.sidebar.button("📥 Импортировать", key="consensus_import"):
              _import_results(manager, output_dir)


  def _import_results(manager: AnnotationManager, output_dir: str):
      """Импортирует good.txt/needs_review.txt в текущий AnnotationManager"""
      try:
          import os

          for fname, mark_as_done in (("good.txt", True), ("needs_review.txt", False)):
              path = os.path.join(output_dir, fname)
              if not os.path.exists(path):
                  continue
              with open(path, "r", encoding="utf-8") as f:
                  contents = f.read()
              success, error = manager.load_from_file(contents)
              if not success:
                  st.sidebar.error(f"{fname}: {error}")
                  continue
              if mark_as_done:
                  for name in manager.get_image_list("all"):
                      manager.records[name].is_marked = True
                      manager.modified_records.add(name)
          st.sidebar.success("Импортировано")
      except Exception as e:
          st.sidebar.error(f"Ошибка импорта: {e}")
  ```
- **MIRROR**: `SIDEBAR_SECTION_PATTERN`, `ERROR_HANDLING` (broad try/except + `st.sidebar.error` in Russian, matching the rest of the app's convention).
- **IMPORTS**: `requests`, `streamlit as st`, `src.annotations.AnnotationManager`.
- **GOTCHA**: `AnnotationManager.load_from_file` (see `src/annotations.py:23-58`) merges by image *filename*, not full path, and OVERWRITES any existing record with the same name (`self.records[img_name] = ImageRecord(...)`) — if the maintainer's working batch already has entries for the same filenames, importing will silently replace their existing (possibly hand-corrected) annotations. Call this out as a visible warning in the sidebar before the import button, e.g. `st.sidebar.caption("⚠️ Перезапишет существующие записи с тем же именем файла")`, rather than adding new merge logic to `AnnotationManager` (out of scope for this plan — flagging risk, not re-architecting the merge).
- **VALIDATE**: With the backend running and a completed job, clicking "📥 Импортировать" populates `manager.records` from `good.txt`/`needs_review.txt`, visible immediately in the existing list/editor views without any other code change.

#### Task 8.3: Wire into the sidebar
- **ACTION**: Update `src/ui/sidebar.py`.
- **IMPLEMENT**: Add `from src.ui.consensus_view import render_consensus_section` at the top, and `render_consensus_section(manager)` as the last line of `render_sidebar()`.
- **MIRROR**: Existing import/call style already in this file.
- **VALIDATE**: Running `app1.py` shows the new "🤖 Консенсус OCR" section below "🗂️ Бэкапы" in the sidebar.

#### Task 8.4: Update PRD phase status
- **ACTION**: Flip Phase 8's row to `complete` once a real end-to-end run→status→import cycle works against the running backend.
- **VALIDATE**: PRD table reflects reality.

---

### Phase 9 — Subjective Evaluation

#### Task 9.1: Run against a real batch
- **ACTION**: Run `streamlit run app1.py --server.enableXsrfProtection=false` and `uvicorn backend.main:app --host 127.0.0.1 --port 8756` side by side; point the consensus section at a real folder of documents the maintainer would otherwise label by hand.
- **IMPLEMENT**: Execute the full run → status → import flow from Task 8.2/8.3's validation, then manually review the imported "good" bucket's accuracy and the "needs_review" bucket's usefulness by eyeballing a representative sample inside the existing `app1.py` editor.
- **VALIDATE**: Both buckets are populated and browsable in the app; the maintainer has actually looked at real output, not just confirmed the pipeline runs.

#### Task 9.2: Record the subjective judgment and go/no-go
- **ACTION**: Add a dated entry to the PRD's Decisions Log (`ocr-markup-v2.prd.md`, after the existing table) capturing: felt time saved vs. manual labeling, "good" bucket's actual accuracy on spot-check, whether Tesseract's 3-way vote changed the outcome meaningfully versus the Phase 6 2-engine version, and the go/no-go call referenced in PRD Open Question #3 (retire, narrow, or invest further).
- **IMPLEMENT**: A new row: `| Consensus spike outcome | <keep as-is / narrow to N engines / retire> | <alternatives considered> | <the subjective evidence from Task 9.1> |`.
- **GOTCHA**: This is deliberately a judgment call recorded in prose/table form, not a metric — per the PRD's explicit "Formal accuracy benchmarking... not building" scope decision. Resist the urge to build measurement tooling here.
- **VALIDATE**: The Decisions Log entry exists and is specific enough that a future reader understands *why* the go/no-go call was made, not just what it was.

#### Task 9.3: Update PRD phase status
- **ACTION**: Flip Phase 9's row to `complete`, and update the PRD's overall `Status: DRAFT - needs validation` header note to reflect the spike's outcome (e.g. `Status: Track A shipped, Track B spike evaluated — see Decisions Log`).
- **VALIDATE**: PRD is internally consistent — every phase 5-9 row is `complete`, the Decisions Log has the go/no-go entry, and the header no longer says "needs validation" without qualification.

---

## Testing Strategy

No test framework exists in this repo (confirmed via `CLAUDE.md` and direct inspection) — all validation below is manual, matching the project's established convention.

### Manual Validation Matrix

| Area | How | Pass Signal |
|---|---|---|
| Phase 5 regression | Full checklist walk-through in a running `app1.py` | Every checklist row ✅ |
| Backend detection | `Detector().detect()` on a real page | Non-empty polygon list roughly matching visible text lines |
| Backend recognition | Each `recognize_*` on a hand-picked crop with known text | Returned text is a reasonable transcription, score in `[0,1]` |
| `vote()` logic | Manual calls covering all 4 branches (Task 7.2) | Each branch returns the expected `(bucket, text, engine)` |
| Full pipeline | `run()` against a small real folder | `good.txt`/`needs_review.txt` non-empty, correct `path\ttext\n` format |
| API | `curl`/Postman against `/run`, `/status/{id}`, `/result/{id}` | Job id issued, status transitions running→done, result matches pipeline output |
| App-side import | Click through Task 8.2's UI against a completed job | Records appear in `app1.py`'s list/editor with correct marked/unmarked state |
| End-to-end spike | Task 9.1 | Maintainer forms a genuine subjective opinion on time saved |

### Edge Cases Checklist
- [ ] Empty input folder (backend should return empty buckets, not crash)
- [ ] A single corrupt/unreadable image in the batch (must not abort the whole run — see Task 6.6 GOTCHA)
- [ ] All three engines disagree with all scores below threshold (→ `needs_review`, Task 7.2 branch d)
- [ ] `preferred_model` set to an engine name not present in `results` (must not crash `vote()` — falls through to best-score branch)
- [ ] Re-running `/run` against the same `output_dir` (decide/confirm at implementation time whether it overwrites or the maintainer must clear it manually — document whichever behavior ships)
- [ ] Importing into `app1.py` when filenames collide with already-labeled entries (Task 8.2 GOTCHA — confirm the warning is visible, not just theoretical)
- [ ] Backend not running when the sidebar's "▶ Запустить" is clicked (must show a clean Russian error, not an unhandled stack trace in the Streamlit UI)

---

## Validation Commands

### Backend dependency install
```bash
pip install -r backend/requirements.txt
```
EXPECT: Succeeds without touching the root venv's Streamlit/Pillow versions if run in a separate venv (recommended, not enforced by this plan).

### Backend smoke test
```bash
uvicorn backend.main:app --host 127.0.0.1 --port 8756
```
EXPECT: Starts without import errors; `curl http://127.0.0.1:8756/docs` returns the FastAPI Swagger UI.

### App smoke test
```bash
streamlit run app1.py --server.enableXsrfProtection=false
```
EXPECT: App loads exactly as before Phase 8, plus the new "🤖 Консенсус OCR" sidebar section.

### Manual Validation
- [ ] Phase 5 checklist fully executed and ✅
- [ ] Backend runs a real batch end-to-end (Phase 6+7)
- [ ] Import flow moves consensus output into `app1.py`'s data model (Phase 8)
- [ ] Subjective go/no-go recorded in the PRD (Phase 9)

---

## Acceptance Criteria
- [ ] All tasks completed
- [ ] All validation commands pass
- [ ] No regressions found in Phase 5 (or all found regressions fixed and re-verified)
- [ ] Backend runs against a real document batch without crashing on a full pass
- [ ] `good.txt`/`needs_review.txt` import cleanly into `app1.py` via the new sidebar section
- [ ] PRD phases 5-9 all flipped to `complete`, with the Phase 9 go/no-go decision recorded

## Completion Checklist
- [ ] Code follows discovered patterns (dataclass models, broad try/except + Russian messages, tab-separated `rec.txt` shape)
- [ ] Error handling matches codebase style throughout `backend/`
- [ ] No hardcoded local model paths anywhere in `backend/` (the whole point of Phase 6)
- [ ] No ML dependency leaked into root `requirements.txt` or `pyinst_command.txt`
- [ ] No unnecessary scope additions (no job persistence, no auth, no shared-constants refactor, no VLM engines)
- [ ] Self-contained — no questions needed during implementation beyond the transport decision already resolved (REST over localhost)

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| PaddleOCR's public detection module API differs meaningfully from what's documented at plan time (fast-moving library) | M | M | Task 6.3 explicitly calls out verifying `lang="ru"` support and the exact call shape against the installed version before building on top of it |
| Tesseract Russian-language pack isn't installed/available in the target environment | M | M | PRD's own mitigation: time-box Tesseract, fall back to 2-engine consensus (Phase 6's shape) if blocked — Task 7.4 explicitly records whether this happened |
| Running 3 ML engines per crop is too slow for a real batch, stalling Phase 9's evaluation before a subjective judgment can even form | M | M | Task 7.3 explicitly treats slowness as a valid Phase 9 finding rather than something to silently optimize; no perf work is in this plan's scope |
| Import step (Task 8.2) silently overwrites hand-corrected existing labels with same-named consensus output | M | H | Explicit UI warning caption before the import button (Task 8.2 GOTCHA) — accepted as sufficient for a single-operator spike rather than building real merge/diff logic |
| Backend and app drift on the `IMAGE_EXTENSIONS` tuple over time (already inconsistent between `predict.py` and `annotations.py` today) | L | L | Task 6.2 explicitly matches `annotations.py`'s dotted style; documented as a known pre-existing inconsistency, not fixed repo-wide (out of scope) |

## Notes
- Phases 1-4 (Track A) are further along in the working tree than the PRD's `in-progress` status suggests — this plan verified that directly (see "Current State" section) rather than trusting the PRD's status column, and Phase 5 can proceed immediately without waiting on any further Track A work.
- The transport decision for Phases 6-9 (REST over localhost vs. filesystem drop) was resolved with the maintainer before writing this plan: **REST over localhost**, using FastAPI + a simple in-memory job store (no queue, no persistence) since this is a single-operator, single-concurrent-job spike.
- The two PRD open questions about model portability (#2) and Tesseract licensing (#4) are resolved by design in this plan: dropping `ocr_library` in favor of the public `paddleocr`/`surya-ocr` packages (which self-manage model downloads/caching) removes the hardcoded-path problem, and Tesseract's Apache-2.0 licensing (both `pytesseract` and the system binary) has no blocker for internal use.
