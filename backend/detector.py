from typing import List, Tuple

DETECTOR_ENGINES = ("paddle", "surya", "tesseract")
DEFAULT_DETECTOR_ENGINE = "paddle"


class _Engines:
    """Ленивый холдер тяжёлых моделей детекции (Paddle, Surya)"""

    _paddle = None
    _surya = None

    @classmethod
    def paddle(cls):
        if cls._paddle is None:
            from paddleocr import TextDetection

            # enable_mkldnn=False: с oneDNN включённым PP-OCRv6_medium_det
            # падает с "ConvertPirAttribute2RuntimeAttribute not support"
            # на этой сборке paddlepaddle
            cls._paddle = TextDetection(enable_mkldnn=False)
        return cls._paddle

    @classmethod
    def surya(cls):
        if cls._surya is None:
            from surya.detection import DetectionPredictor

            cls._surya = DetectionPredictor()
        return cls._surya


def _extract_polygon(box):
    """Surya box может быть объектом (box.polygon) либо dict-like (box["polygon"])"""
    if isinstance(box, dict):
        return box["polygon"]
    return box.polygon


def _detect_paddle(numpy_image) -> List[List[Tuple[int, int]]]:
    try:
        result = list(_Engines.paddle().predict(numpy_image, batch_size=1))
        return list(result[0]["dt_polys"]) if result else []
    except Exception as e:
        print(f"Ошибка детекции PaddleOCR: {e}")
        return []


def _detect_surya(pil_image) -> List[List[Tuple[int, int]]]:
    try:
        predictions = _Engines.surya()([pil_image])
        boxes = (
            predictions[0].bboxes
            if not isinstance(predictions[0], dict)
            else predictions[0]["bboxes"]
        )
        return [_extract_polygon(box) for box in boxes]
    except Exception as e:
        print(f"Ошибка детекции Surya: {e}")
        return []


def _detect_tesseract(numpy_image, lang: str) -> List[List[Tuple[int, int]]]:
    try:
        import pytesseract
        from pytesseract import Output

        data = pytesseract.image_to_data(numpy_image, lang=lang, output_type=Output.DICT)
        lines = {}
        for i, word in enumerate(data["text"]):
            if int(data["conf"][i]) == -1 or not word.strip():
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            left, top = data["left"][i], data["top"][i]
            right, bottom = left + data["width"][i], top + data["height"][i]
            if key not in lines:
                lines[key] = [left, top, right, bottom]
            else:
                box = lines[key]
                box[0] = min(box[0], left)
                box[1] = min(box[1], top)
                box[2] = max(box[2], right)
                box[3] = max(box[3], bottom)
        return [[(x0, y0), (x1, y0), (x1, y1), (x0, y1)] for x0, y0, x1, y1 in lines.values()]
    except Exception as e:
        print(f"Ошибка детекции Tesseract: {e}")
        return []


class Detector:
    """Детектор строк текста — выбираемый движок (PaddleOCR PP-OCRv6 / SuryaOCR / Tesseract)"""

    def __init__(self, engine: str = DEFAULT_DETECTOR_ENGINE, tesseract_lang: str = "rus"):
        if engine not in DETECTOR_ENGINES:
            raise ValueError(f"Неизвестный движок детекции: {engine}")
        self._engine = engine
        self._tesseract_lang = tesseract_lang
        if engine == "paddle":
            _Engines.paddle()
        elif engine == "surya":
            _Engines.surya()

    def detect(self, image) -> List[List[Tuple[int, int]]]:
        """Возвращает список полигонов (боксов) строк текста.

        image — numpy-массив (RGB); для surya оборачивается в PIL.Image.
        """
        if self._engine == "paddle":
            return _detect_paddle(image)
        elif self._engine == "surya":
            from PIL import Image

            return _detect_surya(Image.fromarray(image))
        else:
            return _detect_tesseract(image, self._tesseract_lang)
