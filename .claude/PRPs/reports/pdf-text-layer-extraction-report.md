# Implementation Report: Прямое извлечение текстового слоя PDF (без OCR)

## Summary
Добавлена поддержка `.pdf`-файлов во входной папке `backend/pipeline.run()`.
Новый модуль `backend/pdf_extract.py` (на `pypdfium2`) проверяет первые 2
страницы документа на наличие извлекаемого текстового слоя. Если он есть —
весь документ обрабатывается прямым извлечением текста+координат (без OCR),
строки сразу попадают в `good.txt`. Если нет — документ растеризуется
постранично и идёт в обычный 3-движковый OCR-консенсус, как раньше. Поведение
управляется новым флагом `extract_pdf_text_layer` (по умолчанию `true`) в
`POST /run` и одноимённым чекбоксом в UI.

## Assessment vs Reality

| Metric | Predicted (Plan) | Actual |
|---|---|---|
| Complexity | Large | Large — совпало, все 10 задач реализованы без отклонений |
| Confidence | Высокая (API проверен вживую при подготовке плана) | Подтверждена — реализация 1:1 совпала с кодом в плане |
| Files Changed | 10 | 10 (2 CREATE, 8 UPDATE) — план не учитывал сам файл плана |

## Tasks Completed

| # | Task | Status | Notes |
|---|---|---|---|
| 1 | Зависимости (`backend/requirements.txt`, `requirements-dev.txt`) | Complete | `pypdfium2==4.30.1`, `numpy==1.26.4` |
| 2 | `PDF_EXTENSIONS` в `backend/config.py` | Complete | |
| 3 | Создать `backend/pdf_extract.py` | Complete | Код скопирован из плана без изменений |
| 4 | Рефакторинг `backend/pipeline.py` | Complete | `_save_crop`/`_process_boxes`/`_process_pdf` + ленивый `Detector()` |
| 5 | `backend/jobs.py` — прокинуть флаг | Complete | |
| 6 | `backend/main.py` — поле в `RunRequest` | Complete | |
| 7 | Чекбокс в `frontend/src/ui/generation_view.py` | Complete | |
| 8 | Тесты `backend/tests/test_pdf_extract.py` | Complete | 8/8 зелёных |
| 9 | `backend/README.md` — раздел "PDF" | Complete | |
| 10 | `docs/testing.md` — уточнение покрытия | Complete | |

## Validation Results

| Level | Status | Notes |
|---|---|---|
| Static Analysis | Pass | `ruff check` — 0 замечаний; `ruff format --check` изначально нашёл 1 расхождение в `pdf_extract.py` (перенос длинного условия в списковом включении), исправлено `ruff format` |
| Unit Tests | Pass | `pytest backend/tests/test_pdf_extract.py -v` — 8/8 |
| Full Suite | Pass | `pytest` — 37/37 (frontend/tests + backend/tests), регрессий нет |
| Build | N/A | Python-проект без отдельного build-шага (PyInstaller `.exe` не входит в скоуп этой фичи) |
| Integration | Pass | Реальный запуск `uvicorn backend.main:app` + `POST /run` на синтетическом text-layer PDF: `good_count=1`, `needs_review_count=0`, `good.txt` содержит `crops/<uuid>.webp\tHello World`, файл кропа создан и не пуст. `extract_pdf_text_layer=false` корректно уходит в OCR-fallback ветку (в этом dev-окружении без `backend/requirements.txt` падает с ожидаемым перехваченным `ModuleNotFoundError: paddleocr`, залогированным и не прерывающим обработку остальных файлов — подтверждает ERROR_HANDLING) |
| Edge Cases | Pass | См. Testing Strategy плана — 5/6 чеклиста покрыты юнит-тестами, оставшиеся 3 (битый PDF, PDF с паролем, повёрнутая страница) сознательно не покрываются юнит-тестами по плану (broad try/except в pipeline.run, либо явный "не поддерживается" в NOT Building) |

## Files Changed

| File | Action | Lines |
|---|---|---|
| `backend/pdf_extract.py` | CREATED | +105 |
| `backend/tests/test_pdf_extract.py` | CREATED | +142 |
| `backend/pipeline.py` | UPDATED | полностью переписан (было 103 строки, стало ~260) |
| `backend/config.py` | UPDATED | +1 |
| `backend/jobs.py` | UPDATED | +6/-2 |
| `backend/main.py` | UPDATED | +6/-1 |
| `backend/requirements.txt` | UPDATED | +1 |
| `requirements-dev.txt` | UPDATED | +2 |
| `frontend/src/ui/generation_view.py` | UPDATED | +6 |
| `backend/README.md` | UPDATED | +1 (API) / +18 (новый раздел "PDF") |
| `docs/testing.md` | UPDATED | +5/-1 |

## Deviations from Plan
Нет — реализация точно следует коду, приведённому в плане (все задачи 1-10).
Единственная правка сверх плана: `ruff format` перенёс одно длинное
условие фильтрации в `extract_page_text_boxes` в одну строку (расхождение
между версией ruff, использованной при подготовке плана, и текущей — план
предвидел такую возможность в VALIDATE Task 4, но описал обратный перенос;
на практике формат сошёлся к другому виду). Применено автоматически, без
изменения логики.

## Issues Encountered
Установка `requirements-dev.txt` выдала предупреждения pip о конфликтах
версий с несвязанными пакетами (`langchain-community`, `langchain-huggingface`,
`tb-nightly` и т.п.), уже присутствующими в этом (не изолированном venv)
окружении — не относится к этой фиче, установка целевых пакетов
(`pypdfium2==4.30.1`, `numpy==1.26.4`, `Pillow==10.4.0`) прошла успешно.
`backend/requirements.txt` (тяжёлые ML-зависимости: paddleocr, surya-ocr,
pytesseract) не устанавливался — вне скоупа этой фичи и не требуется для
пути "текстовый слой PDF" (что и было целью лениво создаваемого `Detector()`);
это ограничило ручную проверку OCR-fallback-ветки до проверки корректности
graceful error handling, а не самого распознавания.

## Tests Written

| Test File | Tests | Coverage |
|---|---|---|
| `backend/tests/test_pdf_extract.py` | 8 tests | `page_has_text_layer`, `document_has_text_layer` (включая границу пробинга 2 страниц), `render_page` (масштаб DPI), `extract_page_text_boxes` (текст+бокс и пустая страница) |

## Next Steps
- [ ] Code review via `/code-review`
- [ ] Create PR via `/prp-pr`
