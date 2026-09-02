IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp")
PDF_EXTENSIONS = (".pdf",)
DEFAULT_SCORE_THRESHOLD = 0.95
# Движки распознавания, доступные для консенсуса (см. backend/recognizers.py) —
# по умолчанию используются все 3 с требованием совпадения любых 2 ("2 из 3").
RECOGNITION_ENGINES = ("paddle", "surya", "tesseract")
DEFAULT_ENGINES = RECOGNITION_ENGINES
DEFAULT_MIN_AGREE = 2
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8756
# Верхняя граница ожидания одного вызова recognize_* (Surya может занимать
# до ~20с на строку, см. backend/README.md) — если движок завис (а не просто
# медленный), строка получает пустой результат вместо блокировки всего job'а.
ENGINE_CALL_TIMEOUT_SECONDS = 30
# Схема именования кропов — как в предшественнике этого пайплайна
# (predict.py::save_image): по CROPS_PER_FOLDER файлов на подпапку
# (0/, 1/, 2/, ...), а не непрозрачный uuid4 на каждый кроп.
CROPS_PER_FOLDER = 10000
CROP_FILENAME_DIGITS = len(str(CROPS_PER_FOLDER))

# ── VLM-режим авторазметки (отдельный путь, см. backend/pipeline_vlm.py) ──
# Полностраничный парсинг: VLM обрабатывает страницу/регион целиком за один
# forward и сам отдаёт (полигон строки, текст). Все модели подключаются через
# единый OpenAI-совместимый HTTP (/v1/chat/completions с image_url) — сам
# backend тяжёлых ML-зависимостей VLM не тянет, модели поднимает пользователь
# внешними сервисами (llama-server / Ollama / vLLM), см. scripts/vlm/.
VLM_ENGINES = ("paddleocr_vl", "glm_ocr", "hunyuan_ocr", "dots_ocr", "unlimited_ocr")

# Метаданные каждого движка:
#   endpoint_env      — имя переменной окружения с базовым URL сервиса
#   default_endpoint  — фолбэк, если переменная не задана
#   served_model_name — имя модели в теле запроса (model: ...)
#   box_strategy      — откуда брать боксы строк:
#       "native" — модель сама отдаёт боксы (dots.ocr JSON, HunyuanOCR
#                  spotting, PaddleOCR-VL pipeline, Unlimited-OCR <box>-токены)
#       "layout" — модель отдаёт только текст (markdown), боксы регионов
#                  берём от backend.detector.Detector (см. backend/vlm_layout.py)
#   gpu_only          — движок реально работает только на GPU (dots.ocr,
#                       Unlimited-OCR) — во фронтенде помечен, не required
VLM_ENGINE_META = {
    "paddleocr_vl": {
        "endpoint_env": "PADDLEOCR_VL_ENDPOINT",
        "default_endpoint": "http://localhost:11434",
        "served_model_name": "MedAIBase/PaddleOCR-VL:0.9b",
        "box_strategy": "native",
        "gpu_only": False,
    },
    "glm_ocr": {
        "endpoint_env": "GLM_OCR_ENDPOINT",
        "default_endpoint": "http://localhost:11434",
        "served_model_name": "glm-ocr",
        "box_strategy": "layout",
        "gpu_only": False,
    },
    "hunyuan_ocr": {
        "endpoint_env": "HUNYUAN_OCR_ENDPOINT",
        "default_endpoint": "http://localhost:8081",
        "served_model_name": "HunyuanOCR",
        "box_strategy": "native",
        "gpu_only": False,
    },
    "dots_ocr": {
        "endpoint_env": "DOTS_OCR_ENDPOINT",
        "default_endpoint": "http://localhost:8082",
        "served_model_name": "dots.ocr",
        "box_strategy": "native",
        "gpu_only": True,
    },
    "unlimited_ocr": {
        "endpoint_env": "UNLIMITED_OCR_ENDPOINT",
        "default_endpoint": "http://localhost:8083",
        "served_model_name": "baidu/Unlimited-OCR",
        "box_strategy": "native",
        "gpu_only": True,
    },
}

# VLM на CPU отвечают минутами, не секундами (Folio-OCR: OCR_REQUEST_TIMEOUT_MS
# =300000) — отдельно от ENGINE_CALL_TIMEOUT_SECONDS=30 классического пути.
VLM_REQUEST_TIMEOUT_SECONDS = 300
# Пинг /v1/models для health-check (backend/models_status.py) — короткий,
# т.к. дергается для всех VLM-движков на каждый GET /models/status.
VLM_HEALTHCHECK_TIMEOUT_SECONDS = 3
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
# Даунскейл самой длинной стороны страницы перед base64 — иначе плотная A4 в
# высоком DPI раздувает тело HTTP-запроса на десятки мегабайт.
VLM_MAX_IMAGE_SIDE = 2048
