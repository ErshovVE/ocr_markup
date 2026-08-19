from typing import List, Tuple


class Detector:
    """Детектор строк текста на основе PaddleOCR (PP-OCRv6, детекция не зависит от языка)"""

    def __init__(self):
        from paddleocr import TextDetection

        # enable_mkldnn=False: с oneDNN включённым PP-OCRv6_medium_det падает с
        # "ConvertPirAttribute2RuntimeAttribute not support" на этой сборке paddlepaddle
        self._detector = TextDetection(enable_mkldnn=False)

    def detect(self, image) -> List[List[Tuple[int, int]]]:
        """Возвращает список полигонов (боксов) строк текста"""
        try:
            result = list(self._detector.predict(image, batch_size=1))
            return list(result[0]["dt_polys"]) if result else []
        except Exception as e:
            print(f"Ошибка детекции: {e}")
            return []
