# Plan: Прямое извлечение текстового слоя PDF (без OCR)

## Summary
Добавить в `backend/pipeline.run()` обработку PDF-файлов во входной папке.
Если у PDF есть извлекаемый текстовый слой (проверяется по первым 1-2
страницам документа), весь документ обрабатывается через `pypdfium2`:
текст и координаты вытаскиваются напрямую из PDF, OCR-консенсус (Paddle/
Surya/Tesseract) не запускается вообще, а каждая строка сразу попадает в
`good.txt` (текст и координаты точны по определению). Если текстового слоя
нет — документ, как и раньше, растеризуется постранично и идёт в обычный
3-движковый консенсус. Поведение управляется новым флагом
`extract_pdf_text_layer` (по умолчанию `true`) в `POST /run` и чекбоксом в
`frontend/src/ui/generation_view.py`.

## User Story
Как пользователь, который готовит данные для разметки/дообучения OCR, я
хочу, чтобы «нативные» PDF (с текстовым слоем — экспортированные из Word,
1С, сгенерированные программно и т.п.) не гонялись через тяжёлый и
небыстрый 3-движковый OCR-консенсус, а сразу давали точный текст+координаты,
поскольку у таких документов это уже есть в самом файле.

## Problem → Solution
Сейчас `backend/pipeline.run()` (`backend/pipeline.py:23-103`) ищет во
входной папке только файлы с расширениями из `IMAGE_EXTENSIONS`
(`backend/config.py:1`) и для каждого гонит детекцию (PaddleOCR) +
распознавание тремя движками + голосование (`backend/consensus.py::vote`).
PDF-файлы полностью игнорируются (не попадают в `matched_files`) — их
приходится заранее конвертировать в изображения вручную. → `run()` находит
и `.pdf`-файлы; для каждого сначала проверяет, есть ли извлекаемый текстовый
слой (`pdf_extract.document_has_text_layer`), и либо извлекает текст+боксы
напрямую (без OCR, сразу в `good.txt`), либо растеризует страницы и
прогоняет их через существующий OCR-консенсус — идентично сегодняшней
обработке изображений.

## Metadata
- **Complexity**: Large (новый backend-модуль + рефакторинг `pipeline.run()` + API-контракт + frontend-чекбокс + новые тесты + зависимости)
- **Source PRD**: N/A (изложено напрямую пользователем в чате, уточнено через уточняющие вопросы)
- **PRD Phase**: N/A
- **Estimated Files**: 10 (1 новый backend-модуль, 1 новый тест-файл, 6 изменяемых файлов кода/конфигурации, 2 файла документации)

## Решения, зафиксированные с пользователем
1. **Гранулярность определения "есть текстовый слой"** — на уровне **документа**, по первым **2 страницам** (пробинг). Если хотя бы одна из первых
   2 страниц содержит непустой текст — весь документ обрабатывается через
   прямое извлечение; страницы **без** текста внутри такого документа
   **пропускаются** (не отправляются в OCR как fallback) — «если пропустим
   какие-то страницы — не беда» (дословно от пользователя). Если ни одна из
   первых 2 страниц текста не содержит — весь документ целиком идёт в
   обычный OCR-консенсус (даже если текст есть на более поздних страницах —
   осознанное упрощение).
2. **Настройка `extract_pdf_text_layer`** — новое булево поле в
   `POST /run` и чекбокс в UI, **включено по умолчанию** (`true`).

---

## UX Design

### Before
```
┌───────────────────────────────────────────┐
│  🤖 Авторазметка                            │
│  Папка с документами: [___________]         │
│  Папка вывода:        [___________]         │
│  Порог уверенности:   [====slider====]       │
│  Предпочитаемая модель: [None|paddle|...]     │
│  [▶ Запустить]                               │
└───────────────────────────────────────────┘
   PDF-файлы во входной папке молча игнорируются
   (не попадают в matched_files, не в good/needs_review)
```

### After
```
┌───────────────────────────────────────────┐
│  🤖 Авторазметка                            │
│  Папка с документами: [___________]         │
│  Папка вывода:        [___________]         │
│  Порог уверенности:   [====slider====]       │
│  Предпочитаемая модель: [None|paddle|...]     │
│  ☑ Извлекать текст из PDF напрямую,          │
│    без OCR (если есть текстовый слой)        │
│  [▶ Запустить]                               │
└───────────────────────────────────────────┘
   PDF с текстовым слоем -> good.txt сразу, без OCR
   PDF-скан без текстового слоя -> обычный OCR-консенсус
```

### Interaction Changes
| Touchpoint | Before | After | Notes |
|---|---|---|---|
| Входные файлы `/run` | Только `IMAGE_EXTENSIONS` | + `.pdf` | `backend/pipeline.py::run` |
| Настройки запуска (UI) | 4 контрола | + чекбокс "Извлекать текст из PDF" | `frontend/src/ui/generation_view.py::_render_run_controls` |
| Результат для PDF с текстовым слоем | N/A (файл игнорировался) | Строки сразу в `good.txt`, `AnnotationManager` помечает их `is_marked=True` как обычно | Без изменений в `_build_manager_from_output` — формат тот же |
| Результат для PDF-скана | N/A | Как обычное изображение — детекция + консенсус, `good.txt`/`needs_review.txt` | Страницы растеризуются через `pdf_extract.render_page` |

---

## Mandatory Reading

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | `backend/pipeline.py` | 1-103 | Файл, который рефакторится — текущая логика цикла по боксам переносится в helper, к ней добавляется PDF-ветка |
| P0 | `backend/config.py` | 1-4 | `IMAGE_EXTENSIONS`, `DEFAULT_SCORE_THRESHOLD` — сюда добавляется `PDF_EXTENSIONS` |
| P0 | `backend/consensus.py` | 1-35 | `vote()` — НЕ вызывается для PDF-текстового-слоя пути (текст уже точен), но вызывается как раньше для PDF-скан-fallback пути |
| P0 | `predict.py` | 26-99 | Прежний (не входящий в сервис, приватная `ocr_library`) прототип `extract_text_pdf` — источник паттерна группировки по PDF text-объектам и маппинга координат PDF->pixel; в этом плане переписан на «голый» `pypdfium2` без `ocr_library` |
| P1 | `backend/jobs.py` | 1-84 | `start_job`/`_run_job` — сигнатуры, через которые новый параметр должен прокинуться в `pipeline.run` |
| P1 | `backend/main.py` | 1-89 | `RunRequest` (Pydantic) — сюда добавляется поле `extract_pdf_text_layer` |
| P1 | `backend/detector.py` | 1-22 | Формат бокса, который возвращает детектор: `[[x0,y0],[x1,y0],[x1,y1],[x0,y1]]` — PDF-извлечение обязано возвращать боксы в том же формате |
| P1 | `frontend/src/ui/generation_view.py` | 63-89 | `_render_run_controls` — стиль контролов Streamlit + JSON payload в `POST /run` |
| P1 | `frontend/src/annotations.py` | 23-60 | `load_from_file` — подтверждает, что `.webp`-кропы уже поддерживаются (`image_extensions` на строке 27), изменений не требует |
| P2 | `backend/tests/test_consensus.py` | 1-65 | Стиль unit-тестов чистой логики без реальных ML-зависимостей — mirror для `test_pdf_extract.py` |
| P2 | `backend/tests/test_models_status.py` | 1-62 | Ещё один пример стиля тестов с `patch`/фикстурами |
| P2 | `docs/testing.md` | 1-35 | Текущая формулировка "detector.py/recognizers.py не тестируются" — требует уточнения, что `pdf_extract.py` тестируется |
| P2 | `backend/README.md` | 1-59 | Раздел `## API` — требует обновления описания `/run` |

## External Documentation

Библиотека `pypdfium2` уже установлена в текущем dev-окружении
(`pip show pypdfium2` → `4.30.1`), но **не объявлена** ни в
`backend/requirements.txt`, ни в `requirements-dev.txt` — её нужно добавить
явно. API проверен вживую в этом окружении (не по документации из памяти) —
все сигнатуры и форматы данных ниже подтверждены запуском кода:

```
KEY_INSIGHT: pdfium.PdfDocument(path_or_bytes, password=None, autoclose=False)
поддерживает len(doc), doc[i] (только int-индекс, СРЕЗЫ doc[:2] НЕ
поддерживаются — TypeError), и итерацию for page in doc.
APPLIES_TO: pdf_extract.document_has_text_layer, pipeline._process_pdf
GOTCHA: использовать `for i in range(min(probe_pages, len(pdf_doc))): page = pdf_doc[i]`,
не пытаться делать pdf_doc[:probe_pages].

KEY_INSIGHT: page.get_textpage().get_charbox(i) и
page.get_objects(filter=[pdfium.raw.FPDF_PAGEOBJ_TEXT]) (константа = 1) ->
obj.get_pos() оба возвращают кортеж в PDF user space как
(left, bottom, right, top) — ось Y растёт СНИЗУ вверх (origin в левом
нижнем углу страницы).
APPLIES_TO: pdf_extract.extract_page_text_boxes
GOTCHA: bottom < top численно (не "y0 < y1" как в пиксельных координатах) —
перепутать local left/bottom/right/top с привычным x0/y0/x1/y1 легко.

KEY_INSIGHT: textpage.get_text_range(i, 1) (per-char, с явным count=1)
НЕ выбрасывает предупреждение. Но textpage.get_text_range(0, -1) или
textpage.get_text_range() (дефолтные параметры index=0,count=-1) выбрасывают
UserWarning "call with default params will be implicitly redirected to
get_text_bounded()" — даже если 0 и -1 переданы ЯВНО. Для текста всей
страницы нужно вызывать textpage.get_text_bounded() напрямую (без
аргументов) — тогда предупреждения нет.
APPLIES_TO: pdf_extract.page_has_text_layer (использовать get_text_bounded()),
pdf_extract.extract_page_text_boxes (использовать get_text_range(i, 1) для
каждого символа — как в предыдущем прототипе predict.py)
GOTCHA: не использовать get_text_range() с дефолтными аргументами.

KEY_INSIGHT: page.render(scale=dpi/72).to_pil() возвращает PIL.Image в
режиме "RGB" (не RGBA) для страницы без прозрачности — проверено эмпирически
для страницы 400x400pt при scale=200/72 -> изображение 1112x1112px (округление
вверх: round(400 * 200/72) = 1111.11 -> 1112).
APPLIES_TO: pdf_extract.render_page
GOTCHA: всё равно вызывать .convert("RGB") явно (как в остальном pipeline.py) —
дешёвый no-op если уже RGB, но защищает от редких PDF с альфа-каналом.

KEY_INSIGHT: маппинг PDF-координат (points, Y снизу вверх) в пиксельные
координаты отрендеренного изображения (Y сверху вниз) — простая линейная
формула без поворота, если страница не повёрнута (/Rotate не учтён отдельно,
см. Risks):
    x_pix = pdf_x / page_width  * image_width
    y_pix = image_height - (pdf_y / page_height * image_height)
Формула проверена вручную на синтетическом PDF: символ с charbox
(73.92, 300.0, ..., 317.18) на странице 400x400pt, изображение 1112x1112px
(scale=200/72) даёт y0≈230.3, y1≈278 — совпадает с ожидаемым положением
текста, отрисованного через `Td 72 300`.
APPLIES_TO: pdf_extract._pdf_x_to_pix, pdf_extract._pdf_y_to_pix
GOTCHA: top (PDF) маппится в y0 (pixel, меньшее значение = выше на экране),
bottom (PDF) маппится в y1 (pixel, большее значение = ниже на экране) — не
перепутать местами, иначе бокс "перевёрнут" по вертикали.

KEY_INSIGHT: requirements-dev.txt сейчас ставит ТОЛЬКО
frontend/requirements.txt + pytest/pytest-cov/ruff — backend/requirements.txt
НЕ ставится. `docs/testing.md:17-20` явно объясняет: detector.py/recognizers.py
не тестируются, т.к. лениво импортируют тяжёлые ML-зависимости (модели,
системный Tesseract). pypdfium2 — лёгкая самодостаточная библиотека без
скачиваемых моделей и системных бинарников, поэтому НОВЫЙ модуль
pdf_extract.py, в отличие от detector.py/recognizers.py, ДОЛЖЕН быть
юнит-тестируемым — но для этого pypdfium2 (и numpy, которого тоже нет ни в
одном requirements-файле явно) нужно добавить в requirements-dev.txt, а не
только в backend/requirements.txt.
APPLIES_TO: requirements-dev.txt, backend/requirements.txt, docs/testing.md
GOTCHA: если добавить pypdfium2 только в backend/requirements.txt, новый
test_pdf_extract.py будет падать при `pip install -r requirements-dev.txt && pytest`
— именно тот сценарий, который описан в docs/testing.md как основной.
```

---

## Patterns to Mirror

### GLOB_BY_EXTENSION_TUPLE
// SOURCE: backend/pipeline.py:45-47, backend/config.py:1
```python
matched_files = []
for ext in IMAGE_EXTENSIONS:
    matched_files.extend(glob(os.path.join(input_dir, f"*{ext}")))
```
Для PDF — тот же паттерн с новой константой `PDF_EXTENSIONS = (".pdf",)` в
`backend/config.py` (регистр не нормализуется — как и для `IMAGE_EXTENSIONS`,
`.PDF` в верхнем регистре не подхватится; сознательно не меняем это
поведение).

### BOX_FORMAT (детектор -> кроп)
// SOURCE: backend/pipeline.py:64-66, backend/detector.py:14-18
```python
x0, y0 = box[0]
x2, y2 = box[2]
img_crop = numpy_image[int(y0) : int(y2), int(x0) : int(x2)]
```
Бокс — 4 точки полигона `[[x0,y0],[x1,y0],[x1,y1],[x0,y1]]` (левый-верх,
правый-верх, правый-низ, левый-низ). PDF-извлечение обязано возвращать боксы
в точно таком же формате, чтобы этот код мог остаться без изменений.

### CROP_SAVE_AND_LINE_FORMAT
// SOURCE: backend/pipeline.py:83-89
```python
crop_dir = os.path.join(output_dir, "crops")
os.makedirs(crop_dir, exist_ok=True)
crop_name = f"crop_{uuid.uuid4().hex}.webp"
crop_path = os.path.join(crop_dir, crop_name)
Image.fromarray(img_crop).save(crop_path, "WEBP")
line = f"crops/{crop_name}\t{text}\n"
```
Уникальное имя на каждый кроп (uuid4) — повторный запуск не портит старые
кропы. `.webp` уже входит в `image_extensions`, проверяемый
`AnnotationManager.load_from_file` (`frontend/src/annotations.py:27`) —
изменений там не требуется.

### ERROR_HANDLING (широкий try/except с print, без падения всего run)
// SOURCE: backend/pipeline.py:53-60, 94-96; backend/detector.py:16-21; backend/recognizers.py:57-59
```python
try:
    ...
except Exception as e:
    print(f"Ошибка обработки файла {file_path}: {e}")
    continue
```
Каждый файл/бокс/страница обрабатывается в своём `try/except`, ошибка не
прерывает обработку остальных файлов — mirror для PDF-файлов и PDF-страниц.

### LAZY_HEAVY_DEPENDENCY (импорт внутри функции/метода, не на верхнем уровне модуля)
// SOURCE: backend/detector.py:7-8, backend/recognizers.py:18, 30, 40-41
```python
def __init__(self):
    from paddleocr import TextDetection
    self._detector = TextDetection(enable_mkldnn=False)
```
`pypdfium2` **не** тяжёлая ML-зависимость (не грузит модели, не требует
системных бинарников) — поэтому в отличие от paddleocr/surya её можно
импортировать на уровне модуля в `backend/pdf_extract.py` напрямую (см.
KEY_INSIGHT выше про requirements-dev.txt) — это осознанное отличие от
LAZY_HEAVY_DEPENDENCY, а не нарушение паттерна.

### TYPING_STYLE (типизируются примитивы, объекты из тяжёлых/специфичных библиотек — нет)
// SOURCE: backend/pipeline.py:23-29, backend/recognizers.py:50, 62-64, 76
```python
def run(
    input_dir: str,
    output_dir: str,
    threshold: float,
    preferred_model: Optional[str] = None,
    lang: str = "ru",
    latin_model_size: str = DEFAULT_LATIN_MODEL_SIZE,
) -> Tuple[int, int]:
def recognize_paddle(crop) -> Tuple[str, float]:   # crop — БЕЗ типа
```
`Dict`/`List`/`Optional`/`Tuple` из `typing` (не `dict`/`list`/`X | None`) —
см. `CLAUDE.md`, раздел Code Style, и `pyproject.toml` (`ruff` намеренно не
включает правило `UP`). `pdfium.PdfPage`/`pdfium.PdfDocument` — исключение:
поскольку `pypdfium2` импортируется на верхнем уровне модуля (не лениво),
типизировать ими параметры — нормально и добавляет ясности, в отличие от
`crop`/`image`/`box` в `recognizers.py`, которые оставлены без типа именно
из-за отсутствия верхнеуровневого импорта их источников.

### TEST_STRUCTURE (без моков реальных ML-моделей, чистые unit-тесты)
// SOURCE: backend/tests/test_consensus.py:1-24
```python
from backend.consensus import vote


def test_vote_returns_needs_review_for_empty_results():
    bucket, text, engine = vote({}, threshold=0.9)

    assert bucket == "needs_review"
    assert text == ""
    assert engine == ""
```
Плоские `test_*` функции без классов, без фикстур там, где не нужны общие
данные (`test_models_status.py` использует `@pytest.fixture(autouse=True)`
только там, где есть общее mutable-состояние модуля).

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `backend/pdf_extract.py` | CREATE | Новый модуль: рендер PDF-страницы, извлечение текстовых боксов из текстового слоя, проверка "есть ли текстовый слой" (постранично и на уровне документа) |
| `backend/pipeline.py` | UPDATE | Добавить поиск `.pdf`-файлов; вынести обработку боксов в `_process_boxes`/`_save_crop` (переиспользуется для растровых изображений И для PDF-скан-fallback страниц); добавить `_process_pdf` и параметр `extract_pdf_text_layer` в `run()` |
| `backend/config.py` | UPDATE | Добавить `PDF_EXTENSIONS = (".pdf",)` |
| `backend/jobs.py` | UPDATE | Прокинуть `extract_pdf_text_layer` через `start_job`/`_run_job` в `pipeline.run` |
| `backend/main.py` | UPDATE | Добавить поле `extract_pdf_text_layer: bool = True` в `RunRequest`, передать в `start_job` |
| `backend/requirements.txt` | UPDATE | Добавить `pypdfium2==4.30.1` |
| `requirements-dev.txt` | UPDATE | Добавить `pypdfium2==4.30.1` и `numpy==1.26.4` — нужны, чтобы `backend/tests/test_pdf_extract.py` проходил без установки `backend/requirements.txt` (см. GOTCHA выше) |
| `backend/tests/test_pdf_extract.py` | CREATE | Юнит-тесты для `pdf_extract.py` на синтетических PDF, построенных вручную (без внешних PDF-библиотек) |
| `frontend/src/ui/generation_view.py` | UPDATE | Чекбокс "Извлекать текст из PDF..." в `_render_run_controls`, поле в JSON-теле `POST /run` |
| `backend/README.md` | UPDATE | Описать `.pdf`-вход, новое поле `extract_pdf_text_layer` в `/run`, кратко — логику пробинга текстового слоя и её ограничение (см. Risks) |
| `docs/testing.md` | UPDATE | Уточнить: `backend/pdf_extract.py` тестируется (в отличие от detector.py/recognizers.py) — pypdfium2 лёгкая, добавлена в requirements-dev.txt |

## NOT Building
- OCR fallback для отдельных "пустых" страниц внутри PDF, который в целом
  признан "с текстовым слоем" — такие страницы просто пропускаются (явное
  решение пользователя).
- Обработка PDF с текстовым слоем, начинающимся ПОСЛЕ 2-й страницы — такой
  документ целиком пойдёт в OCR-консенсус (осознанное упрощение пробинга).
- Пароль-защищённые PDF — при ошибке открытия документ логируется и
  пропускается, как любой другой битый файл (без запроса пароля у
  пользователя).
- Специальная обработка повёрнутых страниц (`/Rotate`) — координаты не
  корректируются под поворот отдельно (см. Risks).
- Настройка DPI рендеринга страницы и количества страниц для пробинга через
  API/UI — захардкожены в `pdf_extract.py` (`PDF_RENDER_DPI = 200`,
  `PROBE_PAGE_COUNT = 2`), как внутренняя деталь реализации.
- Более сложная, чем "один PDF text-объект = один кроп", группировка символов
  в строки — используется тот же практический подход, что и в прежнем
  (не входящем в сервис) прототипе `predict.py::extract_text_pdf`.
- Эвристики отличия "нативного" текстового слоя от текстового слоя,
  добавленного OCR-программой сканера (searchable PDF) — см. Risks, это
  прямое следствие выбранного пользователем подхода "если есть текстовый
  слой — доверяем ему полностью".

---

## Step-by-Step Tasks

### Task 1: Добавить зависимости
- **ACTION**: Обновить `backend/requirements.txt` и `requirements-dev.txt`.
- **IMPLEMENT**:
  `backend/requirements.txt` — добавить строку `pypdfium2==4.30.1` (после
  `Pillow==10.4.0`).
  `requirements-dev.txt` — добавить `pypdfium2==4.30.1` и `numpy==1.26.4`
  после существующих `-r frontend/requirements.txt` / `pytest`/`ruff` строк.
- **MIRROR**: Существующий формат — `pkg==точная_версия`, без диапазонов.
- **IMPORTS**: N/A
- **GOTCHA**: Версии `4.30.1`/`1.26.4` — версии, реально установленные и
  проверенные в текущем dev-окружении (`pip show pypdfium2`/`pip show numpy`).
  Не гадать другую версию.
- **VALIDATE**: `pip install -r requirements-dev.txt` завершается без ошибок
  в чистом venv.

### Task 2: `PDF_EXTENSIONS` в конфиге
- **ACTION**: Добавить константу для поиска PDF-файлов.
- **IMPLEMENT** (`backend/config.py`):
```python
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp")
PDF_EXTENSIONS = (".pdf",)
DEFAULT_SCORE_THRESHOLD = 0.95
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8756
```
- **MIRROR**: `IMAGE_EXTENSIONS` — тот же файл, тот же стиль (tuple констант).
- **IMPORTS**: N/A
- **GOTCHA**: Не путать с regex/glob-паттерном — используется как суффикс в
  `f"*{ext}"`, см. GLOB_BY_EXTENSION_TUPLE.
- **VALIDATE**: `python -c "from backend.config import PDF_EXTENSIONS; print(PDF_EXTENSIONS)"`

### Task 3: Создать `backend/pdf_extract.py`
- **ACTION**: Новый модуль с чистыми функциями извлечения текстового слоя PDF.
- **IMPLEMENT**:
```python
"""Извлечение текстового слоя PDF без OCR через pypdfium2.

pypdfium2 — лёгкая самодостаточная библиотека (без скачиваемых моделей и
системных бинарников), поэтому в отличие от detector.py/recognizers.py этот
модуль полностью юнит-тестируется (см. backend/tests/test_pdf_extract.py и
docs/testing.md).
"""

from typing import List, Tuple

import numpy as np
import pypdfium2 as pdfium

PDF_RENDER_DPI = 200
PROBE_PAGE_COUNT = 2


def render_page(page: pdfium.PdfPage, dpi: int = PDF_RENDER_DPI) -> np.ndarray:
    """Рендерит страницу PDF в numpy-изображение (RGB) при заданном DPI"""
    bitmap = page.render(scale=dpi / 72)
    return np.array(bitmap.to_pil().convert("RGB"))


def _pdf_x_to_pix(x: float, page_width: float, image_width: int) -> float:
    return x / page_width * image_width


def _pdf_y_to_pix(y: float, page_height: float, image_height: int) -> float:
    # PDF: ось Y растёт снизу вверх; растровое изображение: сверху вниз
    return image_height - (y / page_height * image_height)


def extract_page_text_boxes(
    page: pdfium.PdfPage, image_width: int, image_height: int
) -> List[Tuple[List[List[float]], str]]:
    """Извлекает текстовые боксы страницы PDF из текстового слоя (без OCR).

    Группировка — по PDF text-объектам (аналог прежнего, не входящего в
    сервис прототипа, см. predict.py::extract_text_pdf в корне репозитория).
    Один PDF text-объект обычно соответствует одному вызову показа текста
    (Tj/TJ) — на практике чаще всего строка или её часть, не гарантированная
    построчная группировка, а лучшее доступное приближение.

    Возвращает список (box, text), box — [[x0,y0],[x1,y0],[x1,y1],[x0,y1]]
    в пиксельных координатах изображения, отрендеренного через render_page()
    ДЛЯ ЭТОЙ ЖЕ страницы этим же image_width/image_height (координаты зависят
    от масштаба рендера).
    """
    page_width, page_height = page.get_size()
    textpage = page.get_textpage()
    char_boxes = [textpage.get_charbox(i) for i in range(textpage.count_chars())]

    result: List[Tuple[List[List[float]], str]] = []
    for obj in page.get_objects(filter=[pdfium.raw.FPDF_PAGEOBJ_TEXT]):
        left_b, bottom_b, right_b, top_b = obj.get_pos()
        indices = [
            i
            for i, box in enumerate(char_boxes)
            if box[0] >= left_b
            and box[2] <= right_b
            and box[1] >= bottom_b
            and box[3] <= top_b
        ]
        if not indices:
            continue

        text = "".join(textpage.get_text_range(i, 1) for i in indices).strip()
        if not text:
            continue

        boxes = [char_boxes[i] for i in indices]
        left = min(b[0] for b in boxes)
        bottom = min(b[1] for b in boxes)
        right = max(b[2] for b in boxes)
        top = max(b[3] for b in boxes)

        x0 = _pdf_x_to_pix(left, page_width, image_width)
        y0 = _pdf_y_to_pix(top, page_height, image_height)
        x1 = _pdf_x_to_pix(right, page_width, image_width)
        y1 = _pdf_y_to_pix(bottom, page_height, image_height)

        result.append(([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], text))

    return result


def page_has_text_layer(page: pdfium.PdfPage) -> bool:
    """True, если у страницы PDF есть непустой извлекаемый текстовый слой"""
    textpage = page.get_textpage()
    if textpage.count_chars() == 0:
        return False
    return bool(textpage.get_text_bounded().strip())


def document_has_text_layer(
    pdf_doc: pdfium.PdfDocument, probe_pages: int = PROBE_PAGE_COUNT
) -> bool:
    """Решение "использовать текстовый слой" на уровне всего документа.

    Проверяет только первые `probe_pages` страниц (по умолчанию 2) — если ни
    одна из них не содержит текста, документ целиком обрабатывается через
    обычный OCR-консенсус, даже если текстовый слой появляется на более
    поздних страницах (осознанное упрощение, см. план/PRD).
    """
    for page_index in range(min(probe_pages, len(pdf_doc))):
        if page_has_text_layer(pdf_doc[page_index]):
            return True
    return False
```
- **MIRROR**: ERROR_HANDLING здесь **не** применяется внутри самого модуля —
  `pdf_extract.py` остаётся набором чистых функций без `try/except`; вызывающая
  сторона (`pipeline.py::_process_pdf`) оборачивает вызовы в `try/except` по
  паттерну ERROR_HANDLING (как для `detector.detect`/`recognize_*`, которые
  сами гасят исключения, а `pipeline.run` — нет, оборачивает снаружи).
- **IMPORTS**: `numpy as np`, `pypdfium2 as pdfium`, `from typing import List, Tuple`.
- **GOTCHA**: Использовать `textpage.get_text_bounded()` (без аргументов) для
  текста всей страницы и `textpage.get_text_range(i, 1)` для отдельных
  символов — НЕ `get_text_range()`/`get_text_range(0, -1)` (см. External
  Documentation, KEY_INSIGHT про warning). `pdf_doc[i]` — только int-индекс,
  без срезов.
- **VALIDATE**: Task 8 (тесты) покрывает этот модуль; дополнительно
  `ruff check backend/pdf_extract.py` — 0 замечаний.

### Task 4: Рефакторинг `backend/pipeline.py`
- **ACTION**: Вынести обработку боксов в переиспользуемый helper, добавить
  поиск и обработку `.pdf`-файлов.
- **IMPLEMENT** — полное новое содержимое файла:
```python
import os
import uuid
from glob import glob
from typing import Callable, List, Optional, Tuple

import numpy as np
import pypdfium2 as pdfium
from PIL import Image

from backend import pdf_extract
from backend.config import IMAGE_EXTENSIONS, PDF_EXTENSIONS
from backend.consensus import vote
from backend.detector import Detector
from backend.recognizers import (
    DEFAULT_LATIN_MODEL_SIZE,
    recognize_paddle,
    recognize_paddle_latin,
    recognize_surya,
    recognize_tesseract,
)

MIN_CROP_PIX = 10


def _save_crop(img_crop: np.ndarray, output_dir: str) -> str:
    """Сохраняет кроп в output_dir/crops с уникальным именем, возвращает имя файла"""
    crop_dir = os.path.join(output_dir, "crops")
    os.makedirs(crop_dir, exist_ok=True)
    crop_name = f"crop_{uuid.uuid4().hex}.webp"
    Image.fromarray(img_crop).save(os.path.join(crop_dir, crop_name), "WEBP")
    return crop_name


def _process_boxes(
    image: Image.Image,
    numpy_image: np.ndarray,
    boxes,
    output_dir: str,
    threshold: float,
    preferred_model: Optional[str],
    lang: str,
    latin_model_size: str,
    tesseract_lang: str,
    source_label: str,
) -> Tuple[List[str], List[str]]:
    """Прогоняет обнаруженные детектором боксы через консенсус 3 движков.

    Общая логика для растровых изображений и страниц PDF без текстового слоя
    (см. run()/_process_pdf()).
    """
    good_lines: List[str] = []
    needs_review_lines: List[str] = []

    for box in boxes:
        try:
            x0, y0 = box[0]
            x2, y2 = box[2]
            img_crop = numpy_image[int(y0) : int(y2), int(x0) : int(x2)]

            if img_crop.shape[0] <= MIN_CROP_PIX or img_crop.shape[1] <= MIN_CROP_PIX:
                continue

            paddle_result = (
                recognize_paddle(img_crop)
                if lang == "ru"
                else recognize_paddle_latin(img_crop, latin_model_size)
            )
            results = {
                "paddle": paddle_result,
                "surya": recognize_surya(image, box),
                "tesseract": recognize_tesseract(img_crop, tesseract_lang),
            }
            bucket, text, _engine = vote(results, threshold, preferred_model)

            crop_name = _save_crop(img_crop, output_dir)
            line = f"crops/{crop_name}\t{text}\n"
            if bucket == "good":
                good_lines.append(line)
            else:
                needs_review_lines.append(line)
        except Exception as e:
            print(f"Ошибка распознавания строки в {source_label}: {e}")
            continue

    return good_lines, needs_review_lines


def _process_pdf(
    file_path: str,
    get_detector: Callable[[], Detector],
    output_dir: str,
    threshold: float,
    preferred_model: Optional[str],
    lang: str,
    latin_model_size: str,
    tesseract_lang: str,
    extract_pdf_text_layer: bool,
) -> Tuple[List[str], List[str]]:
    """Обрабатывает один PDF-файл постранично: либо прямым извлечением
    текстового слоя (без OCR), либо обычным OCR-консенсусом растровых страниц.

    Решение "использовать текстовый слой" принимается один раз для всего
    документа (pdf_extract.document_has_text_layer) — если да, страницы без
    текста внутри такого документа просто пропускаются, а не отправляются в
    OCR (осознанное упрощение, см. план/PRD).
    """
    good_lines: List[str] = []
    needs_review_lines: List[str] = []

    pdf_doc = pdfium.PdfDocument(file_path)
    try:
        use_text_layer = extract_pdf_text_layer and pdf_extract.document_has_text_layer(pdf_doc)

        for page_index in range(len(pdf_doc)):
            page = pdf_doc[page_index]
            source_label = f"{file_path} (страница {page_index + 1})"
            try:
                numpy_image = pdf_extract.render_page(page)
            except Exception as e:
                print(f"Ошибка рендеринга {source_label}: {e}")
                continue

            if use_text_layer:
                if not pdf_extract.page_has_text_layer(page):
                    continue
                image_height, image_width = numpy_image.shape[:2]
                try:
                    boxes_text = pdf_extract.extract_page_text_boxes(
                        page, image_width, image_height
                    )
                except Exception as e:
                    print(f"Ошибка извлечения текстового слоя {source_label}: {e}")
                    continue

                for box, text in boxes_text:
                    bx0, by0 = box[0]
                    bx2, by2 = box[2]
                    img_crop = numpy_image[int(by0) : int(by2), int(bx0) : int(bx2)]
                    if img_crop.shape[0] <= MIN_CROP_PIX or img_crop.shape[1] <= MIN_CROP_PIX:
                        continue
                    crop_name = _save_crop(img_crop, output_dir)
                    good_lines.append(f"crops/{crop_name}\t{text}\n")
            else:
                image = Image.fromarray(numpy_image)
                boxes = get_detector().detect(numpy_image)
                page_good, page_review = _process_boxes(
                    image,
                    numpy_image,
                    boxes,
                    output_dir,
                    threshold,
                    preferred_model,
                    lang,
                    latin_model_size,
                    tesseract_lang,
                    source_label,
                )
                good_lines.extend(page_good)
                needs_review_lines.extend(page_review)
    finally:
        pdf_doc.close()

    return good_lines, needs_review_lines


def run(
    input_dir: str,
    output_dir: str,
    threshold: float,
    preferred_model: Optional[str] = None,
    lang: str = "ru",
    latin_model_size: str = DEFAULT_LATIN_MODEL_SIZE,
    extract_pdf_text_layer: bool = True,
) -> Tuple[int, int]:
    """Обрабатывает папку документов (изображения + PDF): детекция ->
    распознавание x3 -> голосование; для PDF с текстовым слоем — прямое
    извлечение текста+координат без OCR (см. extract_pdf_text_layer).

    Возвращает (кол-во хороших строк, кол-во строк на проверку) и пишет
    good.txt/needs_review.txt в output_dir в формате path\ttext\n.

    good.txt/needs_review.txt перезаписываются на каждый запуск (они
    описывают только результат этого запуска), а файлы в crops/ получают
    уникальное имя (uuid4) на каждый кроп, поэтому повторный запуск с тем же
    output_dir не портит содержимое уже сохранённых/импортированных кропов
    из прошлых запусков.
    """
    os.makedirs(output_dir, exist_ok=True)

    detector: Optional[Detector] = None

    def get_detector() -> Detector:
        nonlocal detector
        if detector is None:
            detector = Detector()
        return detector

    matched_files = []
    for ext in IMAGE_EXTENSIONS:
        matched_files.extend(glob(os.path.join(input_dir, f"*{ext}")))
    pdf_files = []
    for ext in PDF_EXTENSIONS:
        pdf_files.extend(glob(os.path.join(input_dir, f"*{ext}")))

    good_lines = []
    needs_review_lines = []
    tesseract_lang = "rus" if lang == "ru" else "eng"

    for file_path in matched_files:
        try:
            image = Image.open(file_path).convert("RGB")
            numpy_image = np.array(image)
            boxes = get_detector().detect(numpy_image)
        except Exception as e:
            print(f"Ошибка обработки файла {file_path}: {e}")
            continue

        page_good, page_review = _process_boxes(
            image,
            numpy_image,
            boxes,
            output_dir,
            threshold,
            preferred_model,
            lang,
            latin_model_size,
            tesseract_lang,
            file_path,
        )
        good_lines.extend(page_good)
        needs_review_lines.extend(page_review)

    for file_path in pdf_files:
        try:
            page_good, page_review = _process_pdf(
                file_path,
                get_detector,
                output_dir,
                threshold,
                preferred_model,
                lang,
                latin_model_size,
                tesseract_lang,
                extract_pdf_text_layer,
            )
        except Exception as e:
            print(f"Ошибка обработки файла {file_path}: {e}")
            continue
        good_lines.extend(page_good)
        needs_review_lines.extend(page_review)

    with open(os.path.join(output_dir, "good.txt"), "w", encoding="utf-8") as f:
        f.write("".join(good_lines))
    with open(os.path.join(output_dir, "needs_review.txt"), "w", encoding="utf-8") as f:
        f.write("".join(needs_review_lines))

    return len(good_lines), len(needs_review_lines)
```
- **MIRROR**: CROP_SAVE_AND_LINE_FORMAT, BOX_FORMAT, ERROR_HANDLING,
  GLOB_BY_EXTENSION_TUPLE (все выше).
- **IMPORTS**: `pypdfium2 as pdfium`, `from backend import pdf_extract`,
  `from backend.config import IMAGE_EXTENSIONS, PDF_EXTENSIONS`,
  `from typing import Callable, List, Optional, Tuple`.
- **GOTCHA**: `Detector()` теперь создаётся ЛЕНИВО через замыкание
  `get_detector()` — раньше создавался безусловно в начале `run()`. Это
  важно для сценария "только PDF с текстовым слоем": PaddleOCR-модель
  детекции вообще не загружается, что и есть смысл фичи ("распознавание
  вообще не нужно"). НЕ создавать `Detector()` заранее.
  `_process_pdf` закрывает `pdf_doc` в `finally` — на Windows незакрытый
  файл-хендл PDF может помешать повторному чтению/удалению файла.
- **VALIDATE**:
  `pytest backend/tests/ -k "not pdf_extract"` (существующие тесты не
  сломаны — они не зависят от pipeline.py напрямую, но модуль должен хотя бы
  импортироваться: `python -c "import backend.pipeline"`).
  `ruff check backend/pipeline.py` и `ruff format --check backend/pipeline.py`
  — оба уже прогнаны на этом же коде при подготовке плана (временно как
  `backend/_plan_check_pipeline.py`, удалён после проверки): 0 замечаний
  линтера, `ruff format` не меняет ничего сверх уже применённых в коде выше
  переносов строк.

### Task 5: Прокинуть флаг через `backend/jobs.py`
- **ACTION**: Добавить параметр `extract_pdf_text_layer` в `start_job`/`_run_job`.
- **IMPLEMENT**:
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
            input_dir,
            output_dir,
            threshold,
            preferred_model,
            lang,
            latin_model_size,
            extract_pdf_text_layer,
        )
        ...  # без изменений

def start_job(
    input_dir: str,
    output_dir: str,
    threshold: float,
    preferred_model: Optional[str] = None,
    lang: str = "ru",
    latin_model_size: str = DEFAULT_LATIN_MODEL_SIZE,
    extract_pdf_text_layer: bool = True,
) -> str:
    job_id = str(uuid.uuid4())
    _jobs[job_id] = JobState(status="running")
    thread = threading.Thread(
        target=_run_job,
        args=(
            job_id,
            input_dir,
            output_dir,
            threshold,
            preferred_model,
            lang,
            latin_model_size,
            extract_pdf_text_layer,
        ),
        daemon=True,
    )
    thread.start()
    return job_id
```
- **MIRROR**: Существующий IN_MEMORY_STATE_PATTERN (`backend/jobs.py:29-79`) —
  позиционные параметры в том же порядке, что и `pipeline.run`.
- **IMPORTS**: Без изменений.
- **GOTCHA**: Порядок позиционных аргументов между `start_job` -> `_run_job`
  -> `pipeline.run` должен совпадать — как и сейчас с `lang`/`latin_model_size`.
- **VALIDATE**: `python -c "import backend.jobs"`; существующие
  `backend/tests/` не трогают `jobs.py` напрямую — регрессии по факту
  проверяются через Task 9 (ручная проверка) и Task 4's VALIDATE.

### Task 6: Новое поле API в `backend/main.py`
- **ACTION**: Добавить `extract_pdf_text_layer` в `RunRequest` и передать в `start_job`.
- **IMPLEMENT**:
```python
class RunRequest(BaseModel):
    input_dir: str
    output_dir: str
    score_threshold: float = DEFAULT_SCORE_THRESHOLD
    preferred_model: Optional[str] = None
    lang: str = "ru"
    latin_model_size: str = DEFAULT_LATIN_MODEL_SIZE
    # Если во входной папке есть PDF с извлекаемым текстовым слоем —
    # вытащить текст+координаты напрямую (без OCR) и сразу пометить как good.
    # См. backend/README.md, раздел "PDF".
    extract_pdf_text_layer: bool = True


@app.post("/run")
def run(req: RunRequest):
    ...  # существующие проверки без изменений
    job_id = start_job(
        req.input_dir,
        req.output_dir,
        req.score_threshold,
        req.preferred_model,
        req.lang,
        req.latin_model_size,
        req.extract_pdf_text_layer,
    )
    return {"job_id": job_id}
```
- **MIRROR**: Существующий стиль `RunRequest`/`Pydantic BaseModel` с
  комментариями над полями, объясняющими семантику не-очевидных значений
  (см. `lang`/`latin_model_size` в текущем файле).
- **IMPORTS**: Без изменений.
- **GOTCHA**: Порядок позиционных аргументов в `start_job(...)` — новый
  аргумент добавляется В КОНЕЦ, чтобы не сломать порядок существующих.
- **VALIDATE**: `uvicorn backend.main:app --reload` стартует без ошибок;
  `curl -X POST http://127.0.0.1:8756/run -H "Content-Type: application/json" -d "{\"input_dir\":\"...\",\"output_dir\":\"...\"}"`
  (без `extract_pdf_text_layer` в теле) отрабатывает — подтверждает
  дефолт `true`.

### Task 7: Чекбокс в UI (`frontend/src/ui/generation_view.py`)
- **ACTION**: Добавить контрол и включить поле в JSON-payload запроса `/run`.
- **IMPLEMENT** (внутри `_render_run_controls`, после `preferred = st.selectbox(...)`):
```python
    extract_pdf_text_layer = st.checkbox(
        "Извлекать текст из PDF напрямую, без OCR (если есть текстовый слой)",
        value=True,
        key="consensus_extract_pdf",
    )

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
- **MIRROR**: Существующие `st.text_input`/`st.slider`/`st.selectbox` с
  `key=...` (session-state как единственное хранилище состояния, см.
  `CLAUDE.md`, раздел Code Style).
- **IMPORTS**: Без изменений (уже есть `streamlit as st`, `requests`).
- **GOTCHA**: `key="consensus_extract_pdf"` не должен конфликтовать с уже
  занятыми ключами (`consensus_input`, `consensus_output`,
  `consensus_threshold`, `consensus_preferred`, `consensus_run`,
  `consensus_status`, `consensus_to_manual`, `consensus_job_id`) — новый
  ключ уникален, конфликта нет.
- **VALIDATE**: Ручная проверка в браузере (см. Manual Validation ниже) —
  Streamlit-UI не покрыт автотестами (см. `CLAUDE.md`, раздел Testing).

### Task 8: Тесты `backend/tests/test_pdf_extract.py`
- **ACTION**: Написать юнит-тесты на синтетических PDF (без внешних PDF-либ,
  вручную собранный минимальный PDF-байткод — проверено вживую, что
  `pypdfium2` его корректно парсит).
- **IMPLEMENT**:
```python
import io
from typing import List, Optional, Tuple

import pypdfium2 as pdfium
import pytest

from backend import pdf_extract


def _build_pdf(
    pages: List[Optional[Tuple[str, int, int]]], page_w: int = 400, page_h: int = 400
) -> bytes:
    """Собирает минимальный валидный PDF без внешних библиотек.

    pages: список, где каждый элемент — None (пустая страница без текста)
    либо (text, x, y) — страница с одной строкой текста Helvetica 24pt,
    показанной оператором Tj в точке (x, y) (PDF user space, Y снизу вверх).

    Схема нумерации объектов (фиксированная, соответствует порядку append
    ниже): 1 Catalog, 2 Pages, 3..2+n Page-объекты, 3+n Font, 4+n..3+2n
    Content-стримы.
    """
    n = len(pages)
    font_obj_num = 3 + n
    content_obj_nums = [4 + n + i for i in range(n)]

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        (
            f"<< /Type /Pages /Kids [{' '.join(f'{3 + i} 0 R' for i in range(n))}] "
            f"/Count {n} >>"
        ).encode(),
    ]
    for i, p in enumerate(pages):
        resources = f"<< /Font << /F1 {font_obj_num} 0 R >> >>" if p is not None else "<< >>"
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_w} {page_h}] "
                f"/Resources {resources} /Contents {content_obj_nums[i]} 0 R >>"
            ).encode()
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for p in pages:
        stream = b"" if p is None else f"BT /F1 24 Tf {p[1]} {p[2]} Td ({p[0]}) Tj ET".encode()
        objects.append(f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream")

    buf = io.BytesIO()
    buf.write(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(buf.tell())
        buf.write(f"{i} 0 obj\n".encode())
        buf.write(obj)
        buf.write(b"\nendobj\n")
    xref_offset = buf.tell()
    total = len(objects) + 1
    buf.write(f"xref\n0 {total}\n".encode())
    buf.write(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        buf.write(f"{off:010d} 00000 n \n".encode())
    buf.write(f"trailer\n<< /Size {total} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF".encode())
    return buf.getvalue()


@pytest.fixture
def text_pdf_doc():
    doc = pdfium.PdfDocument(_build_pdf([("Hello World", 72, 300)]))
    yield doc
    doc.close()


@pytest.fixture
def blank_pdf_doc():
    doc = pdfium.PdfDocument(_build_pdf([None]))
    yield doc
    doc.close()


def test_page_has_text_layer_true_for_text_page(text_pdf_doc):
    assert pdf_extract.page_has_text_layer(text_pdf_doc[0]) is True


def test_page_has_text_layer_false_for_blank_page(blank_pdf_doc):
    assert pdf_extract.page_has_text_layer(blank_pdf_doc[0]) is False


def test_document_has_text_layer_true_when_second_probed_page_has_text():
    doc = pdfium.PdfDocument(_build_pdf([None, ("Page Two", 72, 300)]))
    try:
        assert pdf_extract.document_has_text_layer(doc) is True
    finally:
        doc.close()


def test_document_has_text_layer_false_when_text_starts_after_probe_range():
    # Осознанное упрощение: пробинг смотрит только первые 2 страницы.
    doc = pdfium.PdfDocument(_build_pdf([None, None, ("Page Three", 72, 300)]))
    try:
        assert pdf_extract.document_has_text_layer(doc) is False
    finally:
        doc.close()


def test_document_has_text_layer_false_for_fully_blank_document(blank_pdf_doc):
    assert pdf_extract.document_has_text_layer(blank_pdf_doc) is False


def test_render_page_returns_rgb_uint8_array(text_pdf_doc):
    image = pdf_extract.render_page(text_pdf_doc[0], dpi=200)
    assert image.ndim == 3
    assert image.shape[2] == 3
    assert image.dtype.name == "uint8"
    # страница 400x400pt при 200dpi (scale=200/72) -> ~1112x1112px
    assert image.shape[0] == pytest.approx(1112, abs=2)
    assert image.shape[1] == pytest.approx(1112, abs=2)


def test_extract_page_text_boxes_returns_text_and_pixel_box(text_pdf_doc):
    page = text_pdf_doc[0]
    image = pdf_extract.render_page(page, dpi=200)
    image_height, image_width = image.shape[:2]

    boxes = pdf_extract.extract_page_text_boxes(page, image_width, image_height)

    assert len(boxes) == 1
    box, text = boxes[0]
    assert text == "Hello World"
    x0, y0 = box[0]
    x2, y2 = box[2]
    assert 0 <= x0 < x2 <= image_width
    assert 0 <= y0 < y2 <= image_height


def test_extract_page_text_boxes_empty_for_blank_page(blank_pdf_doc):
    page = blank_pdf_doc[0]
    image = pdf_extract.render_page(page, dpi=200)
    image_height, image_width = image.shape[:2]

    assert pdf_extract.extract_page_text_boxes(page, image_width, image_height) == []
```
- **MIRROR**: TEST_STRUCTURE (плоские `test_*` функции), но с фикстурами
  (`@pytest.fixture`) там, где нужен переиспользуемый PDF-документ — как в
  `test_models_status.py` (`@pytest.fixture(autouse=True)` для сброса
  состояния), только здесь `autouse=False` (фикстура нужна не всем тестам).
- **IMPORTS**: `io`, `typing.List/Optional/Tuple`, `pypdfium2 as pdfium`,
  `pytest`, `from backend import pdf_extract`.
- **GOTCHA**: Тестовый PDF использует ТОЛЬКО ASCII-текст (`Helvetica` —
  стандартный Type1-шрифт без кириллической кодировки) — не пытаться
  проверять извлечение кириллицы через этот синтетический PDF-билдер
  (потребовал бы embedded-шрифт с полноценной кодировкой, вне рамок теста).
  `pytest.approx(1112, abs=2)` — рендер даёт `ceil`-подобное округление
  (400 * 200/72 ≈ 1111.11 -> 1112 на практике), допуск `abs=2` покрывает
  вариации округления между версиями pdfium.
- **VALIDATE**: `pytest backend/tests/test_pdf_extract.py -v` — все тесты
  зелёные (весь код этой задачи и `pdf_extract.py` из Task 3 уже прогнан
  один в один через `pytest` и `ruff check --select E,F,W,I,B` в реальном
  окружении с `pypdfium2==4.30.1`/`numpy==1.26.4` при подготовке этого плана
  — 8/8 тестов проходят, 0 замечаний линтера; `ruff format` перенёс сигнатуру
  `_build_pdf(...)` на 3 строки — этот перенос уже применён в коде выше).

### Task 9: Документация — `backend/README.md`
- **ACTION**: Описать новое поведение и поле API.
- **IMPLEMENT**: В раздел `## API`, строку описания `POST /run`, добавить
  `extract_pdf_text_layer: bool` в JSON-схему запроса. Добавить новый
  подраздел после `## API`:
```markdown
## PDF

Входная папка (`input_dir`) может содержать `.pdf`-файлы наравне с
изображениями. Для каждого PDF сначала проверяются первые 2 страницы на
наличие извлекаемого текстового слоя (`extract_pdf_text_layer=true`,
значение по умолчанию):

- **Есть текстовый слой** — текст и координаты вытаскиваются напрямую через
  `pypdfium2` (без OCR), каждая строка сразу попадает в `good.txt`.
  Страницы без текста внутри такого документа пропускаются (не отправляются
  в OCR-fallback).
- **Нет текстового слоя** (в т.ч. если текст появляется только начиная с
  3-й страницы — проверяются только первые 2) — документ обрабатывается
  постранично как обычное растровое изображение, через тот же
  3-движковый OCR-консенсус.

**Известное ограничение**: "текстовый слой" не отличается от текста,
добавленного самим сканером (searchable PDF от сканирующего ПО) — такой слой
может быть неточным (собственный OCR сканера), но будет доверчиво помечен
как `good`. Для папок с такими сканами явно выключайте
`extract_pdf_text_layer`.
```
- **MIRROR**: Существующий стиль `backend/README.md` (короткие абзацы,
  markdown-списки, отсылки к другим файлам).
- **IMPORTS**: N/A
- **GOTCHA**: Не потерять существующее предупреждение про
  отсутствие аутентификации/ограничений на пути (секция "Запуск") — плюс
  дописать про PDF после `## API`, до этой секции или после — выбрать место
  так, чтобы не разрывать существующий текст.
- **VALIDATE**: Визуальная проверка markdown (рендер в редакторе/GitHub).

### Task 10: Документация — `docs/testing.md`
- **ACTION**: Уточнить, какие backend-модули тестируются.
- **IMPLEMENT**: Заменить абзац (строки 16-20) на:
```markdown
Тесты покрывают `src/` (модели, бэкапы, аннотации), `backend/consensus.py`
и `backend/pdf_extract.py`.
`backend/detector.py` и `backend/recognizers.py` не тестируются — они лениво
импортируют тяжёлые ML-зависимости (PaddleOCR, SuryaOCR, pytesseract) только
внутри методов и требуют реальных моделей/системного Tesseract, что не подходит
для юнит-тестов (см. `backend/README.md`). `backend/pdf_extract.py`
использует `pypdfium2` — лёгкую самодостаточную библиотеку без скачиваемых
моделей и системных бинарников — поэтому, в отличие от них, полностью
юнит-тестируется на синтетических PDF (`pypdfium2` и `numpy` добавлены в
`requirements-dev.txt` именно для этого).
```
- **MIRROR**: Существующий стиль файла.
- **IMPORTS**: N/A
- **GOTCHA**: Не менять формулировку про `detector.py`/`recognizers.py` по
  существу — она остаётся верной, только дополняется про `pdf_extract.py`.
- **VALIDATE**: Визуальная проверка.

---

## Testing Strategy

### Unit Tests (см. Task 8 — полный код)

| Test | Input | Expected Output | Edge Case? |
|---|---|---|---|
| `test_page_has_text_layer_true_for_text_page` | Страница с "Hello World" | `True` | — |
| `test_page_has_text_layer_false_for_blank_page` | Пустая страница | `False` | Пустой ввод |
| `test_document_has_text_layer_true_when_second_probed_page_has_text` | [пусто, "Page Two"] | `True` | Текст на 2-й из пробируемых |
| `test_document_has_text_layer_false_when_text_starts_after_probe_range` | [пусто, пусто, "Page Three"] | `False` | Текст ЗА пределами пробинга (граница поведения) |
| `test_document_has_text_layer_false_for_fully_blank_document` | [пусто] | `False` | Полностью пустой документ |
| `test_render_page_returns_rgb_uint8_array` | Страница 400x400pt, dpi=200 | shape≈(1112,1112,3), uint8 | Проверка масштабирования |
| `test_extract_page_text_boxes_returns_text_and_pixel_box` | Страница с текстом | 1 бокс, текст="Hello World", координаты внутри изображения | — |
| `test_extract_page_text_boxes_empty_for_blank_page` | Пустая страница | `[]` | Пустой ввод |

### Edge Cases Checklist
- [x] Пустой PDF (страница без текста) — `test_*_false_for_blank_page`
- [x] Текст за пределами пробируемых страниц — `test_document_has_text_layer_false_when_text_starts_after_probe_range`
- [ ] Битый/повреждённый PDF-файл — не покрыт unit-тестом (обрабатывается
      broad `try/except` в `pipeline.run`'s PDF-цикле, как и битые изображения
      сейчас — см. ERROR_HANDLING; ручная проверка в Manual Validation)
- [ ] Пароль-защищённый PDF — сознательно не поддерживается (см. NOT Building)
- [ ] Повёрнутая страница (`/Rotate`) — сознательно не проверяется (см. Risks)
- [ ] Очень большой PDF (много страниц) — не тестируется отдельно, тот же
      синхронный однопоточный `pipeline.run`, что и сейчас для папки с
      множеством изображений

---

## Validation Commands

### Static Analysis
```bash
ruff check backend/pdf_extract.py backend/pipeline.py backend/jobs.py backend/main.py frontend/src/ui/generation_view.py
ruff format --check backend/pdf_extract.py backend/pipeline.py backend/jobs.py backend/main.py frontend/src/ui/generation_view.py
```
EXPECT: Zero замечаний.

### Unit Tests
```bash
pip install -r requirements-dev.txt
pytest backend/tests/test_pdf_extract.py -v
```
EXPECT: Все тесты зелёные, установка requirements-dev.txt не требует
`backend/requirements.txt` (см. GOTCHA про pypdfium2/numpy в requirements-dev.txt).

### Full Test Suite
```bash
pytest
```
EXPECT: Все существующие тесты (`frontend/tests/`, `backend/tests/`)
по-прежнему проходят + новые тесты `test_pdf_extract.py`. Регрессий нет.

### Backend Manual Validation (нужны установленные backend/requirements.txt +
системный Tesseract — см. backend/README.md; без них можно проверить только
чисто-PDF-текстовый-слой сценарий, т.к. Detector() лениво не создаётся, если
все PDF идут через текстовый слой)
```bash
uvicorn backend.main:app --reload
```
- [ ] `POST /run` с папкой, содержащей PDF с текстовым слоем и
      `extract_pdf_text_layer=true` — `good.txt` в `output_dir` содержит
      строки `crops/*.webp\t<текст>`, `needs_review.txt` пуст для этих
      строк, `crops/` содержит соответствующие `.webp`-файлы, ОТКРЫВАЮЩИЕСЯ
      и визуально соответствующие тексту.
- [ ] Тот же PDF с `extract_pdf_text_layer=false` — файл обрабатывается как
      скан (уходит в OCR-консенсус, результат может отличаться).
- [ ] Папка с PDF-сканом без текстового слоя (`extract_pdf_text_layer=true`
      или `false` — без разницы) — результат идентичен в обоих случаях,
      OCR-консенсус как раньше.
- [ ] Смешанная папка (изображения + оба типа PDF одновременно) —
      `good_count`/`needs_review_count` в ответе `GET /result/{job_id}`
      суммируют все источники корректно.
- [ ] `📥 Перейти к разметке результатов` в UI после такого запуска —
      `AnnotationManager` успешно загружает все записи (включая
      PDF-извлечённые), редактор показывает кроп-изображения корректно.

### Frontend Manual Validation
```bash
cd frontend && streamlit run app.py --server.enableXsrfProtection=false
```
- [ ] Режим "🤖 Авторазметка" показывает новый чекбокс "Извлекать текст из
      PDF..." со значением по умолчанию включено (☑).
- [ ] Снятие чекбокса и запуск — в теле запроса `POST /run`
      (через network-инспектор браузера или лог backend) видно
      `"extract_pdf_text_layer": false`.

---

## Acceptance Criteria
- [ ] Все задачи выполнены
- [ ] Все команды валидации проходят
- [ ] Новые тесты написаны и зелёные (`backend/tests/test_pdf_extract.py`)
- [ ] Нет ошибок типов/линта (`ruff check`)
- [ ] Соответствует UX-дизайну (чекбокс в UI, поведение по умолчанию)

## Completion Checklist
- [ ] Код следует обнаруженным паттернам (см. Patterns to Mirror)
- [ ] Обработка ошибок соответствует стилю проекта (broad try/except + print)
- [ ] Новый тестовый файл соответствует стилю существующих тестов
- [ ] Нет хардкода путей/значений за пределами оговорённых констант
      (`PDF_RENDER_DPI`, `PROBE_PAGE_COUNT`)
- [ ] Документация обновлена (`backend/README.md`, `docs/testing.md`)
- [ ] Нет лишнего скоупа (без per-page OCR fallback внутри text-layer PDF,
      без конфигурируемого DPI/probe-count через API)
- [ ] Самодостаточно — вопросов при реализации возникать не должно

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| PDF text-объект ≠ строка текста (может быть словом/фрагментом в зависимости от того, чем сгенерирован PDF) — кропы из PDF-пути могут быть мельче/крупнее, чем кропы из OCR-детектора для того же типа контента | Medium | Medium (неоднородная гранулярность обучающих данных в одной выборке) | Задокументировано как известное ограничение (совпадает с поведением прежнего прототипа `predict.py`); рекомендуется визуально проверить первые реальные PDF перед массовым использованием |
| "Текстовый слой" может быть добавлен самим сканирующим ПО (searchable PDF) и быть неточным по координатам/тексту, но будет безусловно помечен `good` | Medium | High (подрывает саму цель фичи — "точный текст+координаты по определению" оказывается неверным для этого случая) | Не решается автоматически в этом плане; явно задокументировано в `backend/README.md`, рекомендация выключать `extract_pdf_text_layer` для папок со сканами |
| Повёрнутые страницы (`/Rotate`) — маппинг координат не проверен для этого случая, `page.get_size()`/рендер могут (не) учитывать поворот согласованно | Low-Medium | High если возникает (тихо неверные кропы, помеченные `good`) | Не обрабатывается в этом плане; рекомендуется точечно проверить документ с известным `/Rotate` перед доверием результату в проде |
| `pypdfium2`/`numpy` добавлены в `requirements-dev.txt`, что расширяет "лёгкий" набор dev-зависимостей | Low | Low (обе библиотеки самодостаточны, без скачиваемых моделей, `pypdfium2` — компилированное расширение ~15МБ) | Осознанное, задокументированное решение (см. `docs/testing.md`) |

## Notes
- Формат вывода (`good.txt`/`needs_review.txt`, `crops/*.webp`) не меняется
  — существующий frontend-код (`_build_manager_from_output` в
  `generation_view.py`, `AnnotationManager.load_from_file`) работает без
  изменений с PDF-извлечёнными строками.
- `Detector()` (PaddleOCR-модель детекции строк) теперь создаётся лениво —
  папка, состоящая только из PDF с текстовым слоем, вообще не грузит ни одну
  ML-модель. Это прямое следствие требования "распознавание вообще не нужно"
  и попутно ускоряет холодный старт для такого сценария.
- Прежний скрипт `predict.py` (не часть сервиса, приватная `ocr_library`)
  содержит референсный прототип того же самого извлечения — этот план
  переносит его идею (группировка по text-объектам, маппинг координат) на
  `pypdfium2` напрямую, без `ocr_library`/`FileIterator`.
