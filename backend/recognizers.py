from typing import Optional, Tuple


class _Engines:
    """Ленивый холдер тяжёлых моделей распознавания (Paddle, Surya)"""

    _paddle_ocr = None
    _foundation_predictor = None
    _recognition_predictor = None

    @classmethod
    def paddle(cls):
        if cls._paddle_ocr is None:
            from paddleocr import PaddleOCR

            cls._paddle_ocr = PaddleOCR(use_angle_cls=False, lang="ru", det=False)
        return cls._paddle_ocr

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
    """Распознавание текста через PaddleOCR (только распознавание, без детекции)"""
    try:
        import numpy as np

        predictions = _Engines.paddle()(np.array([crop]))
        text = predictions[0][0][0]
        score = predictions[0][0][1]
        return text, score
    except Exception as e:
        print(f"Ошибка PaddleOCR: {e}")
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


def recognize_tesseract(crop) -> Tuple[str, float]:
    """Распознавание текста через Tesseract"""
    try:
        import pytesseract
        from pytesseract import Output

        data = pytesseract.image_to_data(crop, lang="rus", output_type=Output.DICT)
        words = [
            (w, c) for w, c in zip(data["text"], data["conf"]) if int(c) != -1 and w.strip()
        ]
        if not words:
            return "", 0.0
        text = " ".join(w for w, _ in words)
        avg_conf = sum(int(c) for _, c in words) / len(words) / 100.0
        return text, avg_conf
    except Exception as e:
        print(f"Ошибка Tesseract: {e}")
        return "", 0.0
