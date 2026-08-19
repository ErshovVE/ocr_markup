# Plan: Стартовая страница с режимами «Авторазметка» / «Ручная разметка»

## Summary
Разделить `ocr_markup` frontend на два явных режима, выбираемых на стартовом
экране: **Авторазметка** (настройка и запуск OCR-consensus backend'а, статус
моделей Paddle/Surya/Tesseract с возможностью подготовки/скачивания) и
**Ручная разметка** (текущий флоу редактирования без изменений поведения).
Backend получает два новых эндпоинта для статуса/подготовки моделей. Переход
из авторазметки в ручную разметку выполняется программно (без file_uploader),
подгружая `good.txt`/`needs_review.txt` из `output_dir` напрямую в
`AnnotationManager`.

## User Story
Как пользователь, у которого ещё нет файла разметки, я хочу сгенерировать его
через OCR-consensus и сразу перейти к проверке результатов, вместо того чтобы
имитировать загрузку несуществующего файла ради доступа к скрытой в сайдбаре
секции запуска моделей.

## Problem → Solution
Сейчас `render_consensus_section` (`frontend/src/ui/consensus_view.py`)
вызывается только из `render_sidebar` (`frontend/src/ui/sidebar.py:83`),
которая в свою очередь вызывается только внутри `if uploaded_file:` в
`frontend/app.py:61-114` — т.е. запуск моделей физически недостижим без уже
существующей разметки. → Стартовый экран с явным выбором режима; авторазметка
не требует загрузки файла и после успешного запуска сама формирует
`AnnotationManager` для проверки результатов.

## Metadata
- **Complexity**: Large (новый backend API + реструктуризация frontend entry point + миграция существующей логики без регрессий)
- **Source PRD**: N/A (изложено напрямую пользователем в чате)
- **PRD Phase**: N/A
- **Estimated Files**: 9 (2 новых backend, 2 новых frontend, 4 изменяемых, 1 удаляемый) + 3 файла документации

---

## UX Design

### Before
```
┌─────────────────────────────────────────┐
│  🖼️ OCR Разметка                         │
│  [Загрузите файл разметки (.txt)]        │  <- единственная точка входа
│                                           │
│  (после загрузки + working_dir)          │
│  ┌───────────┬─────────────────────────┐ │
│  │ Список    │ Редактор изображения    │ │
│  │ изображ.  │                         │ │
│  └───────────┴─────────────────────────┘ │
│  Сайдбар: Статистика │ Бэкапы │           │
│           🤖 Консенсус OCR (в самом низу) │  <- недостижимо без файла
└─────────────────────────────────────────┘
```

### After
```
┌─────────────────────────────────────────┐
│  🖼️ OCR Разметка                         │
│  Выберите режим:                         │
│  [ 🤖 Авторазметка ]  [ ✍️ Ручная разметка ]│
└─────────────────────────────────────────┘
        │                        │
        ▼                        ▼
┌───────────────────┐   ┌──────────────────────┐
│ 🤖 Авторазметка    │   │ ✍️ Ручная разметка    │
│ Модели:            │   │ (тот же флоу, что и  │
│  Paddle ✅          │   │  раньше — без изм.)  │
│  Surya  ⚪ [Скачать] │   └──────────────────────┘
│  Tesseract ❌       │             ▲
│ input/output/thresh │             │ "📥 Перейти к разметке
│ [▶ Запустить]        │───────────┘  результатов" (без upload)
│ [📥 Перейти к разметке] │
└───────────────────┘
```

### Interaction Changes
| Touchpoint | Before | After | Notes |
|---|---|---|---|
| Вход в приложение | Сразу file_uploader | Выбор режима (2 кнопки) | `st.session_state.app_mode` |
| Запуск OCR-моделей | Внизу сайдбара, только после загрузки файла | Отдельный полноэкранный режим, доступен сразу | `generation_view.py` |
| Статус моделей | Отсутствует | Панель со статусом Paddle/Surya/Tesseract + кнопка «Скачать» | Новый backend API |
| Переход к результатам | «📥 Импортировать» требовал существующий `manager` | «📥 Перейти к разметке результатов» создаёт `manager` сам и переключает режим | `st.session_state.manager` + `st.rerun()` |
| Смена режима | Нет | Кнопка «🔁 Сменить режим» | Сбрасывает только `app_mode`, не `manager` |

---

## Mandatory Reading

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | `frontend/app.py` | 1-119 | Текущая точка входа целиком — будет разбита на landing + 2 режима |
| P0 | `frontend/src/ui/consensus_view.py` | 1-89 | Логика запуска/статуса/импорта консенсуса — переносится в `generation_view.py` |
| P0 | `backend/jobs.py` | 1-71 | Паттерн in-memory состояния job'а — mirror для `models_status.py` |
| P0 | `backend/recognizers.py` | 1-30 | `_Engines.paddle()`/`_Engines.surya_recognition()` — ленивая загрузка, дергается из `prepare()` |
| P1 | `frontend/src/ui/sidebar.py` | 1-84 | Убрать вызов `render_consensus_section` (строка 83) и импорт (строка 6) |
| P1 | `frontend/src/annotations.py` | 1-61 | `AnnotationManager.__init__`/`load_from_file` — конструктор для handoff-функции |
| P1 | `backend/main.py` | 1-48 | Стиль эндпоинтов FastAPI (Pydantic `BaseModel` запросы, `HTTPException`) — mirror для новых роутов |
| P1 | `backend/pipeline.py` | 17-89 | Подтверждает: пути в `good.txt`/`needs_review.txt` относительны `output_dir`, файлы перезаписываются на каждый запуск |
| P2 | `backend/tests/test_consensus.py` | 1-65 | Стиль тестирования чистой логики без реальных ML-зависимостей — mirror для `test_models_status.py` |
| P2 | `docs/architecture.md` | 1-55 | Таблица модулей и известные хрупкие места — требует обновления |
| P2 | `backend/README.md` | 1-48 | Раздел `## API` — требует обновления |

## External Documentation
No external research needed — feature uses established internal patterns (FastAPI, in-memory state как в `backend/jobs.py`, Streamlit `st.session_state`/`st.rerun()`).

---

## Patterns to Mirror

### IN_MEMORY_STATE_PATTERN (backend)
// SOURCE: backend/jobs.py:18-25, 51-66
```python
@dataclass
class JobState:
    status: JobStatus
    result: Optional[dict] = None
    error: Optional[str] = None

_jobs: Dict[str, JobState] = {}

def start_job(...) -> str:
    job_id = str(uuid.uuid4())
    _jobs[job_id] = JobState(status="running")
    thread = threading.Thread(target=_run_job, args=(...), daemon=True)
    thread.start()
    return job_id
```
Использовать тот же приём (dataclass + module-level dict + daemon Thread) для
статуса моделей, но с фиксированными ключами `"paddle"`/`"surya"` вместо
генерируемых `job_id`.

### LAZY_ENGINE_LOADING (backend)
// SOURCE: backend/recognizers.py:4-29
```python
class _Engines:
    _paddle_ocr = None
    _foundation_predictor = None
    _recognition_predictor = None

    @classmethod
    def paddle(cls):
        if cls._paddle_ocr is None:
            from paddleocr import PaddleOCR
            cls._paddle_ocr = PaddleOCR(use_angle_cls=False, lang="ru", det=False)
        return cls._paddle_ocr

    @classmethod
    def surya_recognition(cls):
        if cls._recognition_predictor is None:
            from surya.foundation import FoundationPredictor
            from surya.recognition import RecognitionPredictor
            cls._foundation_predictor = FoundationPredictor()
            cls._recognition_predictor = RecognitionPredictor(cls._foundation_predictor)
        return cls._recognition_predictor
```
`prepare("paddle")`/`prepare("surya")` просто вызывают `_Engines.paddle()` /
`_Engines.surya_recognition()` в фоновом потоке — сам факт инстанцирования
триггерит скачивание и кэширование моделей (см. `backend/README.md:25-26`).

### FASTAPI_ENDPOINT_PATTERN (backend)
// SOURCE: backend/main.py:16-31
```python
class RunRequest(BaseModel):
    input_dir: str
    output_dir: str
    score_threshold: float = DEFAULT_SCORE_THRESHOLD
    preferred_model: Optional[str] = None

@app.post("/run")
def run(req: RunRequest):
    if not os.path.isdir(req.input_dir):
        raise HTTPException(400, f"input_dir не найдена: {req.input_dir}")
    job_id = start_job(...)
    return {"job_id": job_id}
```

### CONSENSUS_VIEW_UI_PATTERN (frontend, sidebar → полноэкранный вариант)
// SOURCE: frontend/src/ui/consensus_view.py:11-61
```python
def render_consensus_section(manager: AnnotationManager):
    st.sidebar.divider()
    st.sidebar.header("🤖 Консенсус OCR")
    input_dir = st.sidebar.text_input("Папка с документами", key="consensus_input")
    ...
    if st.sidebar.button("▶ Запустить", key="consensus_run"):
        try:
            resp = requests.post(f"{BACKEND_URL}/run", json={...}, timeout=5)
            resp.raise_for_status()
            st.session_state.consensus_job_id = resp.json()["job_id"]
            st.sidebar.success("Запущено")
        except Exception as e:
            st.sidebar.error(f"Ошибка запуска: {e}")
```
Тот же паттерн (виджеты + `requests` + `try/except Exception as e: st.error(...)`),
но через `st.` вместо `st.sidebar.` — авторазметка теперь полноэкранный режим,
а не часть сайдбара.

### IMPORT_RESULTS_PATTERN → ADAPT для handoff
// SOURCE: frontend/src/ui/consensus_view.py:64-88
```python
def _import_results(manager: AnnotationManager, output_dir: str):
    for fname, mark_as_done in (("good.txt", True), ("needs_review.txt", False)):
        path = os.path.join(output_dir, fname)
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            contents = f.read()
        imported_names = {
            os.path.basename(line.split("\t", 1)[0].strip())
            for line in contents.splitlines() if line.strip()
        }
        success, error = manager.load_from_file(contents)
        if mark_as_done:
            for name in imported_names & manager.records.keys():
                manager.records[name].is_marked = True
                manager.modified_records.add(name)
```
Новая функция `_build_manager_from_output(output_dir)` использует ту же логику
объединения `good.txt`(`is_marked=True`) + `needs_review.txt`(`is_marked=False`),
но **создаёт** `AnnotationManager(output_dir, os.path.join(output_dir, "review.txt"))`
с нуля вместо мутации переданного — т.к. в момент запуска авторазметки
`manager` в `st.session_state` ещё не существует.

### AnnotationManager constructor (frontend)
// SOURCE: frontend/src/annotations.py:15-21
```python
class AnnotationManager:
    def __init__(self, base_dir: str, annotation_file: str):
        self.base_dir = Path(base_dir)
        self.annotation_file = Path(annotation_file)
        self.records: Dict[str, ImageRecord] = {}
        self.modified_records: Set[str] = set()
        self.cache_path: Optional[Path] = None
        self.backup_manager = BackupManager(self.base_dir)
```
`base_dir` для нового `manager` — это `output_dir` (не `input_dir`!), потому
что `good.txt`/`needs_review.txt` содержат пути вида `crops/<uuid>.webp`
относительно `output_dir` (см. `backend/pipeline.py:69-75`).

### app.py ENTRY POINT STRUCTURE (frontend)
// SOURCE: frontend/app.py:37-118 (main(), целиком реструктурируется)
```python
def main():
    st.markdown("""<style>...</style>""", unsafe_allow_html=True)
    st.title("🖼️ OCR Разметка")
    init_session_state()
    uploaded_file = st.file_uploader(...)
    if uploaded_file:
        working_dir = st.text_input(...)
        ...
        if st.session_state.manager is None:
            ...
            st.session_state.manager = AnnotationManager(...)
        manager = st.session_state.manager
        ...
        col1, col2 = st.columns([1, 2])
        with col1: render_image_list(manager, filtered)
        with col2: render_image_editor(manager)
        render_sidebar(manager)
```
Разбивается на `render_mode_landing()`, `render_manual_mode()` (новый модуль),
`render_generation_mode()` (новый модуль), маршрутизируемые из тонкого `main()`.

### TEST_STRUCTURE (backend, чистая логика без реальных ML-зависимостей)
// SOURCE: backend/tests/test_consensus.py:1-23
```python
from backend.consensus import vote

def test_vote_returns_needs_review_for_empty_results():
    bucket, text, engine = vote({}, threshold=0.9)
    assert bucket == "needs_review"
    assert text == ""
    assert engine == ""
```
Прямой импорт функции + assert по возвращаемому tuple/значению, без фикстур и
моков там, где логика чистая. Для `models_status.py` — то же самое для
`check_tesseract`, плюс `monkeypatch` для `shutil.which`/`subprocess.run`/
`backend.recognizers._Engines.paddle`.

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `backend/models_status.py` | CREATE | Статус/подготовка моделей Paddle/Surya/Tesseract, in-memory state |
| `backend/main.py` | UPDATE | Добавить `GET /models/status`, `POST /models/prepare` |
| `backend/tests/test_models_status.py` | CREATE | Тесты чистой логики (без реальных Paddle/Surya/Tesseract) |
| `backend/README.md` | UPDATE | Задокументировать новые эндпоинты в `## API` |
| `frontend/app.py` | UPDATE | Тонкий роутер: landing / manual / generation |
| `frontend/src/ui/manual_mode.py` | CREATE | Перенесённое тело текущего `main()`, + поддержка предустановленного `manager` |
| `frontend/src/ui/generation_view.py` | CREATE | Замена `consensus_view.py`: статус моделей + запуск + handoff в manual |
| `frontend/src/ui/consensus_view.py` | DELETE | Логика полностью перенесена в `generation_view.py` |
| `frontend/src/ui/sidebar.py` | UPDATE | Убрать импорт/вызов `render_consensus_section` |
| `docs/architecture.md` | UPDATE | Обновить таблицу модулей под новую структуру |
| `CLAUDE.md` | UPDATE | Обновить список файлов `frontend/src/ui/` в Project Structure |

## NOT Building
- Автообновление статуса моделей (polling/websocket) — только кнопка «Обновить статус», как и у существующего job-статуса в старом `consensus_view.py`.
- Гейтинг кнопки «▶ Запустить» по готовности моделей — pipeline и так лениво скачивает модели при первом обращении; статус-панель чисто информационная.
- Автоустановка Tesseract — недоступно из pip (см. `backend/README.md:18-23`), только показ статуса с текстом ошибки.
- Персистентность статуса моделей между перезапусками backend'а — сохраняется паттерн `backend/jobs.py` (in-memory, спайк).
- Изменение формата `rec.txt`/`status_cache.txt`/`handwritten.txt` или логики `BackupManager` — не затрагиваются.

---

## Step-by-Step Tasks

(см. полный список из 10 задач в исходном плане — реализованы все)

---

## Acceptance Criteria
- [x] Все 10 задач выполнены.
- [x] Все validation commands проходят (см. отчёт implementation report).
- [x] Новые тесты (`test_models_status.py`) написаны и зелёные.
- [x] `ruff check .` без ошибок.
- [x] UX соответствует разделу «After».

## Completion Checklist
- [x] Код следует найденным паттернам (in-memory state, ленивый импорт ML-либ, `try/except Exception as e: st.error(...)`).
- [x] Обработка ошибок соответствует стилю кодовой базы.
- [x] Тесты следуют `TEST_STRUCTURE`.
- [x] Нет хардкода сверх уже существующего (`BACKEND_URL` остаётся как есть).
- [x] `docs/architecture.md` и `CLAUDE.md` обновлены.
- [x] Нет лишнего скоупа сверх раздела «NOT Building».
- [x] Самодостаточно — реализация не требует дополнительных вопросов.

## Notes
См. полный implementation report:
`.claude/PRPs/reports/generation-mode-ocr-markup-report.md`
