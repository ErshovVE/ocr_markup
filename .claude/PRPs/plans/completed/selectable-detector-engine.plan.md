# Plan: Selectable Detector Engine

## Summary
The line-detection step of the OCR consensus pipeline is hard-wired to
PaddleOCR's `TextDetection` (PP-OCRv6). This plan makes the detector an
independent, user-selectable engine (`paddle` | `surya` | `tesseract`),
decoupled from recognition — recognition already always runs all 3 engines
and votes; only the box-producing detector was single-choice.

## User Story
As a maintainer running the OCR-consensus backend,
I want to choose which engine detects text-line boxes (PaddleOCR, SuryaOCR,
or Tesseract) independently of the recognition consensus,
So that I can work around a detector that performs poorly on a given
document type without being stuck with PaddleOCR.

## Problem → Solution
Currently `backend/detector.py`'s `Detector` class always instantiates
`paddleocr.TextDetection` — no parameter anywhere (pipeline, jobs, API,
UI) lets a caller pick a different detector. →
`Detector` gains an `engine` parameter (`paddle`/`surya`/`tesseract`),
threaded end-to-end through `pipeline.run` → `jobs.start_job` →
`POST /run` (`RunRequest.detector_engine`) → the Streamlit UI, with
model-readiness tracking in `models_status.py` extended to cover the two
new downloadable detector models (Paddle detection model, Surya detection
model — both distinct downloads from the recognition models already
tracked).

## Metadata
- **Complexity**: Medium
- **Source PRD**: N/A
- **PRD Phase**: N/A
- **Estimated Files**: 9

---

## UX Design

### Before
```
┌─────────────────────────────────────────────┐
│ 🤖 Авторазметка                              │
│                                               │
│ Модели                                       │
│  PaddleOCR   ✅ Готово                        │
│  SuryaOCR    ⚪ Не проверено      [Скачать]   │
│  Tesseract   ✅ Готово                        │
│ ───────────────────────────────────────────  │
│ Папка с документами: [___________]           │
│ Папка вывода:        [___________]           │
│ Предпочитаемая модель: [paddle ▾]            │
│ ☑ Извлекать текст из PDF напрямую            │
│ Порог уверенности: ──●──────                 │
│ [▶ Запустить]                                │
└─────────────────────────────────────────────┘
Детектор строк — всегда PaddleOCR, без возможности выбора.
```

### After
```
┌─────────────────────────────────────────────┐
│ 🤖 Авторазметка                              │
│                                               │
│ Модели распознавания                         │
│  PaddleOCR   ✅ Готово                        │
│  SuryaOCR    ⚪ Не проверено      [Скачать]   │
│  Tesseract   ✅ Готово                        │
│                                               │
│ Модели детекции строк                        │
│  PaddleOCR   ✅ Готово                        │
│  SuryaOCR    ⚪ Не проверено      [Скачать]   │
│  Tesseract   ✅ Готово                        │
│ ───────────────────────────────────────────  │
│ Папка с документами: [___________]           │
│ Папка вывода:        [___________]           │
│ Детектор строк текста: [paddle ▾]  ← NEW      │
│ Предпочитаемая модель: [paddle ▾]            │
│ ☑ Извлекать текст из PDF напрямую            │
│ Порог уверенности: ──●──────                 │
│ [▶ Запустить]                                │
└─────────────────────────────────────────────┘
Детектор строк выбирается независимо от консенсуса распознавания.
```

### Interaction Changes
| Touchpoint | Before | After | Notes |
|---|---|---|---|
| "Модели" panel | Single list (recognition engines) | Two lists: "Модели распознавания" + "Модели детекции строк" | Detection models for paddle/surya are separate downloads from recognition models |
| Run controls | No detector choice | New selectbox "Детектор строк текста" (paddle/surya/tesseract, default paddle) | Sent as `detector_engine` in `POST /run` |
| `/models/prepare` | `model` ∈ {paddle, surya} (recognition only) | `model` ∈ {paddle, surya, paddle_detector, surya_detector} | Backward compatible — existing values unchanged |

---

## Mandatory Reading

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | [backend/detector.py](backend/detector.py) | 1-22 | The class being rewritten — current hardcoded PaddleOCR-only detector, including the `enable_mkldnn=False` workaround that must be preserved |
| P0 | [backend/recognizers.py](backend/recognizers.py) | 1-48 | `_Engines` lazy-holder pattern to mirror exactly for detector engines |
| P0 | [backend/pipeline.py](backend/pipeline.py) | 170-254 | Where `Detector()` is instantiated (`get_detector()` closure) and how `tesseract_lang` is computed/threaded — new `detector_engine` param plugs in here |
| P0 | [backend/main.py](backend/main.py) | 1-60 | `RunRequest` + `/run` validation pattern (`lang`, `latin_model_size`) to mirror for `detector_engine` |
| P0 | [backend/jobs.py](backend/jobs.py) | 1-89 | Positional param threading from `start_job` → `_run_job` → `pipeline.run` — new param must be added in the same position across all three |
| P0 | [backend/models_status.py](backend/models_status.py) | 1-69 | `_state` dict + `_prepare()` dispatch + `prepare()` — new detector-readiness keys plug in here |
| P1 | [backend/tests/test_models_status.py](backend/tests/test_models_status.py) | 1-62 | Test fixture (`reset_model_state`) and test style to mirror for the two new state keys |
| P1 | [frontend/src/ui/generation_view.py](frontend/src/ui/generation_view.py) | 1-149 | `ENGINES` tuple, `_render_model_status()`, `_render_run_controls()` — UI wiring |
| P2 | [backend/README.md](backend/README.md) | all | API doc to update (`/run`, `/models/status`, `/models/prepare`) |
| P2 | [docs/CODEMAPS/backend.md](docs/CODEMAPS/backend.md) | all | Generated codemap — regenerate after implementation (not hand-edited) |

## External Documentation

| Topic | Source | Key Takeaway |
|---|---|---|
| Surya `DetectionPredictor` API | [github.com/datalab-to/surya](https://github.com/datalab-to/surya) | `from surya.detection import DetectionPredictor; det_predictor = DetectionPredictor(); predictions = det_predictor([pil_image])`. Detection is a plain torch model — **no** `FoundationPredictor` needed (unlike `RecognitionPredictor` in `recognizers.py`). Returns per-image result with a `bboxes` collection; each box carries `polygon` (4 points, clockwise from top-left, matching the format `pipeline.py` already assumes: `box[0]`=top-left, `box[2]`=bottom-right) and `confidence`. |
| Surya return-shape ambiguity | search results disagreed on dict-vs-attribute access for box fields | **GOTCHA**: not verified against the installed `surya-ocr==0.16.0` package (not present in this environment). Write the polygon extraction defensively (see `_extract_polygon` in Task 1) so it works whether `box.polygon` is an attribute or `box["polygon"]` is a dict key. Verify against the real package during implementation and simplify if only one shape is ever hit. |
| PaddleOCR `TextDetection` output | [PaddleOCR docs](https://paddlepaddle.github.io/PaddleOCR/main/en/version3.x/module_usage/text_detection.html) | Unchanged from current code — `predict()` returns `dt_polys` (4-point int16 polygons). No new research needed, only relocated into `_detect_paddle`. |
| pytesseract `image_to_data` line grouping | existing `recognize_tesseract` in `backend/recognizers.py:92-111` | No official "line box" API — group word-level rows by `(block_num, par_num, line_num)` and take the min/max of `(left, top, left+width, top+height)` per group, mirroring the existing `int(c) != -1` confidence-filter idiom already used for recognition. |

---

## Patterns to Mirror

### LAZY_ENGINE_HOLDER
// SOURCE: backend/recognizers.py:7-47
```python
class _Engines:
    """Ленивый холдер тяжёлых моделей распознавания (Paddle, Surya)"""

    _paddle_cyrillic = None
    _paddle_latin = {}
    _foundation_predictor = None
    _recognition_predictor = None

    @classmethod
    def paddle_cyrillic(cls):
        if cls._paddle_cyrillic is None:
            from paddleocr import TextRecognition

            cls._paddle_cyrillic = TextRecognition(
                model_name="cyrillic_PP-OCRv5_mobile_rec", enable_mkldnn=False
            )
        return cls._paddle_cyrillic
```
Mirror this exactly in `backend/detector.py` for `paddle`/`surya` detector
instances (imports stay lazy, inside the classmethod body).

### VALUE_VALIDATION_ERROR
// SOURCE: backend/recognizers.py:26-28
```python
    def paddle_latin(cls, model_size: str = DEFAULT_LATIN_MODEL_SIZE):
        if model_size not in LATIN_MODEL_SIZES:
            raise ValueError(f"Неизвестный размер модели PP-OCRv6: {model_size}")
```
Mirror for `Detector.__init__` rejecting an unknown `engine`.

### API_FIELD_VALIDATION
// SOURCE: backend/main.py:42-49
```python
    if req.lang not in ("ru", "latin"):
        raise HTTPException(400, f"lang должен быть 'ru' или 'latin': {req.lang}")
    if req.latin_model_size not in LATIN_MODEL_SIZES:
        raise HTTPException(
            400,
            f"latin_model_size должен быть одним из {LATIN_MODEL_SIZES}: "
            f"{req.latin_model_size}",
        )
```
Mirror for `detector_engine` validation in `POST /run`.

### POSITIONAL_PARAM_THREADING
// SOURCE: backend/jobs.py:29-88
```python
def _run_job(
    job_id: str,
    input_dir: str,
    output_dir: str,
    threshold: float,
    preferred_model: Optional[str],
    lang: str,
    latin_model_size: str,
    extract_pdf_text_layer: bool,
):
    try:
        good_count, needs_review_count = pipeline.run(
            input_dir, output_dir, threshold, preferred_model, lang,
            latin_model_size, extract_pdf_text_layer,
        )
```
New `detector_engine` param is appended **last** in `run()`,
`start_job()`, and `_run_job()` signatures (and the matching call sites) —
appending avoids reordering existing positional args across 3 files.

### MODEL_STATUS_STATE_AND_PREPARE
// SOURCE: backend/models_status.py:22-68
```python
_state: Dict[str, ModelState] = {"paddle": ModelState(), "surya": ModelState()}
...
def _prepare(name: str):
    with _lock:
        _state[name] = ModelState("checking")
    try:
        from backend.recognizers import _Engines

        if name == "paddle":
            _Engines.paddle_cyrillic()
        elif name == "surya":
            _Engines.surya_recognition()
        with _lock:
            _state[name] = ModelState("ready")
    except Exception as e:
        with _lock:
            _state[name] = ModelState("error", str(e))
```
Extend `_state` with `"paddle_detector"` / `"surya_detector"` keys and add
matching `elif` branches in `_prepare`, importing `backend.detector._Engines`
lazily (same style).

### MODEL_STATUS_TEST_FIXTURE
// SOURCE: backend/tests/test_models_status.py:8-19
```python
@pytest.fixture(autouse=True)
def reset_model_state():
    """Изолирует тесты друг от друга — _state общий module-level словарь"""
    models_status._state = {
        "paddle": models_status.ModelState(),
        "surya": models_status.ModelState(),
    }
    yield
    models_status._state = {
        "paddle": models_status.ModelState(),
        "surya": models_status.ModelState(),
    }
```
Add the two new keys to both dict literals in this fixture.

### STREAMLIT_ENGINE_STATUS_ROW
// SOURCE: frontend/src/ui/generation_view.py:26-60
```python
ENGINES = (("paddle", "PaddleOCR"), ("surya", "SuryaOCR"), ("tesseract", "Tesseract"))

def _render_model_status():
    st.subheader("Модели")
    ...
    for name, label in ENGINES:
        info = st.session_state.models_status_cache.get(name, {})
        status = info.get("status", "not_checked")
        col1, col2, col3 = st.columns([2, 2, 1])
        col1.write(label)
        col2.write(STATUS_LABELS.get(status, status))
        if name != "tesseract" and status not in ("ready", "checking"):
            if col3.button("Скачать", key=f"prepare_{name}"):
                ...
```
Extract the per-row body (columns + button + caption) into a small helper
`_render_engine_status_row(label, status_key, prepare_name, key_prefix)` and
call it twice — once per `ENGINES` entry for recognition (unchanged status
keys), once per `ENGINES` entry for detection (status keys
`paddle_detector`/`surya_detector`/`tesseract`, prepare name `None` for
tesseract). This removes duplication between the two now-near-identical
loops without inventing new architecture.

### STREAMLIT_SELECTBOX_IN_RUN_PAYLOAD
// SOURCE: frontend/src/ui/generation_view.py:66-90
```python
    preferred = st.selectbox(
        "Предпочитаемая модель (при разногласии)",
        [None, "paddle", "surya", "tesseract"],
        key="consensus_preferred",
    )
    ...
    if st.button("▶ Запустить", key="consensus_run"):
        try:
            resp = requests.post(
                f"{BACKEND_URL}/run",
                json={
                    "input_dir": input_dir,
                    "output_dir": output_dir,
                    "score_threshold": threshold,
                    "preferred_model": preferred,
                    "extract_pdf_text_layer": extract_pdf_text_layer,
                },
                timeout=5,
            )
```
Mirror for the new `detector_engine` selectbox (no `None` option — always
has a concrete default, `"paddle"`), added to the same `json={...}` payload.

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `backend/detector.py` | REWRITE | Replace hardcoded `PaddleOCR`-only `Detector` with an engine-selectable class (`paddle`/`surya`/`tesseract`) plus a `_Engines` lazy holder, mirroring `recognizers.py` |
| `backend/pipeline.py` | UPDATE | Add `detector_engine` param to `run()`; pass it (+ existing `tesseract_lang`) into `Detector(...)` inside the `get_detector()` closure |
| `backend/jobs.py` | UPDATE | Thread `detector_engine` through `start_job()` / `_run_job()` (appended last) |
| `backend/main.py` | UPDATE | Add `detector_engine: str = DEFAULT_DETECTOR_ENGINE` to `RunRequest`, validate against `DETECTOR_ENGINES`, pass to `start_job` |
| `backend/models_status.py` | UPDATE | Add `"paddle_detector"`/`"surya_detector"` to `_state`; extend `_prepare()` dispatch to instantiate the corresponding detector engine |
| `backend/tests/test_models_status.py` | UPDATE | Add the two new keys to the `reset_model_state` fixture; add `test_prepare_success_sets_ready`/failure tests for `paddle_detector` and `surya_detector` mirroring the existing `paddle` tests |
| `backend/README.md` | UPDATE | Document `detector_engine` field on `POST /run`, and the two new `/models/status`/`/models/prepare` keys |
| `frontend/src/ui/generation_view.py` | UPDATE | Add "Модели детекции строк" status subsection + "Детектор строк текста" selectbox wired into the `/run` payload |
| `docs/CODEMAPS/backend.md` | REGENERATE | Run `/update-codemaps` after implementation (generated file, not hand-authored) |

## NOT Building

- No change to the recognition consensus itself — all 3 recognizers still
  always run per detected box; `preferred_model` remains a tie-break only,
  unrelated to the new `detector_engine` selection.
- No per-document/per-page detector override — one `detector_engine` per
  `/run` call, same granularity as `lang`/`preferred_model` today.
- No new Surya "layout" detection (regions/labels) — only Surya's
  line-level `DetectionPredictor`, matching what PaddleOCR's `TextDetection`
  already produces (line boxes, not layout classification).
- No persistence of the chosen detector across backend restarts — matches
  the existing no-persistence design of `jobs.py`/`models_status.py`.
- No confidence-based filtering of Surya detection boxes — mirrors the
  current PaddleOCR behavior of returning all `dt_polys` unfiltered.

---

## Step-by-Step Tasks

### Task 1: Rewrite `backend/detector.py` with engine selection
- **ACTION**: Replace the current hardcoded-PaddleOCR `Detector` class with
  an engine-selectable version plus a `_Engines` lazy holder.
- **IMPLEMENT**:
  ```python
  from typing import List, Tuple

  DETECTOR_ENGINES = ("paddle", "surya", "tesseract")
  DEFAULT_DETECTOR_ENGINE = "paddle"


  class _Engines:
      """Ленивый холдер тяжёлых моделей детекции (Paddle, Surya)"""

      _paddle = None
      _surya = None

      @classmethod
      def paddle(cls):
          if cls._paddle is None:
              from paddleocr import TextDetection

              # enable_mkldnn=False: с oneDNN включённым PP-OCRv6_medium_det
              # падает с "ConvertPirAttribute2RuntimeAttribute not support"
              # на этой сборке paddlepaddle
              cls._paddle = TextDetection(enable_mkldnn=False)
          return cls._paddle

      @classmethod
      def surya(cls):
          if cls._surya is None:
              from surya.detection import DetectionPredictor

              cls._surya = DetectionPredictor()
          return cls._surya


  def _extract_polygon(box):
      """Surya box может быть объектом (box.polygon) либо dict-like (box["polygon"])"""
      if isinstance(box, dict):
          return box["polygon"]
      return box.polygon


  def _detect_paddle(numpy_image) -> List[List[Tuple[int, int]]]:
      try:
          result = list(_Engines.paddle().predict(numpy_image, batch_size=1))
          return list(result[0]["dt_polys"]) if result else []
      except Exception as e:
          print(f"Ошибка детекции PaddleOCR: {e}")
          return []


  def _detect_surya(pil_image) -> List[List[Tuple[int, int]]]:
      try:
          predictions = _Engines.surya()([pil_image])
          boxes = predictions[0].bboxes if not isinstance(predictions[0], dict) else predictions[0]["bboxes"]
          return [_extract_polygon(box) for box in boxes]
      except Exception as e:
          print(f"Ошибка детекции Surya: {e}")
          return []


  def _detect_tesseract(numpy_image, lang: str) -> List[List[Tuple[int, int]]]:
      try:
          import pytesseract
          from pytesseract import Output

          data = pytesseract.image_to_data(numpy_image, lang=lang, output_type=Output.DICT)
          lines = {}
          for i, word in enumerate(data["text"]):
              if int(data["conf"][i]) == -1 or not word.strip():
                  continue
              key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
              left, top = data["left"][i], data["top"][i]
              right, bottom = left + data["width"][i], top + data["height"][i]
              if key not in lines:
                  lines[key] = [left, top, right, bottom]
              else:
                  box = lines[key]
                  box[0] = min(box[0], left)
                  box[1] = min(box[1], top)
                  box[2] = max(box[2], right)
                  box[3] = max(box[3], bottom)
          return [
              [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
              for x0, y0, x1, y1 in lines.values()
          ]
      except Exception as e:
          print(f"Ошибка детекции Tesseract: {e}")
          return []


  class Detector:
      """Детектор строк текста — выбираемый движок (PaddleOCR PP-OCRv6 / SuryaOCR / Tesseract)"""

      def __init__(self, engine: str = DEFAULT_DETECTOR_ENGINE, tesseract_lang: str = "rus"):
          if engine not in DETECTOR_ENGINES:
              raise ValueError(f"Неизвестный движок детекции: {engine}")
          self._engine = engine
          self._tesseract_lang = tesseract_lang
          if engine == "paddle":
              _Engines.paddle()
          elif engine == "surya":
              _Engines.surya()

      def detect(self, image) -> List[List[Tuple[int, int]]]:
          """Возвращает список полигонов (боксов) строк текста.

          image — numpy-массив (RGB); для surya оборачивается в PIL.Image.
          """
          if self._engine == "paddle":
              return _detect_paddle(image)
          elif self._engine == "surya":
              from PIL import Image

              return _detect_surya(Image.fromarray(image))
          else:
              return _detect_tesseract(image, self._tesseract_lang)
  ```
- **MIRROR**: `LAZY_ENGINE_HOLDER`, `VALUE_VALIDATION_ERROR` (Patterns section above)
- **IMPORTS**: `paddleocr.TextDetection`, `surya.detection.DetectionPredictor`,
  `pytesseract`/`pytesseract.Output`, `PIL.Image` — all lazy/local imports,
  matching the existing "heavy deps imported only inside methods" convention
  (so importing `backend.detector` itself never requires these packages —
  needed for Task 6's lightweight test).
- **GOTCHA**: The polygon point order must stay `[top-left, top-right,
  bottom-right, bottom-left]` for all 3 engines — `pipeline.py` unpacks
  `box[0]` as the crop's top-left and `box[2]` as bottom-right. Verify the
  real `surya-ocr==0.16.0` package's `.bboxes`/`.polygon` shape during
  implementation (not confirmed locally — package not installed in this
  environment); the `isinstance(..., dict)` fallbacks in `_detect_surya`/
  `_extract_polygon` exist specifically to absorb that uncertainty — simplify
  to the single confirmed shape once verified.
- **VALIDATE**: `python -c "import backend.detector"` succeeds without
  `paddleocr`/`surya`/`pytesseract` installed (proves imports stayed lazy).
  `python -c "from backend.detector import Detector; Detector('bogus')"`
  raises `ValueError`.

### Task 2: Thread `detector_engine` through `pipeline.run`
- **ACTION**: Add a `detector_engine` parameter to `run()` and use it (plus
  the already-computed `tesseract_lang`) when constructing `Detector`.
- **IMPLEMENT**: Change the import to
  `from backend.detector import DEFAULT_DETECTOR_ENGINE, Detector`. Add
  `detector_engine: str = DEFAULT_DETECTOR_ENGINE` as the last parameter of
  `run()`. Inside `get_detector()`:
  ```python
  def get_detector() -> Detector:
      nonlocal detector
      if detector is None:
          detector = Detector(engine=detector_engine, tesseract_lang=tesseract_lang)
      return detector
  ```
- **MIRROR**: existing `get_detector()` closure at `backend/pipeline.py:196-200`
- **IMPORTS**: `backend.detector.DEFAULT_DETECTOR_ENGINE`
- **GOTCHA**: `tesseract_lang` is assigned at `backend/pipeline.py:211`,
  *after* `get_detector` is defined but *before* it's first called (inside
  the `matched_files` loop) — Python closures resolve free variables at
  call time, so this ordering already works; do not move the
  `tesseract_lang` assignment earlier "for clarity", it's unnecessary and
  risks widening the diff.
- **VALIDATE**: `pipeline.run(...)` called with `detector_engine="tesseract"`
  and a folder containing one small image (no Paddle/Surya install needed)
  exercises the new path end-to-end if Tesseract is installed locally;
  otherwise rely on the unit-level `Detector` validation from Task 1.

### Task 3: Thread `detector_engine` through `backend/jobs.py`
- **ACTION**: Append `detector_engine: str = DEFAULT_DETECTOR_ENGINE` as the
  last parameter to `start_job()` and `_run_job()`, passing it through to
  `pipeline.run(...)`.
- **IMPLEMENT**: Update the `from backend.detector import DEFAULT_DETECTOR_ENGINE`
  import (new), keep `from backend.recognizers import DEFAULT_LATIN_MODEL_SIZE`
  as-is. Append the new arg to both signatures and both call sites
  (`_run_job`'s call into `pipeline.run`, and the `Thread(args=(...))` tuple
  in `start_job`).
- **MIRROR**: `POSITIONAL_PARAM_THREADING` pattern above
- **IMPORTS**: `backend.detector.DEFAULT_DETECTOR_ENGINE`
- **GOTCHA**: `_run_job`'s positional call to `pipeline.run(...)` and
  `start_job`'s `Thread(args=(job_id, input_dir, ..., detector_engine))`
  tuple must both end up in the exact same order as `pipeline.run`'s
  signature (Task 2) — a silent param-order mismatch here would pass
  `detector_engine`'s value into the wrong slot with no error at call time.
- **VALIDATE**: `python -c "from backend.jobs import start_job; import inspect; print(inspect.signature(start_job))"`
  shows `detector_engine` as the last parameter.

### Task 4: Add `detector_engine` to the `/run` API
- **ACTION**: Add a validated `detector_engine` field to `RunRequest` in
  `backend/main.py`.
- **IMPLEMENT**:
  ```python
  from backend.detector import DEFAULT_DETECTOR_ENGINE, DETECTOR_ENGINES
  ...
  class RunRequest(BaseModel):
      ...
      extract_pdf_text_layer: bool = True
      # Движок детекции строк текста — независим от preferred_model
      # (который влияет только на голосование распознавания).
      detector_engine: str = DEFAULT_DETECTOR_ENGINE
  ```
  In `run()`, add after the existing `latin_model_size` check:
  ```python
  if req.detector_engine not in DETECTOR_ENGINES:
      raise HTTPException(
          400,
          f"detector_engine должен быть одним из {DETECTOR_ENGINES}: "
          f"{req.detector_engine}",
      )
  ```
  Append `req.detector_engine` to the `start_job(...)` call.
- **MIRROR**: `API_FIELD_VALIDATION` pattern above
- **IMPORTS**: `backend.detector.DEFAULT_DETECTOR_ENGINE`,
  `backend.detector.DETECTOR_ENGINES`
- **GOTCHA**: `start_job(...)`'s call-site argument order must match Task 3's
  updated signature exactly.
- **VALIDATE**: `uvicorn backend.main:app` boots without import errors;
  `POST /run` with `{"detector_engine": "bogus", ...}` returns HTTP 400 with
  the expected message; omitting `detector_engine` entirely defaults to
  `"paddle"` (backward compatible with existing API clients).

### Task 5: Track detector-model readiness in `models_status.py`
- **ACTION**: Add `"paddle_detector"`/`"surya_detector"` state keys and wire
  `_prepare()` to instantiate the corresponding detector engine.
- **IMPLEMENT**:
  ```python
  _state: Dict[str, ModelState] = {
      "paddle": ModelState(),
      "surya": ModelState(),
      "paddle_detector": ModelState(),
      "surya_detector": ModelState(),
  }
  ...
  def _prepare(name: str):
      with _lock:
          _state[name] = ModelState("checking")
      try:
          from backend.recognizers import _Engines as RecognizerEngines
          from backend.detector import _Engines as DetectorEngines

          if name == "paddle":
              RecognizerEngines.paddle_cyrillic()
          elif name == "surya":
              RecognizerEngines.surya_recognition()
          elif name == "paddle_detector":
              DetectorEngines.paddle()
          elif name == "surya_detector":
              DetectorEngines.surya()
          with _lock:
              _state[name] = ModelState("ready")
      except Exception as e:
          with _lock:
              _state[name] = ModelState("error", str(e))
  ```
  `prepare()`'s existing `if name not in _state: raise ValueError(...)` guard
  needs no change — it already covers the new keys via `_state`.
- **MIRROR**: `MODEL_STATUS_STATE_AND_PREPARE` pattern above
- **IMPORTS**: `backend.recognizers._Engines` (renamed on import to
  `RecognizerEngines` to avoid colliding with `backend.detector._Engines`
  imported as `DetectorEngines` in the same function)
- **GOTCHA**: `get_status()` returns `dict(_state)` unmodified plus the
  live `tesseract` check appended — no change needed there, the two new
  keys flow through automatically once added to `_state`.
- **VALIDATE**: `pytest backend/tests/test_models_status.py -v` (after
  Task 6) passes; `GET /models/status` response includes
  `paddle_detector`/`surya_detector` keys.

### Task 6: Extend `test_models_status.py` for the new keys
- **ACTION**: Add `"paddle_detector"`/`"surya_detector"` to the
  `reset_model_state` fixture's two dict literals; add prepare
  success/failure tests for both new keys mirroring the existing
  `paddle` tests.
- **IMPLEMENT**:
  ```python
  @pytest.fixture(autouse=True)
  def reset_model_state():
      state = {
          "paddle": models_status.ModelState(),
          "surya": models_status.ModelState(),
          "paddle_detector": models_status.ModelState(),
          "surya_detector": models_status.ModelState(),
      }
      models_status._state = dict(state)
      yield
      models_status._state = dict(state)


  def test_prepare_detector_success_sets_ready():
      with patch("backend.detector._Engines.paddle", return_value=object()):
          models_status._prepare("paddle_detector")
      assert models_status._state["paddle_detector"].status == "ready"


  def test_prepare_detector_failure_sets_error_with_detail():
      with patch(
          "backend.detector._Engines.surya", side_effect=RuntimeError("boom")
      ):
          models_status._prepare("surya_detector")
      assert models_status._state["surya_detector"].status == "error"
      assert "boom" in models_status._state["surya_detector"].detail
  ```
- **MIRROR**: `MODEL_STATUS_TEST_FIXTURE` pattern above, and
  `test_prepare_success_sets_ready`/`test_prepare_failure_sets_error_with_detail`
  at `backend/tests/test_models_status.py:46-56`
- **IMPORTS**: none new (test file already imports `patch`, `pytest`,
  `models_status`)
- **GOTCHA**: `patch("backend.detector._Engines.paddle", ...)` patches the
  classmethod on `backend.detector._Engines` — must reference the module
  path exactly (`backend.detector._Engines`, not
  `backend.recognizers._Engines`, which is a different class despite the
  same name) or the patch silently no-ops and the real (missing) ML dep
  gets imported.
- **VALIDATE**: `pytest backend/tests/test_models_status.py -v` — all tests
  pass, including the two new ones, with no network/model download
  triggered (patches prevent real instantiation).

### Task 7: Add detector selection to the Streamlit UI
- **ACTION**: Add a "Модели детекции строк" status subsection and a
  "Детектор строк текста" selectbox in `generation_view.py`.
- **IMPLEMENT**:
  ```python
  DETECTOR_STATUS_KEYS = {"paddle": "paddle_detector", "surya": "surya_detector", "tesseract": "tesseract"}


  def _render_engine_status_row(label, status_key, downloadable, key_prefix):
      info = st.session_state.models_status_cache.get(status_key, {})
      status = info.get("status", "not_checked")
      col1, col2, col3 = st.columns([2, 2, 1])
      col1.write(label)
      col2.write(STATUS_LABELS.get(status, status))
      if downloadable and status not in ("ready", "checking"):
          if col3.button("Скачать", key=f"prepare_{key_prefix}_{status_key}"):
              try:
                  resp = requests.post(
                      f"{BACKEND_URL}/models/prepare",
                      json={"model": status_key},
                      timeout=5,
                  )
                  resp.raise_for_status()
                  st.session_state.pop("models_status_cache", None)
                  st.rerun()
              except Exception as e:
                  st.error(f"Ошибка запуска подготовки: {e}")
      if info.get("detail"):
          st.caption(info["detail"])


  def _render_model_status():
      st.subheader("Модели")
      if st.button("🔄 Обновить статус", key="models_refresh"):
          st.session_state.pop("models_status_cache", None)

      if "models_status_cache" not in st.session_state:
          try:
              resp = requests.get(f"{BACKEND_URL}/models/status", timeout=5)
              resp.raise_for_status()
              st.session_state.models_status_cache = resp.json()
          except Exception as e:
              st.error(f"Backend недоступен: {e}")
              return

      st.markdown("**Модели распознавания**")
      for name, label in ENGINES:
          _render_engine_status_row(label, name, name != "tesseract", "rec")

      st.markdown("**Модели детекции строк**")
      for name, label in ENGINES:
          status_key = DETECTOR_STATUS_KEYS[name]
          _render_engine_status_row(label, status_key, status_key != "tesseract", "det")
  ```
  In `_render_run_controls()`, add before the `preferred` selectbox:
  ```python
  detector_engine = st.selectbox(
      "Детектор строк текста",
      ["paddle", "surya", "tesseract"],
      key="consensus_detector",
  )
  ```
  and add `"detector_engine": detector_engine` to the `json={...}` payload
  in the `POST /run` call.
- **MIRROR**: `STREAMLIT_ENGINE_STATUS_ROW`, `STREAMLIT_SELECTBOX_IN_RUN_PAYLOAD`
  patterns above
- **IMPORTS**: none new
- **GOTCHA**: Do not touch the pre-existing uncommitted reordering of
  `threshold`/`preferred`/`extract_pdf_text_layer` already on disk in this
  file (unrelated in-progress change, unstaged) — add the new selectbox
  without reverting that reordering.
- **VALIDATE**: `cd frontend && streamlit run app.py --server.enableXsrfProtection=false`,
  navigate to "🤖 Авторазметка", confirm both status subsections render and
  the new selectbox appears with `paddle` pre-selected; submit a run and
  confirm (via browser devtools or backend logs) the POST body includes
  `detector_engine`.

### Task 8: Update `backend/README.md`
- **ACTION**: Document the new `detector_engine` field and the two new
  `/models/status`/`/models/prepare` keys.
- **IMPLEMENT**: In the `POST /run` line, add `"detector_engine": str`
  to the JSON shape description. Add a short paragraph after the existing
  "Детектор строк использует PaddleOCR..." intro paragraph explaining that
  the detector is now selectable (`paddle`/`surya`/`tesseract`, default
  `paddle`) and independent of the recognition consensus. Update the
  `/models/status`/`/models/prepare` bullet to list the 4 recognition/detector
  keys (`paddle`, `surya`, `paddle_detector`, `surya_detector`) plus
  `tesseract` (shared, no `prepare` needed).
- **MIRROR**: existing prose style in `backend/README.md`
- **IMPORTS**: n/a (docs)
- **GOTCHA**: Keep the existing "не участвует в сборке .exe" and
  single-user/no-auth framing untouched — this change doesn't affect those
  properties.
- **VALIDATE**: manual read-through; no broken markdown links/tables.

### Task 9: Regenerate the backend codemap
- **ACTION**: Run the codemap generator so `docs/CODEMAPS/backend.md`
  reflects the new `detector_engine` field and `backend/detector.py`'s
  new shape.
- **IMPLEMENT**: Invoke `/update-codemaps` (or the equivalent script it
  wraps) after all other tasks are complete.
- **MIRROR**: n/a (generated file)
- **IMPORTS**: n/a
- **GOTCHA**: Don't hand-edit `docs/CODEMAPS/backend.md` — it's
  regenerated from source; hand edits will be overwritten and drift from
  the generator's format.
- **VALIDATE**: diff shows updated `RunRequest` field list and
  `backend/detector.py` line-count/summary; no unrelated files changed.

---

## Testing Strategy

### Unit Tests

| Test | Input | Expected Output | Edge Case? |
|---|---|---|---|
| `Detector("bogus")` | invalid engine name | raises `ValueError` | Yes — mirrors `paddle_latin`'s validation |
| `test_prepare_detector_success_sets_ready` (paddle_detector) | `backend.detector._Engines.paddle` patched to succeed | `_state["paddle_detector"].status == "ready"` | No |
| `test_prepare_detector_failure_sets_error_with_detail` (surya_detector) | `backend.detector._Engines.surya` patched to raise | `_state["surya_detector"].status == "error"`, detail contains message | Yes — failure path |
| `models_status.prepare("bogus")` (existing test, unchanged) | unknown key | raises `ValueError` | Yes — already covered, still passes with new keys added |
| `import backend.detector` with no ML deps installed | module import only | succeeds (all heavy imports stay inside methods) | Yes — protects the "not unit-tested, lazy import" convention documented in `CLAUDE.md`/`docs/testing.md` |

### Edge Cases Checklist
- [x] Invalid `detector_engine` value via API → HTTP 400 (Task 4)
- [x] Invalid `detector_engine` value via `Detector.__init__` → `ValueError` (Task 1, defense in depth)
- [x] Missing/omitted `detector_engine` in request body → defaults to `"paddle"` (backward compatible)
- [x] Tesseract detector with zero recognized words on a page → `_detect_tesseract` returns `[]` (empty `lines` dict), matching existing "no boxes" behavior for any engine on a blank page
- [ ] Concurrent access — N/A, `models_status._state` already lock-protected (`_lock`), unchanged
- [ ] Network failure — N/A, no network calls added beyond existing model-download-on-first-use pattern

---

## Validation Commands

### Static Analysis
```bash
ruff check backend frontend/src/ui/generation_view.py
```
EXPECT: Zero lint errors

```bash
ruff format --check backend backend/tests frontend/src/ui/generation_view.py
```
EXPECT: No reformatting needed (or run without `--check` to apply)

### Unit Tests
```bash
pytest backend/tests/test_models_status.py -v
```
EXPECT: All tests pass, including the 2 new `paddle_detector`/`surya_detector` tests

### Full Test Suite
```bash
pytest
```
EXPECT: No regressions in `frontend/tests/` or the rest of `backend/tests/`

### Import Sanity (no heavy ML deps required)
```bash
python -c "import backend.detector; import backend.pipeline; import backend.jobs; import backend.main; import backend.models_status; print('ok')"
```
EXPECT: `ok`, no `ModuleNotFoundError` for paddleocr/surya/pytesseract (proves lazy-import convention preserved)

### Browser Validation
```bash
cd frontend && streamlit run app.py --server.enableXsrfProtection=false
```
EXPECT: "🤖 Авторазметка" tab shows both "Модели распознавания" and "Модели детекции строк" subsections; the "Детектор строк текста" selectbox appears (default `paddle`) and is included in the `/run` POST body

### Manual Validation
- [ ] Start `uvicorn backend.main:app --reload` from repo root
- [ ] `POST /run` with `detector_engine` omitted → still works exactly as before (backward compatible)
- [ ] `POST /run` with `detector_engine: "bogus"` → HTTP 400 with clear message
- [ ] `GET /models/status` → response includes `paddle`, `surya`, `paddle_detector`, `surya_detector`, `tesseract`
- [ ] If Tesseract is installed locally: `POST /run` with `detector_engine: "tesseract"` on a small test folder produces non-empty `good.txt`/`needs_review.txt` (proves the tesseract line-grouping produces usable boxes)
- [ ] If Paddle/Surya installable locally: spot-check that `detector_engine: "surya"` doesn't crash on the real installed package — this is the one step that directly resolves the "verify Surya's `.bboxes`/`.polygon` shape" GOTCHA from Task 1; if the real shape differs from both branches handled, fix `_extract_polygon`/`_detect_surya` accordingly

---

## Acceptance Criteria
- [ ] All 9 tasks completed
- [ ] All validation commands pass
- [ ] `test_models_status.py` extended and passing
- [ ] No type errors (project doesn't enforce mypy, but `ruff check` clean)
- [ ] No lint errors
- [ ] Matches UX design — two status subsections + new selectbox, backward-compatible API defaults

## Completion Checklist
- [ ] Code follows discovered patterns (`_Engines` lazy holder, positional param threading, `ValueError`/`HTTPException` validation pairing)
- [ ] Error handling matches codebase style (`try/except` + `print(f"Ошибка ...: {e}")` + safe fallback return, consistent with `detector.py`/`recognizers.py`)
- [ ] No logging framework introduced — codebase uses bare `print()` for these ML-engine warnings; do not "improve" this in scope of this change
- [ ] Tests follow `test_models_status.py`'s `patch(...)` + fixture-reset style
- [ ] No hardcoded values beyond the existing `enable_mkldnn=False` workaround (preserved, not duplicated elsewhere)
- [ ] `backend/README.md` updated
- [ ] `docs/CODEMAPS/backend.md` regenerated (not hand-edited)
- [ ] No unnecessary scope additions — recognition consensus untouched, no new detector engines beyond paddle/surya/tesseract, no persistence layer added
- [ ] Self-contained — the one open question (Surya's exact `.bboxes`/`.polygon` return shape) has an explicit defensive fallback plus a manual-validation step to resolve it against the real package, so implementation doesn't block on further codebase search

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Surya `DetectionPredictor` return shape (attribute vs dict access for `.bboxes`/`.polygon`) doesn't match either branch handled in `_extract_polygon`/`_detect_surya` | Medium | Detector selection silently returns 0 boxes for `engine="surya"` (caught by the existing `try/except`, degrades to empty results rather than crashing) | Defensive dual-path extraction in Task 1 + explicit manual-validation step against the real installed package; not verifiable in this environment since `surya-ocr` isn't installed here |
| Polygon point order differs between engines (not all engines guaranteed clockwise-from-top-left) | Low | Crops would be computed from wrong corners for that engine, producing garbled/empty crops | `pipeline.py`'s existing `box[0]`/`box[2]` unpacking is unchanged; Tesseract's grouping is hand-built to match `[TL, TR, BR, BL]` exactly; Surya's is documented as clockwise-from-top-left in its own docs — verify visually via Manual Validation step |
| `models_status._state` key proliferation (4 keys instead of 2) increases the surface `get_status()`/`prepare()`/frontend must stay in sync with | Low | Minor — a forgotten key update in one layer causes a `400`/missing-status-row, not data loss | Task list explicitly touches all 4 layers (`models_status.py`, its test, `main.py` doesn't need changes here since it doesn't validate `/models/prepare`'s `model` field beyond `models_status.prepare`'s own `ValueError`→400 mapping, `generation_view.py`) |
| Tesseract line-grouping produces overly large/merged boxes on multi-column documents (block_num/par_num/line_num grouping is Tesseract's own layout analysis, not ground truth) | Low | Worse crop quality for `detector_engine="tesseract"` specifically vs. paddle/surya | Out of scope to improve Tesseract's own layout analysis; acceptable since it's an opt-in engine choice, not the default |

## Notes
- The task's framing ("нужно уметь работать со всеми моделями") is about
  the **detector** step specifically — recognition already works with all
  3 engines simultaneously (consensus voting), so no changes were made
  there beyond keeping `preferred_model` semantics exactly as-is.
- `docs/architecture.md` was checked and contains no backend/detector
  references (it documents the frontend module map) — no update needed
  there, only `docs/CODEMAPS/backend.md` (Task 9) and `backend/README.md`
  (Task 8).
- Chose to append `detector_engine` as the *last* positional parameter in
  `pipeline.run`/`jobs.start_job`/`jobs._run_job` rather than inserting it
  near `preferred_model` (which is conceptually closer) specifically to
  minimize the diff/reorder-risk across the 3 files that must stay in sync
  positionally — a keyword-only refactor of these signatures was considered
  and rejected as unnecessary scope expansion for this change.

> Next step: Run `/prp-implement .claude/PRPs/plans/selectable-detector-engine.plan.md` to execute this plan.
