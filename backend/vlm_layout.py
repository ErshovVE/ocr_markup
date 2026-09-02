"""Источник боксов регионов для движков со стратегией box_strategy="layout".

GLM-OCR (и опционально PaddleOCR-VL без pipeline) отдаёт только markdown без
координат. Чтобы получить пиксельные боксы для crops/ и good.txt, режем
страницу на регионы существующим построчным детектором
(backend.detector.Detector) — веса те же, что у классического пути, ничего
дополнительно скачивать не нужно.

Ленивый импорт тяжёлого (Detector тянет paddleocr), юнит-тестами не
покрывается — как backend/detector.py, см. docs/testing.md. Тестируемая
геометрия слияния регионов — в backend/vlm_geometry.py::merge_adjacent.
"""

from typing import List, Optional

from backend.vlm_geometry import Polygon, merge_adjacent

_detector = None


def region_boxes(numpy_image) -> List[Polygon]:
    """Полигоны текстовых регионов страницы через backend.detector.Detector
    (engine="paddle"). Детектор создаётся один раз на процесс."""
    global _detector
    if _detector is None:
        from backend.detector import Detector

        _detector = Detector(engine="paddle")
    return list(_detector.detect(numpy_image))


def merged_region_boxes(
    numpy_image, y_gap_ratio: float = 0.5, x_overlap_ratio: float = 0.3
) -> List[Polygon]:
    """region_boxes + слияние вертикально-соседних (меньше HTTP-вызовов к VLM)."""
    return merge_adjacent(region_boxes(numpy_image), y_gap_ratio, x_overlap_ratio)


def reset() -> None:
    """Сбрасывает кэш детектора (для тестов)."""
    global _detector
    _detector = None


def set_detector(detector: Optional[object]) -> None:
    """Подменяет детектор (для тестов/интеграции)."""
    global _detector
    _detector = detector
