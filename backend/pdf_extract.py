"""Извлечение текстового слоя PDF без OCR через pypdfium2.

pypdfium2 — лёгкая самодостаточная библиотека (без скачиваемых моделей и
системных бинарников), поэтому в отличие от detector.py/recognizers.py этот
модуль полностью юнит-тестируется (см. backend/tests/test_pdf_extract.py и
docs/testing.md).
"""

import ctypes
from typing import List, Tuple

import numpy as np
import pypdfium2 as pdfium

from backend import text_layer_quality

PDF_RENDER_DPI = 200
PROBE_PAGE_COUNT = 2


def _object_pos(obj) -> Tuple[float, float, float, float]:
    """(left, bottom, right, top) текстового объекта в координатах страницы PDF.

    pypdfium2 4.x — ``obj.get_pos()``; 5.x переименовал его в ``obj.get_bounds()``
    (та же семантика возврата). Поддерживаем обе, чтобы пин backend/requirements
    и локальное окружение могли расходиться по минорной версии без падения.
    """
    getter = getattr(obj, "get_pos", None) or obj.get_bounds
    return getter()


def render_page(page: pdfium.PdfPage, dpi: int = PDF_RENDER_DPI) -> np.ndarray:
    """Рендерит страницу PDF в numpy-изображение (RGB) при заданном DPI"""
    bitmap = page.render(scale=dpi / 72)
    return np.array(bitmap.to_pil().convert("RGB"))


def _page_to_pixel(page: pdfium.PdfPage, x: float, y: float, width: int, height: int):
    """Точка PDF user space → пиксель картинки render_page() размера width×height.

    Через pdfium FPDF_PageToDevice: он применяет ту же матрицу, что и рендер,
    включая /Rotate страницы. Прежнее ручное «x/page_width, page_height - y»
    не знало о повороте — на страницах с /Rotate 90/180/270 боксы уезжали
    в другое место листа (кроп не той области под текстом строки)."""
    device_x, device_y = ctypes.c_int(), ctypes.c_int()
    pdfium.raw.FPDF_PageToDevice(page.raw, 0, 0, width, height, 0, x, y, device_x, device_y)
    return device_x.value, device_y.value


def _pixel_rect(page: pdfium.PdfPage, left, bottom, right, top, width: int, height: int):
    """Прямоугольник PDF user space → осевой прямоугольник в пикселях
    [[x0,y0],[x1,y0],[x1,y1],[x0,y1]] (углы после поворота нормализуются)."""
    corners = [
        _page_to_pixel(page, px, py, width, height)
        for px, py in ((left, bottom), (right, bottom), (right, top), (left, top))
    ]
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def _center_inside(box, left, bottom, right, top) -> bool:
    """Центр charbox внутри границ объекта. Строгое «charbox целиком внутри»
    отбрасывало символы из-за float-погрешности pdfium (край глифа 97.61600494
    против границы объекта 97.61599731): "HELLO" извлекалось как "HELL", а
    если такой символ был в середине строки — текст терял букву, которую
    кроп при этом показывает (неверная подпись в good.txt)."""
    cx = (box[0] + box[2]) / 2
    cy = (box[1] + box[3]) / 2
    return left <= cx <= right and bottom <= cy <= top


def extract_page_text_boxes(
    page: pdfium.PdfPage, image_width: int, image_height: int
) -> List[Tuple[List[List[float]], str]]:
    """Извлекает текстовые боксы страницы PDF из текстового слоя (без OCR).

    Группировка — по PDF text-объектам (аналог прежнего, не входящего в
    сервис прототипа, см. predict.py::extract_text_pdf в корне репозитория).
    Один PDF text-объект обычно соответствует одному вызову показа текста
    (Tj/TJ) — на практике чаще всего строка или её часть, не гарантированная
    построчная группировка, а лучшее доступное приближение.

    Возвращает список (box, text), box — [[x0,y0],[x1,y0],[x1,y1],[x0,y1]]
    в пиксельных координатах изображения, отрендеренного через render_page()
    ДЛЯ ЭТОЙ ЖЕ страницы этим же image_width/image_height (координаты зависят
    от масштаба рендера; поворот страницы учитывается, см. _page_to_pixel).
    """
    textpage = page.get_textpage()
    try:
        char_boxes = [textpage.get_charbox(i) for i in range(textpage.count_chars())]

        result: List[Tuple[List[List[float]], str]] = []
        for obj in page.get_objects(filter=[pdfium.raw.FPDF_PAGEOBJ_TEXT]):
            left_b, bottom_b, right_b, top_b = _object_pos(obj)
            indices = [
                i
                for i, box in enumerate(char_boxes)
                if _center_inside(box, left_b, bottom_b, right_b, top_b)
            ]
            if not indices:
                continue

            text = "".join(textpage.get_text_range(i, 1) for i in indices).strip()
            if not text:
                continue

            boxes = [char_boxes[i] for i in indices]
            left = min(b[0] for b in boxes)
            bottom = min(b[1] for b in boxes)
            right = max(b[2] for b in boxes)
            top = max(b[3] for b in boxes)

            rect = _pixel_rect(page, left, bottom, right, top, image_width, image_height)
            result.append((rect, text))

        return result
    finally:
        textpage.close()


def page_has_text_layer(page: pdfium.PdfPage) -> bool:
    """True, если у страницы PDF есть непустой извлекаемый текстовый слой"""
    textpage = page.get_textpage()
    try:
        if textpage.count_chars() == 0:
            return False
        return bool(textpage.get_text_bounded().strip())
    finally:
        textpage.close()


def page_words(page: pdfium.PdfPage) -> List[str]:
    """Слова текстового слоя страницы (для оценки качества, без координат)"""
    textpage = page.get_textpage()
    try:
        return textpage.get_text_bounded().split()
    finally:
        textpage.close()


def document_has_text_layer(
    pdf_doc: pdfium.PdfDocument, probe_pages: int = PROBE_PAGE_COUNT
) -> bool:
    """Решение "использовать текстовый слой" на уровне всего документа.

    1. Наличие: проверяются только первые `probe_pages` страниц (по умолчанию
       2) — если ни одна не содержит текста, документ целиком обрабатывается
       через обычный OCR-консенсус, даже если текстовый слой появляется на
       более поздних страницах (осознанное упрощение, см. план/PRD).
    2. Качество: слой сканов — чужое OCR, на машинописи и плохих сканах часто
       мусорный. Если хороших страниц по всему документу слишком мало
       (text_layer_quality.layer_is_trustworthy), документ тоже идёт в OCR,
       а не попадает в good.txt как есть.
    """
    has_text = any(
        page_has_text_layer(pdf_doc[page_index])
        for page_index in range(min(probe_pages, len(pdf_doc)))
    )
    if not has_text:
        return False
    pages_words = [page_words(pdf_doc[page_index]) for page_index in range(len(pdf_doc))]
    qualities = text_layer_quality.page_qualities(pages_words)
    return text_layer_quality.layer_is_trustworthy(qualities)
