# OCR Consensus Backend (спайк)

Отдельный FastAPI-сервис для 3-движкового консенсуса (PaddleOCR детектор +
PaddleOCR/SuryaOCR/TesseractOCR распознаватели). Не включён в
`frontend/requirements.txt` и не участвует в сборке `.exe` — тяжёлые ML-зависимости
изолированы намеренно.

Детектор строк использует PaddleOCR PP-OCRv6 (детекция не зависит от языка).
Распознавание по умолчанию (`lang="ru"`) использует кириллическую модель
`cyrillic_PP-OCRv5_mobile_rec` — PP-OCRv6 её не заменяет, так как её 50 языков
это китайский/японский/английский и 46 языков на латинице, кириллица не
поддерживается. Для документов на латинице можно передать `lang="latin"` в
`/run` — тогда вместо кириллической модели используется PaddleOCR PP-OCRv6
(`latin_model_size`: `tiny` | `small` (по умолчанию) | `medium`), а Tesseract
переключается на `lang="eng"`.

## Установка

Рекомендуется отдельное виртуальное окружение:

```bash
python -m venv .venv-backend
.venv-backend\Scripts\activate  # Windows
pip install -r backend/requirements.txt
```

Дополнительно требуется системный бинарник Tesseract с русским языковым
пакетом (не устанавливается через `pip install pytesseract` — это только
Python-обёртка):

- Установить `tesseract-ocr` для вашей ОС.
- Убедиться, что `tesseract --list-langs` включает `rus`.

Модели PaddleOCR и Surya скачиваются и кэшируются автоматически при первом
использовании — хардкодить локальные пути не нужно.

## Запуск

```bash
uvicorn backend.main:app --host 127.0.0.1 --port 8756
```

Сервис слушает только `127.0.0.1` — без аутентификации и без ограничения на
принимаемые `input_dir`/`output_dir` (любой путь, доступный процессу, будет
прочитан/перезаписан). Это осознанный компромисс для локального
однопользовательского спайка (см. PRD, раздел "Won't Building"); не
запускать на общей/многопользовательской машине как есть.

## API

- `POST /run` — `{"input_dir": str, "output_dir": str, "score_threshold": float, "preferred_model": str | null, "lang": "ru" | "latin", "latin_model_size": "tiny" | "small" | "medium"}` → `{"job_id": str}`
- `GET /status/{job_id}` → `{"status": "running" | "done" | "error", "error": str | null}`
- `GET /result/{job_id}` → `{"output_dir": str, "good_count": int, "needs_review_count": int}`

Состояние задач хранится в памяти процесса — перезапуск backend'а теряет
историю запущенных задач (см. `backend/jobs.py`).
