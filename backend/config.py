# Сравниваются без учёта регистра (см. backend/pipeline.py::list_input_files) —
# камеры/сканеры часто пишут .JPG/.TIF.
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp")
PDF_EXTENSIONS = (".pdf",)
DEFAULT_SCORE_THRESHOLD = 0.95
# Движки распознавания, доступные для консенсуса (см. backend/recognizers.py) —
# по умолчанию используются 3 классических с требованием совпадения любых 2
# ("2 из 3"). custom — своя дообученная модель (экспорт PaddleOCR, нужен
# custom_model_dir), vlm_line — VLM читает одну строку-кроп (нужен line_vlm_engine).
RECOGNITION_ENGINES = ("paddle", "surya", "tesseract", "custom", "vlm_line")
DEFAULT_ENGINES = ("paddle", "surya", "tesseract")
DEFAULT_MIN_AGREE = 2
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8756
# Верхняя граница ожидания одного вызова recognize_* (Surya может занимать
# до ~20с на строку, см. backend/README.md) — если движок завис (а не просто
# медленный), строка получает пустой результат вместо блокировки всего job'а.
ENGINE_CALL_TIMEOUT_SECONDS = 30
# Верхняя граница одного вызова детектора строк на страницу (загрузка модели
# в неё не входит) — зависший detect() иначе вешал весь job.
DETECTOR_CALL_TIMEOUT_SECONDS = 120
# Сколько строк страницы уходит в движки распознавания одним батчем
# (backend/pipeline.py::_process_boxes). Больше — быстрее (меньше вызовов
# моделей), меньше — чаще прогресс/проверка отмены и короче бюджет таймаута
# батча (ENGINE_CALL_TIMEOUT_SECONDS × размер батча).
RECOGNITION_BATCH_SIZE = 16
# Схема именования кропов — как в предшественнике этого пайплайна
# (predict.py::save_image): по CROPS_PER_FOLDER файлов на подпапку
# (0/, 1/, 2/, ...), а не непрозрачный uuid4 на каждый кроп.
CROPS_PER_FOLDER = 10000
CROP_FILENAME_DIGITS = len(str(CROPS_PER_FOLDER))

# ── VLM-режим авторазметки (отдельный путь, см. backend/pipeline_vlm.py) ──
# Все модели обслуживает ОДИН llama.cpp llama-server в router-режиме
# (docker-compose.yml: llama-vlm / llama-vlm-gpu, пресеты — scripts/vlm/models.ini):
# один адрес, модель выбирается полем "model" в запросе и загружается по
# требованию. llama.cpp работает и на CPU, и на GPU на одних и тех же GGUF.
# Backend шлёт только OpenAI-совместимый HTTP (/v1/chat/completions с
# image_url), тяжёлых ML-зависимостей VLM не тянет.
VLM_ENDPOINT_ENV = "VLM_ENDPOINT"
VLM_DEFAULT_ENDPOINT = "http://localhost:8080"
VLM_ENGINES = ("paddleocr_vl", "glm_ocr", "hunyuan_ocr", "dots_ocr", "unlimited_ocr")

# Метаданные каждого движка:
#   served_model_name — имя пресета в scripts/vlm/models.ini (поле "model" запроса)
#   box_strategy      — откуда брать боксы строк:
#       "native" — модель сама отдаёт строки с боксами (PaddleOCR-VL 1.6
#                  "Spotting:", HunyuanOCR spotting)
#       "layout" — модель читает текст одной строки (GLM-OCR, dots.ocr,
#                  Unlimited-OCR): боксы строк даёт backend.detector.Detector
#                  (backend/vlm_layout.py), каждая строка — отдельный запрос
#   upscale_below     — (необязательно) картинку, у которой ОБЕ стороны меньше
#                       этого числа пикселей, перед запросом увеличить ×2 —
#                       официальная предобработка Spotting у PaddleOCR-VL
#                       (PaddleX paddleocr_vl/uilts.py::pre_process_for_spotting)
VLM_ENGINE_META = {
    "paddleocr_vl": {
        "served_model_name": "paddleocr-vl",
        "box_strategy": "native",
        "upscale_below": 1500,
    },
    "glm_ocr": {
        "served_model_name": "glm-ocr",
        "box_strategy": "layout",
    },
    "hunyuan_ocr": {
        "served_model_name": "hunyuan-ocr",
        "box_strategy": "native",
    },
    "dots_ocr": {
        "served_model_name": "dots-ocr",
        "box_strategy": "layout",
    },
    "unlimited_ocr": {
        "served_model_name": "unlimited-ocr",
        "box_strategy": "layout",
    },
}

# VLM на CPU отвечают минутами, не секундами (Folio-OCR: OCR_REQUEST_TIMEOUT_MS
# =300000) — отдельно от ENGINE_CALL_TIMEOUT_SECONDS=30 классического пути.
# Это read-таймаут (ожидание ответа модели). connect/write/pool держим
# короткими отдельно (VLM_CONNECT_TIMEOUT_SECONDS) — хост, завершивший
# TCP-handshake но молчащий, не должен держать поток job'а все 5 минут.
VLM_REQUEST_TIMEOUT_SECONDS = 300
VLM_CONNECT_TIMEOUT_SECONDS = 5
# Верхняя граница тела ответа VLM (стрим читается по кускам и обрывается на
# превышении) — недоверенный/сломанный endpoint не должен раздуть память
# многогигабайтным телом. max_tokens в запросе нормальный ответ и так
# ограничивает, это защита от неответственного сервера.
VLM_MAX_RESPONSE_BYTES = 32 * 1024 * 1024
# Запрос /v1/models для health-check (backend/models_status.py) — короткий:
# один на все VLM-движки, дергается на GET /models/status.
VLM_HEALTHCHECK_TIMEOUT_SECONDS = 3
# Кэш ответа /v1/models llama-server'а: GET /models/status дергается фронтендом
# по таймеру — внутри окна отдаём последний известный статус.
VLM_STATUS_CACHE_TTL_SECONDS = 8
# Потолок токенов ответа модели. Полностраничные native-стратегии (dots.ocr,
# HunyuanOCR) отдают всю страницу за один ответ — на плотной A4 4096 токенов
# обрезали бы нижние строки без всякого сигнала.
VLM_MAX_OUTPUT_TOKENS = 8192
# Согласование боксов между несколькими VLM: сколько движков должны отдать
# совпадающий по IoU бокс с одинаковым текстом (аналог min_agree, но по боксам,
# а не по score — VLM per-line confidence не дают).
DEFAULT_VLM_MIN_AGREE = 1
# Порог IoU, при котором боксы двух движков считаются одной строкой.
DEFAULT_IOU_THRESHOLD = 0.5
# VLM-движки, умеющие читать одну строку-кроп (движок "vlm_line" консенсуса,
# промпты — backend/vlm_adapters.py::LINE_PROMPTS). hunyuan_ocr — только spotting.
LINE_VLM_ENGINES = ("glm_ocr", "dots_ocr", "unlimited_ocr", "paddleocr_vl")
# Параллельных запросов vlm_line на батч строк — llama-server/vLLM батчат сами.
VLM_LINE_CONCURRENCY = 8
# Даунскейл самой длинной стороны страницы перед base64 — иначе плотная A4 в
# высоком DPI раздувает тело HTTP-запроса на десятки мегабайт.
VLM_MAX_IMAGE_SIDE = 2048
