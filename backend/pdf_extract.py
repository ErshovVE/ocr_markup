"""Извлечение текстового слоя PDF без OCR через pypdfium2.

pypdfium2 — лёгкая самодостаточная библиотека (без скачиваемых моделей и
системных бинарников), поэтому в отличие от detector.py/recognizers.py этот
модуль полностью юнит-тестируется (см. backend/tests/test_pdf_extract.py и
docs/testing.md).
"""

import ctypes
import random
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pypdfium2 as pdfium

from backend import text_layer_quality

PDF_RENDER_DPI = 200
# Поле вокруг рамки строки из текстового слоя, пиксели рендера: случайное для
# каждой стороны каждой строки (включительные диапазоны). Рамка слоя идёт
# впритык к буквам и чуть смещена относительно краски — без поля кроп срезал
# края глифов; случайное вместо фиксированного — чтобы датасет не приучал
# модель к одинаковым отступам.
TEXT_BOX_PAD_X_RANGE = (1, 3)  # слева и справа
TEXT_BOX_PAD_Y_RANGE = (0, 2)  # сверху и снизу
_RNG = random.Random()

# Флаги шрифта PDF (FontDescriptor /Flags, ISO 32000-1 табл. 123), которые
# pdfium отдаёт через FPDFText_GetFontInfo.
_FONT_FLAG_ITALIC = 1 << 6
_FONT_FLAG_FORCE_BOLD = 1 << 18
# Жирность по имени: FPDFText_GetFontWeight на PDF из LibreOffice всегда 400
# даже для LiberationSans-Bold, так что имя — основной источник.
_BOLD_NAME = re.compile(r"bold|black|heavy|semibold|demi", re.IGNORECASE)
_ITALIC_NAME = re.compile(r"italic|oblique", re.IGNORECASE)
_SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")


@dataclass
class TextStyle:
    """Оформление строки текстового слоя, как его видит pdfium."""

    font_name: str  # базовое имя шрифта без префикса подмножества (ABCDEF+)
    font_size: float  # кегль в пунктах с учётом матрицы текста
    bold: bool
    italic: bool


@dataclass
class TextLine:
    """Строка текстового слоя: рамка в пикселях рендера, текст и оформление."""

    box: List[List[float]]
    text: str
    style: TextStyle


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


def _pixel_rect(
    page: pdfium.PdfPage,
    left,
    bottom,
    right,
    top,
    width: int,
    height: int,
    pad: Tuple[int, int, int, int] = (0, 0, 0, 0),
):
    """Прямоугольник PDF user space → осевой прямоугольник в пикселях
    [[x0,y0],[x1,y0],[x1,y1],[x0,y1]] (углы после поворота нормализуются)."""
    corners = [
        _page_to_pixel(page, px, py, width, height)
        for px, py in ((left, bottom), (right, bottom), (right, top), (left, top))
    ]
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    # pad = (слева, сверху, справа, снизу) в пикселях картинки, в её пределах.
    pad_left, pad_top, pad_right, pad_bottom = pad
    x0 = max(0, min(xs) - pad_left)
    y0 = max(0, min(ys) - pad_top)
    x1 = min(width, max(xs) + pad_right)
    y1 = min(height, max(ys) + pad_bottom)
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def _chars_by_text_object(textpage: pdfium.PdfTextPage) -> List[List[int]]:
    """Индексы символов страницы, сгруппированные по PDF text-объекту, которому
    их приписал сам pdfium (FPDFText_GetTextObject), в порядке первого символа.

    Раньше символ относили к объекту геометрически — центр его рамки внутри
    границ объекта. На сканах с невидимым слоем FineReader шрифты не встроены
    (TimesNewRoman, Tahoma), и без них в системе (slim Docker-образ) pdfium
    считает границы объекта по контурам глифов шрифта-замены — для кириллицы
    вырожденным: граница обрывалась на начале последней буквы, и строки
    теряли её в тексте и в кропе ("от 20 декабр")."""
    groups: Dict[int, List[int]] = {}
    for index in range(textpage.count_chars()):
        handle = pdfium.raw.FPDFText_GetTextObject(textpage.raw, index)
        key = ctypes.cast(handle, ctypes.c_void_p).value
        if key is not None:
            groups.setdefault(key, []).append(index)
    return list(groups.values())


def _restore_hyphens(text: str) -> str:
    """Мягкий перенос pdfium (text_layer_quality.SOFT_HYPHENS) -> видимый дефис:
    на скане в конце строки напечатан обычный знак переноса, подпись к кропу
    должна с ним совпадать."""
    for char in text_layer_quality.SOFT_HYPHENS:
        text = text.replace(char, "-")
    return text


def _random_pad(rng: random.Random) -> Tuple[int, int, int, int]:
    """(слева, сверху, справа, снизу) из TEXT_BOX_PAD_X_RANGE/TEXT_BOX_PAD_Y_RANGE."""
    return (
        rng.randint(*TEXT_BOX_PAD_X_RANGE),
        rng.randint(*TEXT_BOX_PAD_Y_RANGE),
        rng.randint(*TEXT_BOX_PAD_X_RANGE),
        rng.randint(*TEXT_BOX_PAD_Y_RANGE),
    )


def _char_style(textpage: pdfium.PdfTextPage, index: int) -> TextStyle:
    """Оформление символа index. У PDF text-объекта один шрифт и кегль,
    поэтому стиль первого непробельного символа — стиль всей строки."""
    flags = ctypes.c_int()
    size = pdfium.raw.FPDFText_GetFontInfo(textpage.raw, index, None, 0, ctypes.byref(flags))
    buffer = ctypes.create_string_buffer(max(size, 1))
    pdfium.raw.FPDFText_GetFontInfo(textpage.raw, index, buffer, size, ctypes.byref(flags))
    name = _SUBSET_PREFIX.sub("", buffer.value.decode("utf-8", "replace"))
    weight = pdfium.raw.FPDFText_GetFontWeight(textpage.raw, index)
    return TextStyle(
        font_name=name,
        font_size=round(pdfium.raw.FPDFText_GetFontSize(textpage.raw, index), 2),
        bold=bool(_BOLD_NAME.search(name))
        or weight >= 600
        or bool(flags.value & _FONT_FLAG_FORCE_BOLD),
        italic=bool(_ITALIC_NAME.search(name)) or bool(flags.value & _FONT_FLAG_ITALIC),
    )


def extract_page_text_lines(
    page: pdfium.PdfPage,
    image_width: int,
    image_height: int,
    rng: Optional[random.Random] = None,
) -> List[TextLine]:
    """Строки текстового слоя страницы вместе с оформлением (шрифт, кегль,
    жирный, курсив) — для генераторов датасета, которым нужно знать, каким
    шрифтом напечатан каждый кроп (балансировка по шрифтам/кеглям/стилям).

    Рамки и тексты — те же, что у extract_page_text_boxes (она построена на
    этой функции), с тем же порядком обращений к rng."""
    textpage = page.get_textpage()
    try:
        result: List[TextLine] = []
        for indices in _chars_by_text_object(textpage):
            chars = [textpage.get_text_range(i, 1) for i in indices]
            text = _restore_hyphens("".join(chars)).strip()
            if not text:
                continue

            # loose=True: рамка по ширине символа и высоте шрифта из самого PDF,
            # а не по контурам глифа — не зависит от наличия шрифта в системе.
            # Пробелы/переводы строк в рамку не входят (у них нулевая высота).
            ink = [i for i, char in zip(indices, chars, strict=True) if char.strip()]
            boxes = [textpage.get_charbox(i, loose=True) for i in ink]
            left = min(b[0] for b in boxes)
            bottom = min(b[1] for b in boxes)
            right = max(b[2] for b in boxes)
            top = max(b[3] for b in boxes)

            rect = _pixel_rect(
                page,
                left,
                bottom,
                right,
                top,
                image_width,
                image_height,
                pad=_random_pad(rng or _RNG),
            )
            result.append(TextLine(box=rect, text=text, style=_char_style(textpage, ink[0])))

        return result
    finally:
        textpage.close()


def extract_page_text_boxes(
    page: pdfium.PdfPage,
    image_width: int,
    image_height: int,
    rng: Optional[random.Random] = None,
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
    К рамке добавляется случайное поле (TEXT_BOX_PAD_X_RANGE по горизонтали,
    TEXT_BOX_PAD_Y_RANGE по вертикали, независимо для каждой стороны); rng —
    источник случайности (по умолчанию общий модульный, в тестах — с seed).
    Оформление строк — extract_page_text_lines.
    """
    return [
        (line.box, line.text)
        for line in extract_page_text_lines(page, image_width, image_height, rng)
    ]


def page_words(page: pdfium.PdfPage) -> List[str]:
    """Слова текстового слоя страницы (для оценки качества, без координат)"""
    textpage = page.get_textpage()
    try:
        return textpage.get_text_bounded().split()
    finally:
        textpage.close()


def page_text_layer_usable(page: pdfium.PdfPage) -> bool:
    """Решение "текстовый слой вместо OCR" для одной страницы.

    Слой сканов — чужое OCR (сканер, FineReader), на машинописи и плохих
    сканах он с ошибками. Страница берётся из слоя, только если текст есть и
    его качество не ниже text_layer_quality.PAGE_MIN_QUALITY; иначе она идёт
    через OCR-консенсус, как растровая. Решение постраничное: в одном
    документе чистые страницы берутся из слоя, а титул, таблицы и страницы с
    плохим слоем — распознаются."""
    return text_layer_quality.page_is_usable(page_words(page))
