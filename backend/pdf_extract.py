"""Извлечение текстового слоя PDF без OCR через pypdfium2.

pypdfium2 — лёгкая самодостаточная библиотека (без скачиваемых моделей и
системных бинарников), поэтому в отличие от detector.py/recognizers.py этот
модуль полностью юнит-тестируется (см. backend/tests/test_pdf_extract.py и
docs/testing.md).
"""

from typing import List, Tuple

import numpy as np
import pypdfium2 as pdfium

PDF_RENDER_DPI = 200
PROBE_PAGE_COUNT = 2


def render_page(page: pdfium.PdfPage, dpi: int = PDF_RENDER_DPI) -> np.ndarray:
    """Рендерит страницу PDF в numpy-изображение (RGB) при заданном DPI"""
    bitmap = page.render(scale=dpi / 72)
    return np.array(bitmap.to_pil().convert("RGB"))


def _pdf_x_to_pix(x: float, page_width: float, image_width: int) -> float:
    return x / page_width * image_width


def _pdf_y_to_pix(y: float, page_height: float, image_height: int) -> float:
    # PDF: ось Y растёт снизу вверх; растровое изображение: сверху вниз
    return image_height - (y / page_height * image_height)


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
    от масштаба рендера).
    """
    page_width, page_height = page.get_size()
    textpage = page.get_textpage()
    char_boxes = [textpage.get_charbox(i) for i in range(textpage.count_chars())]

    result: List[Tuple[List[List[float]], str]] = []
    for obj in page.get_objects(filter=[pdfium.raw.FPDF_PAGEOBJ_TEXT]):
        left_b, bottom_b, right_b, top_b = obj.get_pos()
        indices = [
            i
            for i, box in enumerate(char_boxes)
            if box[0] >= left_b and box[2] <= right_b and box[1] >= bottom_b and box[3] <= top_b
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

        x0 = _pdf_x_to_pix(left, page_width, image_width)
        y0 = _pdf_y_to_pix(top, page_height, image_height)
        x1 = _pdf_x_to_pix(right, page_width, image_width)
        y1 = _pdf_y_to_pix(bottom, page_height, image_height)

        result.append(([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], text))

    return result


def page_has_text_layer(page: pdfium.PdfPage) -> bool:
    """True, если у страницы PDF есть непустой извлекаемый текстовый слой"""
    textpage = page.get_textpage()
    if textpage.count_chars() == 0:
        return False
    return bool(textpage.get_text_bounded().strip())


def document_has_text_layer(
    pdf_doc: pdfium.PdfDocument, probe_pages: int = PROBE_PAGE_COUNT
) -> bool:
    """Решение "использовать текстовый слой" на уровне всего документа.

    Проверяет только первые `probe_pages` страниц (по умолчанию 2) — если ни
    одна из них не содержит текста, документ целиком обрабатывается через
    обычный OCR-консенсус, даже если текстовый слой появляется на более
    поздних страницах (осознанное упрощение, см. план/PRD).
    """
    for page_index in range(min(probe_pages, len(pdf_doc))):
        if page_has_text_layer(pdf_doc[page_index]):
            return True
    return False
