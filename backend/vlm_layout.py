"""Источник боксов строк для движков со стратегией box_strategy="layout".

GLM-OCR (и опционально PaddleOCR-VL без pipeline) отдаёт только markdown без
координат. Чтобы получить пиксельные боксы для crops/ и good.txt, режем
страницу на строки существующим построчным детектором
(backend.detector.Detector) — веса те же, что у классического пути, ничего
дополнительно скачивать не нужно.

Каждая строка детектора — отдельный регион (отдельный VLM-вызов). Соседние
строки раньше сливались в один регион ради меньшего числа вызовов, но тогда
кроп становился абзацем с текстом всех строк через пробел — это ломало
контракт good.txt «одна строка = один кроп» и не сопоставлялось по IoU с
построчными боксами других VLM.

Ленивый импорт тяжёлого (Detector тянет paddleocr), юнит-тестами не
покрывается — как backend/detector.py, см. docs/testing.md.
"""

import threading
from typing import List, Optional

from backend.vlm_geometry import Polygon

_detector = None
# Детектор — один общий PaddleOCR-предиктор, не thread-safe. Сейчас VLM-путь
# зовёт его последовательно (backend/pipeline_vlm.py), лок — страховка на случай
# конкурентных вызовов: сериализует и ленивую инициализацию, и сам detect().
_detector_lock = threading.Lock()


def region_boxes(numpy_image) -> List[Polygon]:
    """Полигоны строк текста страницы через backend.detector.Detector
    (engine="paddle"). Детектор создаётся один раз на процесс."""
    global _detector
    with _detector_lock:
        if _detector is None:
            from backend.detector import Detector

            _detector = Detector(engine="paddle")
        return list(_detector.detect(numpy_image))


def reset() -> None:
    """Сбрасывает кэш детектора (для тестов)."""
    global _detector
    _detector = None


def set_detector(detector: Optional[object]) -> None:
    """Подменяет детектор (для тестов/интеграции)."""
    global _detector
    _detector = detector
