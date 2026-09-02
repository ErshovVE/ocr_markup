# OCR Consensus Backend (спайк)

<p align="center">
  <strong>Language:</strong>
  <a href="../../backend/README.md">English</a> |
  <b>🇷🇺 Русский</b>
</p>

Отдельный FastAPI-сервис для 3-движкового консенсуса (PaddleOCR детектор +
PaddleOCR/SuryaOCR/TesseractOCR распознаватели). Не включён в
`frontend/requirements.txt` и не участвует в сборке `.exe` — тяжёлые ML-зависимости
изолированы намеренно.

Детектор строк использует PaddleOCR PP-OCRv6 (детекция не зависит от языка).

Детектор строк текста выбирается независимо от консенсуса распознавания —
`detector_engine` в `/run` принимает `paddle` (по умолчанию), `surya` или
`tesseract` и влияет только на то, какой движок находит боксы строк.

Какие движки распознавания прогонять на строку и сколько из них должны
сойтись в одном тексте, чтобы принять его без ручной проверки, задаётся
парой полей `engines`/`min_agree` в `/run` — схема "N из M" (см.
`frontend/src/ui/generation_view.py::CONSENSUS_SCHEME_KEYS` для готовых
пресетов: 1 из 1, 1 из 2, 2 из 2, 2 из 3). По умолчанию — все 3 движка,
совпадение любых 2 (`engines=["paddle","surya","tesseract"]`,
`min_agree=2`) — прежнее захардкоженное поведение. При `min_agree <= 1`
сверка большинства текстов пропускается: побеждает единственный уверенный
движок (или `preferred_model`/лучший по score, см. `backend/consensus.py::vote`).
`preferred_model` остаётся тай-брейком только для голосования распознавания
и должен входить в `engines`.

При `detector_engine="surya"` детектор строк иногда объединяет 2-3 строки
текста в один бокс вместо одной (причина не выяснена). Признак — перевод
строки (`\n`) в тексте, который вернул на этот бокс какой-либо из движков
распознавания. В этом случае строка не попадает ни в `good.txt`, ни в
`needs_review.txt`, кроп не сохраняется — она просто пропускается, а
сообщение об этом уходит в `error_count`/`errors` (`GET /status/{job_id}`,
см. ниже) и в консоль backend'а (см. `backend/pipeline.py::_process_boxes`).
При других `detector_engine` эта проверка не выполняется.

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

- `POST /run` — `{"input_dir": str, "output_dir": str, "score_threshold": float, "preferred_model": str | null, "lang": "ru" | "latin", "latin_model_size": "tiny" | "small" | "medium", "extract_pdf_text_layer": bool, "detector_engine": "paddle" | "surya" | "tesseract", "engines": ["paddle" | "surya" | "tesseract", ...], "min_agree": int}` → `{"job_id": str, "warnings": [str]}`; 400, если `engines` пуст/содержит неизвестный движок или `min_agree` вне `[1, len(engines)]`; 409, если уже выполняется другое задание (одновременно поддерживается только одно, см. backend/jobs.py). `warnings` — движки из `engines` (и детектор), чья модель ещё не готова (`not_checked`/`checking`/`error` в `/models/status`) — задание всё равно стартует, предупреждение просто объясняет, почему первые строки могут "зависнуть" на скачивании весов
- `GET /jobs/active` → `{"job_id": str | null}` — id текущего выполняющегося задания (или null); нужен фронтенду, чтобы восстановить трекер прогресса после перезагрузки страницы
- `GET /status/{job_id}` → `{"status": "running" | "done" | "error" | "cancelled", "error": str | null, "docs_found": int, "docs_processed": int, "good_count": int, "review_count": int, "diverged_count": int, "error_count": int, "errors": [str]}` — трекер прогресса обновляется построчно по ходу выполнения задания (см. backend/jobs.py), а не только по завершении файла целиком (распознавание одной строки Surya может занимать до ~20с); `diverged_count` — строки, где 2+ движка независимо уверены (score >= threshold), но разошлись в тексте (см. backend/consensus.py); `error_count`/`errors` — файлы/строки, упавшие с исключением или таймаутом движка (см. `ENGINE_CALL_TIMEOUT_SECONDS` ниже) — `error_count` растёт без ограничения, `errors` хранит только последние `MAX_STORED_ERRORS` (по умолчанию 50) сообщений
- `POST /jobs/{job_id}/cancel` → `{"status": "cancelling"}`; 404 — неизвестный `job_id`, 409 — задание уже не выполняется. Отмена кооперативная: поток нельзя убить напрямую, поэтому задание останавливается на ближайшей проверке между файлами/страницами/строками, не теряя уже записанное; после остановки `/status` покажет `"status": "cancelled"`
- `GET /jobs/status_snapshot?output_dir=...` → тот же формат, что и `/status/{job_id}`, но по `output_dir`, а не по `job_id` — читает `output_dir/_job_status.json` (пишется на каждый обработанный файл и по завершении, см. backend/jobs.py). Нужен, чтобы понять, чем закончилось задание, после перезапуска backend'а — `_jobs`/`job_id` в памяти к этому моменту уже потеряны, а сам снэпшот на диске переживает рестарт. 404, если снэпшота для этой `output_dir` ещё нет
- `GET /result/{job_id}` → `{"output_dir": str, "good_count": int, "needs_review_count": int}`
- `GET /models/status` → `{"paddle": {...}, "surya": {...}, "paddle_detector": {...}, "surya_detector": {...}, "tesseract": {...}}`, каждое значение — `{"status": "not_checked"|"checking"|"ready"|"error", "detail": str|null}`. `paddle`/`surya` — модели распознавания; `paddle_detector`/`surya_detector` — отдельные, независимо скачиваемые модели детекции строк для тех же движков; `tesseract` — общий (детекция и распознавание используют один и тот же системный бинарник)
- `POST /models/prepare` — `{"model": "paddle"|"surya"|"paddle_detector"|"surya_detector"}` → `{"status": "started"}` (асинхронно инстанцирует движок в фоновом потоке, что триггерит скачивание/кэширование моделей; Tesseract сюда не передаётся — ставится вручную, см. раздел «Установка»)

Состояние задач (счётчики/статус в памяти, `_jobs`/`job_id`) не переживает
перезапуск backend'а — см. `backend/jobs.py`. Сами результаты не теряются:
`good.txt`/`needs_review.txt`/`debug.jsonl` пишутся на диск построчно с
`flush()` по ходу выполнения, а не одним махом в конце, и статус
дополнительно дублируется в `output_dir/_job_status.json` на каждый
обработанный файл — см. `GET /jobs/status_snapshot` выше.

Один вызов recognize_* (paddle/surya/tesseract на одну строку) ограничен
`ENGINE_CALL_TIMEOUT_SECONDS` (по умолчанию 30с, `backend/config.py`) — если
движок завис (не просто медленный — recognize_* сами ловят исключения и
возвращают пустой результат, см. `backend/recognizers.py`), для этой строки
он считается пустым, а не блокирует весь job. Таймаут не убивает поток
движка — он просто перестаёт ждать; сам вызов может доработать в фоне.

## Именование кропов (`crops/`)

Кропы именуются по схеме предшественника этого пайплайна (`predict.py::save_image`),
а не непрозрачным `uuid4`: `crops/{N // CROPS_PER_FOLDER}/image_{N:05d}.webp`,
где `N` — сквозной номер кропа и `CROPS_PER_FOLDER = 10000` (`backend/config.py`) —
то есть не больше 10000 файлов на подпапку (`crops/0/`, `crops/1/`, ...).
Нумерация при повторном запуске на тот же `output_dir` продолжается с
максимума, уже найденного на диске (`backend/pipeline.py::_resume_img_count`),
а не начинается заново с 1 — иначе повторный запуск затёр бы уже
сохранённые/импортированные кропы прошлых запусков под теми же именами.

## Отладочные данные авторазметки (`debug.jsonl`)

Рядом с `good.txt`/`needs_review.txt` в `output_dir` пишется `debug.jsonl` —
по одной JSON-записи на строку:

```json
{"crop": "crops/0/image_00001.webp", "bucket": "good", "engine": "paddle", "diverged": false,
 "engines": {"paddle": {"text": "...", "score": 0.97}, "surya": {"text": "...", "score": 0.93}, "tesseract": {"text": "...", "score": 0.81}}}
```

`engines` в записи содержит только те движки, что реально были прогнаны на
эту строку (см. `engines`/`min_agree` в `/run` выше) — не всегда все 3. Без
этого файла победивший текст в `good.txt`/`needs_review.txt` — это всё, что
остаётся от голосования (`backend/consensus.py::vote`); ни имя победившего
движка, ни варианты проигравших нигде больше не сохраняются.
Фронтенд использует `debug.jsonl` для показа деталей разметчику (см.
`frontend/src/annotations.py::AnnotationManager._load_debug_file`) — если
файла нет (например, при чисто ручной разметке), это не ошибка, просто
детали показывать нечем. PDF-страницы с извлечённым текстовым слоем (без
OCR) в `debug.jsonl` не попадают — там `vote()` не вызывается.

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
  OCR-консенсус выбранных `engines`/`min_agree`.

**Известное ограничение**: "текстовый слой" не отличается от текста,
добавленного самим сканером (searchable PDF от сканирующего ПО) — такой слой
может быть неточным (собственный OCR сканера), но будет доверчиво помечен
как `good`. Для папок с такими сканами явно выключайте
`extract_pdf_text_layer`.

## VLM-режим (`mode="vlm"`)

Второй путь авторазметки (`backend/pipeline_vlm.py`). Вместо построчного
пайплайна (детектор → кроп строки → `recognize_*` → `vote`)
vision-language-модель обрабатывает **страницу целиком за один forward** и
сама отдаёт `(полигон строки, текст)`. Выход — те же
`good.txt` / `needs_review.txt` / `debug.jsonl` / `crops/`, поэтому handoff в
ручную разметку не меняется.

Все модели подключаются через единый **OpenAI-совместимый HTTP**
(`POST {endpoint}/v1/chat/completions` с `image_url`). Сами модели поднимаются
**внешними сервисами** (llama-server / Ollama / vLLM) — backend добавляет
единственную зависимость `httpx` и не тянет ML-веса VLM.

### Поля `/run`

`{"mode": "vlm", "input_dir": str, "output_dir": str, "vlm_engines": [str, ...], "vlm_min_agree": int, "iou_threshold": float}`
→ `{"job_id": str, "warnings": [str]}`.

- `vlm_engines` — непустое подмножество движков из таблицы ниже; иначе 400.
- `vlm_min_agree` — сколько движков должны отдать совпадающий по IoU бокс с
  одинаковым текстом, чтобы строка считалась `good` (аналог `min_agree`, но
  по боксам — VLM per-line confidence не дают). Должно быть
  `1..len(vlm_engines)`.
- `iou_threshold` — порог совпадения боксов при сведении нескольких движков.
  Должно быть в `(0, 1]`.
- Классические поля (`engines` / `min_agree` / `detector_engine` / `lang`)
  при `mode="vlm"` игнорируются. `mode` по умолчанию `"consensus"` — старые
  клиенты работают без изменений.

Трекер прогресса (`GET /status/{job_id}`) и `JobState` — общие с классическим
путём (те же счётчики `good_count` / `review_count` / `diverged_count`).

### Движки

| id | env endpoint'а | дефолт | `gpu_only` | стратегия боксов | как поднять |
|---|---|---|---|---|---|
| `paddleocr_vl` | `PADDLEOCR_VL_ENDPOINT` | `http://localhost:11434` | нет | native | `ollama pull MedAIBase/PaddleOCR-VL:0.9b` (community-тег) |
| `glm_ocr` | `GLM_OCR_ENDPOINT` | `http://localhost:11434` | нет | layout | `ollama pull glm-ocr` |
| `hunyuan_ocr` | `HUNYUAN_OCR_ENDPOINT` | `http://localhost:8081` | нет | native | `llama-server -hf ggml-org/HunyuanOCR-GGUF --port 8081` |
| `dots_ocr` | `DOTS_OCR_ENDPOINT` | `http://localhost:8082` | да | native | vLLM ≥ 0.11.0 (`rednote-hilab/dots.ocr`) |
| `unlimited_ocr` | `UNLIMITED_OCR_ENDPOINT` | `http://localhost:8083` | да | native | vLLM / SGLang (`baidu/Unlimited-OCR`) |

- **native** — модель сама отдаёт боксы (dots.ocr JSON, HunyuanOCR spotting
  `text(x1,y1),(x2,y2)`, PaddleOCR-VL pipeline JSON, Unlimited-OCR
  `<box>`-токены).
- **layout** — модель отдаёт только markdown (`glm_ocr`); боксы строк даёт
  `backend/vlm_layout.py`, переиспользуя тот же `paddle`-детектор строк, что и
  классический путь, со слиянием соседних регионов (меньше HTTP-вызовов).
- Если движок ничего не отдал (ошибка клиента/парсера) — его строки
  пропускаются, сообщение уходит в `error_count`/`errors`, движок в
  группировке этой страницы не участвует.

Поднять сервисы: `scripts/vlm/setup.sh --cpu` (или
`scripts\vlm\setup.ps1 -Cpu` на Windows), либо compose-профили
`--profile vlm-cpu` / `--profile vlm-gpu` (см. `docs/docker.md`). Каждый
движок виден в `GET /models/status` как `vlm_<id>` (живой пинг `/v1/models`,
проверяется каждый запрос — не кэшируется, в отличие от Paddle/Surya).
`/models/prepare` для VLM-движков **не поддерживается**.

### `debug.jsonl` для VLM

Форма та же, что у классического пути, но `score` всегда `1.0` (VLM per-line
confidence не дают). `diverged` проставляется, когда ≥2 движка вернули
непустой, но разный текст для одного бокса.

### Ограничения

- Страницы PDF всегда рендерятся в растр — текстовый слой в VLM-режиме не
  используется (для PDF с текстовым слоем берите `mode="consensus"`).
- Стратегия `layout` (GLM-OCR) даёт одну строку на найденный регион, не
  обязательно одну визуальную строку текста.
- Таблицы/формулы кладутся как обычные строки текста (датасет построчный).
