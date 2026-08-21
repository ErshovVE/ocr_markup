IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp")
PDF_EXTENSIONS = (".pdf",)
DEFAULT_SCORE_THRESHOLD = 0.95
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
