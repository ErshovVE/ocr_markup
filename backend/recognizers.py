from typing import Tuple

LATIN_MODEL_SIZES = ("tiny", "small", "medium")
DEFAULT_LATIN_MODEL_SIZE = "small"


class _Engines:
    """Ленивый холдер тяжёлых моделей распознавания (Paddle, Surya)"""

    _paddle_cyrillic = None
    _paddle_latin = {}
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
    def surya_recognition(cls):
        if cls._recognition_predictor is None:
            from surya.foundation import FoundationPredictor
            from surya.recognition import RecognitionPredictor

            cls._foundation_predictor = FoundationPredictor()
            cls._recognition_predictor = RecognitionPredictor(
                cls._foundation_predictor
            )
        return cls._recognition_predictor


def recognize_paddle(crop) -> Tuple[str, float]:
    """Распознавание русского/кириллического текста через PaddleOCR (cyrillic_PP-OCRv5_mobile_rec)"""
    try:
        result = list(_Engines.paddle_cyrillic().predict(crop, batch_size=1))
        if not result:
            return "", 0.0
        return result[0]["rec_text"], result[0]["rec_score"]
    except Exception as e:
        print(f"Ошибка PaddleOCR: {e}")
        return "", 0.0


def recognize_paddle_latin(
    crop, model_size: str = DEFAULT_LATIN_MODEL_SIZE
) -> Tuple[str, float]:
    """Распознавание латиницы через PaddleOCR PP-OCRv6 (опциональный движок для не-русского текста)"""
    try:
        result = list(_Engines.paddle_latin(model_size).predict(crop, batch_size=1))
        if not result:
            return "", 0.0
        return result[0]["rec_text"], result[0]["rec_score"]
    except Exception as e:
        print(f"Ошибка PaddleOCR PP-OCRv6: {e}")
        return "", 0.0


def recognize_surya(image, box) -> Tuple[str, float]:
    """Распознавание текста через Surya по прямоугольнику box = [[x0,y0],...,[x2,y2]]"""
    try:
        predictions = _Engines.surya_recognition()(
            [image],
            None,
            bboxes=[[[box[0][0], box[0][1], box[2][0], box[2][1]]]],
        )
        text = predictions[0].text_lines[0].text
        score = predictions[0].text_lines[0].confidence
        return text, score
    except Exception as e:
        print(f"Ошибка Surya: {e}")
        return "", 0.0


def recognize_tesseract(crop, lang: str = "rus") -> Tuple[str, float]:
    """Распознавание текста через Tesseract

    crop — уже вырезанная одна строка текста (см. box в
    backend/pipeline.py::_process_boxes, боксы приходят от отдельного
    построчного детектора). Дефолтный PSM Тессеракта (3 — авто-разметка
    целой страницы) на таких маленьких однострочных кропах часто не находит
    вообще ничего (даже на чистом чётком тексте) — он заново пытается
    сегментировать кроп на блоки/строки, а сегментировать там уже нечего.
    "--psm 7" ("считать изображение одной строкой текста") пропускает эту
    повторную сегментацию и распознаёт напрямую — здесь она уместна именно
    потому, что кроп уже гарантированно одна строка.
    """
    try:
        import pytesseract
        from pytesseract import Output

        data = pytesseract.image_to_data(
            crop, lang=lang, config="--psm 7", output_type=Output.DICT
        )
        words = [
            (w, c)
            for w, c in zip(data["text"], data["conf"], strict=False)
            if int(c) != -1 and w.strip()
        ]
        if not words:
            return "", 0.0
        text = " ".join(w for w, _ in words)
        avg_conf = sum(int(c) for _, c in words) / len(words) / 100.0
        return text, avg_conf
    except Exception as e:
        print(f"Ошибка Tesseract: {e}")
        return "", 0.0
