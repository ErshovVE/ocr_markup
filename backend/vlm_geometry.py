"""Чистая геометрия боксов: VLM-режим (backend/pipeline_vlm.py) и вырезание
кропов обоих путей (clamped_bbox → backend/pipeline.py::crop_by_polygon).

Вынесено отдельным модулем без тяжёлых зависимостей, поэтому полностью
юнит-тестируется (в отличие от backend/vlm_layout.py, который дергает
backend.detector.Detector — см. docs/testing.md).

Полигоны, которые строит этот модуль, — прямоугольники
[[x0, y0], [x1, y0], [x1, y1], [x0, y1]]. Входные полигоны (детекторы, текстовый
слой PDF) могут быть произвольными четырёхугольниками — bbox берётся по всем
вершинам (polygon_bbox/clamped_bbox).
"""

import math
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


def clamped_bbox(poly, width: int, height: int) -> Tuple[int, int, int, int]:
    """Целочисленный bbox полигона, зажатый в границы картинки width×height.

    Общий для всех путей вырезания кропа (см. backend/pipeline.py::crop_by_polygon).
    bbox — по ВСЕМ вершинам, а не box[0]/box[2]: у наклонного четырёхугольника
    детектора Paddle эти две вершины не обязаны быть левым-верхним/правым-нижним.
    Зажим обязателен: отрицательный старт numpy-среза считается с конца массива
    и даёт кроп не с того места. floor/ceil — чтобы дробные координаты (текстовый
    слой PDF, Surya) не срезали край строки."""
    x0, y0, x1, y1 = polygon_bbox(poly)
    x0 = max(0, min(math.floor(x0), width))
    y0 = max(0, min(math.floor(y0), height))
    x1 = max(0, min(math.ceil(x1), width))
    y1 = max(0, min(math.ceil(y1), height))
    return x0, y0, x1, y1


def scale_polygon(poly, sx: float, sy: float) -> Polygon:
    """Полигон, масштабированный по осям (перевод между пространствами страницы)."""
    return [[p[0] * sx, p[1] * sy] for p in poly]
