"""Чистая геометрия боксов для VLM-режима (backend/pipeline_vlm.py).

Вынесено отдельным модулем без тяжёлых зависимостей, поэтому полностью
юнит-тестируется (в отличие от backend/vlm_layout.py, который дергает
backend.detector.Detector — см. docs/testing.md).

Полигон везде — прямоугольник в том же формате, что у backend/detector.py:
[[x0, y0], [x1, y0], [x1, y1], [x0, y1]] (box[0] — левый верх, box[2] —
правый низ, как ожидает backend/pipeline.py::_process_boxes).
"""

from typing import List, Tuple

Polygon = List[List[int]]


def rect_polygon(x0: float, y0: float, x1: float, y1: float) -> Polygon:
    """Прямоугольный полигон из двух углов (координаты приводятся к int)."""
    x0, x1 = sorted((int(round(x0)), int(round(x1))))
    y0, y1 = sorted((int(round(y0)), int(round(y1))))
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def polygon_bbox(poly) -> Tuple[int, int, int, int]:
    """Осезависимый bbox (min_x, min_y, max_x, max_y) по вершинам полигона."""
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def iou(poly_a, poly_b) -> float:
    """IoU двух полигонов по их осезависимым bbox (0.0 при непересечении)."""
    ax0, ay0, ax1, ay1 = polygon_bbox(poly_a)
    bx0, by0, bx1, by1 = polygon_bbox(poly_b)
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    area_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    area_b = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    union = area_a + area_b - inter
    if union <= 0:
        return 0.0
    return inter / union


def merge_adjacent(boxes, y_gap_ratio: float = 0.5, x_overlap_ratio: float = 0.3) -> List[Polygon]:
    """Сливает вертикально-соседние боксы с горизонтальным перекрытием в один.

    Приём из Folio-OCR ("region merging") — для layout-стратегии (GLM-OCR)
    каждый регион уходит в VLM отдельным HTTP-вызовом, поэтому чем меньше
    регионов, тем меньше вызовов. Итеративно, пока есть что сливать: два бокса
    объединяются, если вертикальный зазор между ними не больше y_gap_ratio от
    меньшей высоты И горизонтальное перекрытие не меньше x_overlap_ratio от
    меньшей ширины.
    """
    rects = [list(polygon_bbox(b)) for b in boxes]
    changed = True
    while changed:
        changed = False
        merged: List[List[float]] = []
        used = [False] * len(rects)
        for i in range(len(rects)):
            if used[i]:
                continue
            ax0, ay0, ax1, ay1 = rects[i]
            for j in range(i + 1, len(rects)):
                if used[j]:
                    continue
                bx0, by0, bx1, by1 = rects[j]
                min_h = max(1.0, min(ay1 - ay0, by1 - by0))
                min_w = max(1.0, min(ax1 - ax0, bx1 - bx0))
                v_gap = max(ay0, by0) - min(ay1, by1)
                x_overlap = min(ax1, bx1) - max(ax0, bx0)
                if v_gap <= y_gap_ratio * min_h and x_overlap >= x_overlap_ratio * min_w:
                    ax0, ay0 = min(ax0, bx0), min(ay0, by0)
                    ax1, ay1 = max(ax1, bx1), max(ay1, by1)
                    used[j] = True
                    changed = True
            used[i] = True
            merged.append([ax0, ay0, ax1, ay1])
        rects = merged
    return [rect_polygon(x0, y0, x1, y1) for x0, y0, x1, y1 in rects]
