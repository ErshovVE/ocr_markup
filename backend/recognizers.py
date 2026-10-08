import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, List, Optional, Tuple

from backend import vlm_client
from backend.config import VLM_LINE_CONCURRENCY
from backend.vlm_adapters import LINE_PROMPTS, parse_line_text

LATIN_MODEL_SIZES = ("tiny", "small", "medium")
DEFAULT_LATIN_MODEL_SIZE = "small"
EMPTY_RESULT: Tuple[str, float] = ("", 0.0)

logger = logging.getLogger(__name__)


class _Engines:
    """Ленивый холдер тяжёлых моделей распознавания (Paddle, Surya, своя модель)"""

    _paddle_cyrillic = None
    _paddle_latin = {}
    # Своя модель — только последняя запрошенная: (model_dir, предиктор). Новый
    # custom_model_dir вытесняет прежний, а не копит модели в памяти процесса.
    _custom: Optional[Tuple[str, object]] = None
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

    @classmethod
    def paddle_latin(cls, model_size: str = DEFAULT_LATIN_MODEL_SIZE):
        if model_size not in LATIN_MODEL_SIZES:
            raise ValueError(f"Неизвестный размер модели PP-OCRv6: {model_size}")
        if model_size not in cls._paddle_latin:
            from paddleocr import TextRecognition

            cls._paddle_latin[model_size] = TextRecognition(
                model_name=f"PP-OCRv6_{model_size}_rec", enable_mkldnn=False
            )
        return cls._paddle_latin[model_size]

    @classmethod
    def custom(cls, model_dir: str):
        """Своя дообученная модель — экспорт PaddleOCR (tools/export_model.py:
        inference.json/.pdiparams/.yml). Имя архитектуры и словарь PaddleX
        берёт из inference.yml в model_dir. В кэше — одна модель (см. _custom)."""
        if cls._custom is None or cls._custom[0] != model_dir:
            from paddleocr import TextRecognition

            cls._custom = None  # отпустить прежнюю модель до загрузки новой
            cls._custom = (model_dir, TextRecognition(model_dir=model_dir, enable_mkldnn=False))
        return cls._custom[1]

    @classmethod
    def surya_recognition(cls):
        if cls._recognition_predictor is None:
            from surya.foundation import FoundationPredictor
            from surya.recognition import RecognitionPredictor

            cls._foundation_predictor = FoundationPredictor()
            cls._recognition_predictor = RecognitionPredictor(cls._foundation_predictor)
        return cls._recognition_predictor


def _paddle_batch(predictor, crops: List, label: str) -> List[Tuple[str, float]]:
    """Один predict() на все кропы страницы — порядок результатов = порядок
    кропов. Ошибка модели → пустой результат для всех строк батча."""
    try:
        results = list(predictor.predict(crops, batch_size=len(crops)))
        if len(results) != len(crops):
            raise RuntimeError(f"ожидалось {len(crops)} результатов, получено {len(results)}")
        return [(r["rec_text"], float(r["rec_score"])) for r in results]
    except Exception as e:
        logger.warning(f"Ошибка {label}: {e}")
        return [EMPTY_RESULT] * len(crops)


def recognize_paddle_batch(crops: List) -> List[Tuple[str, float]]:
    """Распознавание русского/кириллического текста через PaddleOCR
    (cyrillic_PP-OCRv5_mobile_rec) — батчем по кропам строк."""
    try:
        predictor = _Engines.paddle_cyrillic()
    except Exception as e:
        logger.warning(f"Ошибка PaddleOCR: {e}")
        return [EMPTY_RESULT] * len(crops)
    return _paddle_batch(predictor, crops, "PaddleOCR")


def recognize_paddle_latin_batch(
    crops: List, model_size: str = DEFAULT_LATIN_MODEL_SIZE
) -> List[Tuple[str, float]]:
    """Распознавание латиницы через PaddleOCR PP-OCRv6 — батчем.

    Опциональный движок для не-русского текста."""
    try:
        predictor = _Engines.paddle_latin(model_size)
    except Exception as e:
        logger.warning(f"Ошибка PaddleOCR PP-OCRv6: {e}")
        return [EMPTY_RESULT] * len(crops)
    return _paddle_batch(predictor, crops, "PaddleOCR PP-OCRv6")


def recognize_custom_batch(crops: List, model_dir: str) -> List[Tuple[str, float]]:
    """Распознавание своей дообученной моделью (экспорт PaddleOCR из model_dir) —
    батчем, тем же путём, что у стандартных моделей PaddleOCR."""
    try:
        predictor = _Engines.custom(model_dir)
    except Exception as e:
        logger.warning(f"Ошибка своей модели ({model_dir}): {e}")
        return [EMPTY_RESULT] * len(crops)
    return _paddle_batch(predictor, crops, "Своя модель")


def recognize_vlm_line_batch(
    crops: List, engine_id: str, on_error: Optional[Callable[[str], None]] = None
) -> List[Tuple[str, float]]:
    """VLM читает каждую строку-кроп отдельным запросом (до VLM_LINE_CONCURRENCY
    параллельно — llama-server/vLLM батчат их у себя). Порядок результатов =
    порядок кропов.

    Уверенности VLM не дают: score 1.0 при непустом тексте, иначе 0.0 — при
    min_agree >= 2 vote() решает по совпадению текстов, score влияет только на
    diverged и подсказку. Кроп не даунскейлится (downscale=False): это одна
    строка, а не страница. Строки без ответа — одно сводное сообщение в
    on_error на батч (недоступный endpoint иначе был бы виден только в логе)."""
    try:
        prompt = LINE_PROMPTS[engine_id]
    except KeyError:
        logger.warning(f"Неизвестный построчный VLM-движок: {engine_id}")
        return [EMPTY_RESULT] * len(crops)

    def read_line(crop) -> Tuple[str, Optional[str]]:
        raw, reason = vlm_client.chat_with_reason(engine_id, prompt, crop, downscale=False)
        return parse_line_text(raw), reason

    with ThreadPoolExecutor(max_workers=max(1, min(VLM_LINE_CONCURRENCY, len(crops)))) as pool:
        answers = list(pool.map(read_line, crops))

    reasons = [reason for _, reason in answers if reason]
    if reasons and on_error:
        on_error(f"VLM {engine_id}: {len(reasons)} из {len(crops)} строк без ответа: {reasons[0]}")
    return [(text, 1.0) if text else EMPTY_RESULT for text, _ in answers]


def recognize_surya_batch(crops: List) -> List[Tuple[str, float]]:
    """Распознавание через Surya — только распознавание (детекцию Surya здесь
    не запускает), одним вызовом на все кропы страницы.

    Раньше на каждую строку в Surya уходила вся страница + один бокс, и она
    заново готовила страницу ради одной строки. Теперь — те же кропы, что у
    Paddle/Tesseract: каждый кроп — отдельная картинка с одним боксом во весь
    кроп."""
    try:
        from PIL import Image

        images = [Image.fromarray(crop) for crop in crops]
        bboxes = [[[0, 0, image.width, image.height]] for image in images]
        predictions = _Engines.surya_recognition()(images, bboxes=bboxes)
        results = []
        for prediction in predictions:
            lines = prediction.text_lines
            results.append((lines[0].text, float(lines[0].confidence)) if lines else EMPTY_RESULT)
        if len(results) != len(crops):
            raise RuntimeError(f"ожидалось {len(crops)} результатов, получено {len(results)}")
        return results
    except Exception as e:
        logger.warning(f"Ошибка Surya: {e}")
        return [EMPTY_RESULT] * len(crops)


def recognize_tesseract_batch(crops: List, lang: str = "rus") -> List[Tuple[str, float]]:
    """Tesseract батчинга не умеет (один вызов бинарника на картинку) — по
    кропу подряд, но в одном потоке движка, параллельно Paddle/Surya."""
    return [recognize_tesseract(crop, lang) for crop in crops]


def recognize_tesseract(crop, lang: str = "rus") -> Tuple[str, float]:
    """Распознавание текста через Tesseract

    crop — уже вырезанная одна строка текста (см. backend/pipeline.py::
    _process_boxes, боксы приходят от отдельного построчного детектора).
    Дефолтный PSM Тессеракта (3 — авто-разметка целой страницы) на таких
    маленьких однострочных кропах часто не находит вообще ничего (даже на
    чистом чётком тексте) — он заново пытается сегментировать кроп на
    блоки/строки, а сегментировать там уже нечего.
    "--psm 7" ("считать изображение одной строкой текста") пропускает эту
    повторную сегментацию и распознаёт напрямую — здесь она уместна именно
    потому, что кроп уже гарантированно одна строка.
    """
    try:
        import pytesseract
        from pytesseract import Output

        data = pytesseract.image_to_data(crop, lang=lang, config="--psm 7", output_type=Output.DICT)
        # int(float(c)): часть сборок Tesseract отдаёт conf строкой вида
        # "95.23", и голый int() на ней кидает ValueError (движок молча даёт
        # пусто из-за внешнего try/except).
        words = [
            (w, float(c))
            for w, c in zip(data["text"], data["conf"], strict=False)
            if float(c) != -1 and w.strip()
        ]
        if not words:
            return "", 0.0
        text = " ".join(w for w, _ in words)
        avg_conf = sum(c for _, c in words) / len(words) / 100.0
        return text, avg_conf
    except Exception as e:
        logger.warning(f"Ошибка Tesseract: {e}")
        return "", 0.0
