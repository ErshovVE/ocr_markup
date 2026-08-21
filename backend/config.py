IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp")
PDF_EXTENSIONS = (".pdf",)
DEFAULT_SCORE_THRESHOLD = 0.95
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8756
# Верхняя граница ожидания одного вызова recognize_* (Surya может занимать
# до ~20с на строку, см. backend/README.md) — если движок завис (а не просто
# медленный), строка получает пустой результат вместо блокировки всего job'а.
ENGINE_CALL_TIMEOUT_SECONDS = 30
