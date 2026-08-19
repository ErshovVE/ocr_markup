from typing import List, Tuple


class Detector:
    """Детектор строк текста на основе PaddleOCR"""

    def __init__(self):
        from paddleocr import PaddleOCR

        self._ocr = PaddleOCR(use_angle_cls=False, lang="ru", rec=False)

    def detect(self, image) -> List[List[Tuple[int, int]]]:
        """Возвращает список полигонов (боксов) строк текста"""
        try:
            result = self._ocr.ocr(image, rec=False)
            return result[0] if result and result[0] else []
        except Exception as e:
            print(f"Ошибка детекции: {e}")
            return []
