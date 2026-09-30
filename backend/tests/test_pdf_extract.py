import io
import random
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


def _single_page(line):
    return pdfium.PdfDocument(_build_pdf([(line, 10, 300)], page_w=600))[0]


def test_page_text_layer_usable_for_clean_layer():
    page = _single_page("The standard applies to washers for machine tools")
    assert pdf_extract.page_text_layer_usable(page) is True


def test_page_text_layer_not_usable_for_garbage_layer():
    # Слой есть, но это мусорное OCR сканера — страница должна уйти в OCR.
    page = _single_page("Th3 st4nd@rd app1ies t0 w4sh#rs f0r m4ch1ne")
    assert pdf_extract.page_text_layer_usable(page) is False


def test_page_text_layer_not_usable_for_blank_page(blank_pdf_doc):
    assert pdf_extract.page_text_layer_usable(blank_pdf_doc[0]) is False


def test_page_text_layer_usable_for_short_text(text_pdf_doc):
    # 2 слова — оценивать не по чему, но текст есть: берём слой.
    assert pdf_extract.page_text_layer_usable(text_pdf_doc[0]) is True


def test_page_words(text_pdf_doc):
    assert pdf_extract.page_words(text_pdf_doc[0]) == ["Hello", "World"]


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


def _rotated_text_page(text: str, rotate: int):
    data = _build_pdf([(text, 20, 20)], page_w=400, page_h=200).replace(
        b"/MediaBox [0 0 400 200]", f"/MediaBox [0 0 400 200] /Rotate {rotate}".encode()
    )
    return pdfium.PdfDocument(data)[0]


def test_extract_keeps_last_glyph_despite_float_edge_mismatch():
    """Край 'O' на ~1e-5 выходит за границу text-объекта — раньше "HELL"."""
    page = _rotated_text_page("HELLO", 0)
    image = pdf_extract.render_page(page)

    [(_, text)] = pdf_extract.extract_page_text_boxes(page, image.shape[1], image.shape[0])

    assert text == "HELLO"


@pytest.mark.parametrize("rotate", [0, 90, 180, 270])
def test_extract_box_covers_rendered_ink_on_rotated_pages(rotate):
    page = _rotated_text_page("HELLO", rotate)
    image = pdf_extract.render_page(page)
    height, width = image.shape[:2]

    [(box, _)] = pdf_extract.extract_page_text_boxes(page, width, height)

    ys, xs = (image.mean(axis=2) < 128).nonzero()
    (x0, y0), (x1, y1) = box[0], box[2]
    assert x0 <= xs.min() + 2 and xs.max() <= x1 + 2
    assert y0 <= ys.min() + 2 and ys.max() <= y1 + 2


def test_restore_hyphens_turns_soft_hyphen_markers_into_dash():
    assert pdf_extract._restore_hyphens("на фо\ufffe") == "на фо-"
    assert pdf_extract._restore_hyphens("стан\x02дарт") == "стан-дарт"


def _ink_and_box(seed):
    page = _rotated_text_page("HELLO", 0)
    image = pdf_extract.render_page(page)
    height, width = image.shape[:2]
    [(box, _)] = pdf_extract.extract_page_text_boxes(page, width, height, rng=random.Random(seed))
    no_pad = pdf_extract.extract_page_text_boxes(page, width, height, rng=_ZeroRng())
    return box, no_pad[0][0]


class _ZeroRng:
    """rng без поля: randint всегда возвращает нижнюю границу 0."""

    def randint(self, low, high):
        return 0


def test_extract_box_padding_is_random_within_ranges():
    x_lo, x_hi = pdf_extract.TEXT_BOX_PAD_X_RANGE
    y_lo, y_hi = pdf_extract.TEXT_BOX_PAD_Y_RANGE
    pads = set()
    for seed in range(40):
        box, bare = _ink_and_box(seed)
        left, top = bare[0][0] - box[0][0], bare[0][1] - box[0][1]
        right, bottom = box[2][0] - bare[2][0], box[2][1] - bare[2][1]
        assert x_lo <= left <= x_hi and x_lo <= right <= x_hi
        assert y_lo <= top <= y_hi and y_lo <= bottom <= y_hi
        pads.add((left, top, right, bottom))
    assert len(pads) > 1  # поле действительно случайное, не фиксированное


def test_extract_box_padding_reproducible_with_seed():
    assert _ink_and_box(7)[0] == _ink_and_box(7)[0]


def test_extract_box_padding_is_clamped_to_image():
    page = pdfium.PdfDocument(_build_pdf([("EDGE", 0, 0)]))[0]
    image = pdf_extract.render_page(page)
    height, width = image.shape[:2]

    [(box, _)] = pdf_extract.extract_page_text_boxes(page, width, height)

    (x0, y0), (x1, y1) = box[0], box[2]
    assert 0 <= x0 and 0 <= y0 and x1 <= width and y1 <= height


def _build_styled_pdf(lines: List[Tuple[str, str, float, int]]) -> bytes:
    """PDF из одной страницы 600×400: каждая строка — (text, BaseFont, кегль, y),
    своим шрифтом (Type1 из стандартных 14 или с префиксом подмножества),
    отдельным BT/Tj/ET — отдельным text-объектом."""
    fonts = sorted({base for _, base, _, _ in lines})
    font_num = {base: 5 + i for i, base in enumerate(fonts)}
    font_refs = " ".join(f"/F{font_num[b]} {font_num[b]} 0 R" for b in fonts)
    stream = "\n".join(
        f"BT /F{font_num[base]} {size} Tf 20 {y} Td ({text}) Tj ET" for text, base, size, y in lines
    ).encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 400] "
            f"/Resources << /Font << {font_refs} >> >> /Contents 4 0 R >>"
        ).encode(),
        f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream",
    ] + [f"<< /Type /Font /Subtype /Type1 /BaseFont /{b} >>".encode() for b in fonts]

    buf = io.BytesIO()
    buf.write(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(buf.tell())
        buf.write(f"{i} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref_offset = buf.tell()
    buf.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        buf.write(f"{off:010d} 00000 n \n".encode())
    buf.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF".encode()
    )
    return buf.getvalue()


STYLED_LINES = [
    ("Regular line", "Helvetica", 24, 340),
    ("Bold line", "Helvetica-Bold", 12, 280),
    ("Oblique line", "Helvetica-Oblique", 16, 220),
    ("Bold italic line", "Times-BoldItalic", 10.5, 160),
    ("Subset font line", "ABCDEF+Courier", 8, 100),
]


@pytest.fixture
def styled_page():
    doc = pdfium.PdfDocument(_build_styled_pdf(STYLED_LINES))
    yield doc[0]
    doc.close()


def test_extract_page_text_lines_reports_font_size_bold_italic(styled_page):
    lines = pdf_extract.extract_page_text_lines(styled_page, 600, 400, rng=random.Random(0))

    got = {line.text: line.style for line in lines}
    assert set(got) == {text for text, _, _, _ in STYLED_LINES}
    for text, base, size, _ in STYLED_LINES:
        style = got[text]
        assert style.font_size == pytest.approx(size, abs=0.01), text
        assert style.bold == ("Bold" in base), text
        assert style.italic == ("Italic" in base or "Oblique" in base), text


def test_extract_page_text_lines_strips_subset_prefix(styled_page):
    lines = pdf_extract.extract_page_text_lines(styled_page, 600, 400, rng=random.Random(0))

    names = {line.text: line.style.font_name for line in lines}
    assert names["Subset font line"] == "Courier"
    assert names["Bold line"] == "Helvetica-Bold"


def test_extract_page_text_boxes_matches_lines_with_same_seed(styled_page):
    lines = pdf_extract.extract_page_text_lines(styled_page, 600, 400, rng=random.Random(7))
    boxes = pdf_extract.extract_page_text_boxes(styled_page, 600, 400, rng=random.Random(7))

    assert boxes == [(line.box, line.text) for line in lines]
