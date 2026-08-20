import io
from typing import List, Optional, Tuple

import pypdfium2 as pdfium
import pytest

from backend import pdf_extract


def _build_pdf(
    pages: List[Optional[Tuple[str, int, int]]], page_w: int = 400, page_h: int = 400
) -> bytes:
    """Собирает минимальный валидный PDF без внешних библиотек.

    pages: список, где каждый элемент — None (пустая страница без текста)
    либо (text, x, y) — страница с одной строкой текста Helvetica 24pt,
    показанной оператором Tj в точке (x, y) (PDF user space, Y снизу вверх).

    Схема нумерации объектов (фиксированная, соответствует порядку append
    ниже): 1 Catalog, 2 Pages, 3..2+n Page-объекты, 3+n Font, 4+n..3+2n
    Content-стримы.
    """
    n = len(pages)
    font_obj_num = 3 + n
    content_obj_nums = [4 + n + i for i in range(n)]

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        (
            f"<< /Type /Pages /Kids [{' '.join(f'{3 + i} 0 R' for i in range(n))}] "
            f"/Count {n} >>"
        ).encode(),
    ]
    for i, p in enumerate(pages):
        resources = f"<< /Font << /F1 {font_obj_num} 0 R >> >>" if p is not None else "<< >>"
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_w} {page_h}] "
                f"/Resources {resources} /Contents {content_obj_nums[i]} 0 R >>"
            ).encode()
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for p in pages:
        stream = b"" if p is None else f"BT /F1 24 Tf {p[1]} {p[2]} Td ({p[0]}) Tj ET".encode()
        objects.append(f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream")

    buf = io.BytesIO()
    buf.write(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(buf.tell())
        buf.write(f"{i} 0 obj\n".encode())
        buf.write(obj)
        buf.write(b"\nendobj\n")
    xref_offset = buf.tell()
    total = len(objects) + 1
    buf.write(f"xref\n0 {total}\n".encode())
    buf.write(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        buf.write(f"{off:010d} 00000 n \n".encode())
    buf.write(f"trailer\n<< /Size {total} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF".encode())
    return buf.getvalue()


@pytest.fixture
def text_pdf_doc():
    doc = pdfium.PdfDocument(_build_pdf([("Hello World", 72, 300)]))
    yield doc
    doc.close()


@pytest.fixture
def blank_pdf_doc():
    doc = pdfium.PdfDocument(_build_pdf([None]))
    yield doc
    doc.close()


def test_page_has_text_layer_true_for_text_page(text_pdf_doc):
    assert pdf_extract.page_has_text_layer(text_pdf_doc[0]) is True


def test_page_has_text_layer_false_for_blank_page(blank_pdf_doc):
    assert pdf_extract.page_has_text_layer(blank_pdf_doc[0]) is False


def test_document_has_text_layer_true_when_second_probed_page_has_text():
    doc = pdfium.PdfDocument(_build_pdf([None, ("Page Two", 72, 300)]))
    try:
        assert pdf_extract.document_has_text_layer(doc) is True
    finally:
        doc.close()


def test_document_has_text_layer_false_when_text_starts_after_probe_range():
    # Осознанное упрощение: пробинг смотрит только первые 2 страницы.
    doc = pdfium.PdfDocument(_build_pdf([None, None, ("Page Three", 72, 300)]))
    try:
        assert pdf_extract.document_has_text_layer(doc) is False
    finally:
        doc.close()


def test_document_has_text_layer_false_for_fully_blank_document(blank_pdf_doc):
    assert pdf_extract.document_has_text_layer(blank_pdf_doc) is False


def test_render_page_returns_rgb_uint8_array(text_pdf_doc):
    image = pdf_extract.render_page(text_pdf_doc[0], dpi=200)
    assert image.ndim == 3
    assert image.shape[2] == 3
    assert image.dtype.name == "uint8"
    # страница 400x400pt при 200dpi (scale=200/72) -> ~1112x1112px
    assert image.shape[0] == pytest.approx(1112, abs=2)
    assert image.shape[1] == pytest.approx(1112, abs=2)


def test_extract_page_text_boxes_returns_text_and_pixel_box(text_pdf_doc):
    page = text_pdf_doc[0]
    image = pdf_extract.render_page(page, dpi=200)
    image_height, image_width = image.shape[:2]

    boxes = pdf_extract.extract_page_text_boxes(page, image_width, image_height)

    assert len(boxes) == 1
    box, text = boxes[0]
    assert text == "Hello World"
    x0, y0 = box[0]
    x2, y2 = box[2]
    assert 0 <= x0 < x2 <= image_width
    assert 0 <= y0 < y2 <= image_height


def test_extract_page_text_boxes_empty_for_blank_page(blank_pdf_doc):
    page = blank_pdf_doc[0]
    image = pdf_extract.render_page(page, dpi=200)
    image_height, image_width = image.shape[:2]

    assert pdf_extract.extract_page_text_boxes(page, image_width, image_height) == []
