"""Промпты и парсеры ответов VLM: сырой ответ модели → [(полигон, текст)].

Каждая модель отдаёт grounding по-своему (см. docs/research/vlm-ocr-mode.md):
  - hunyuan_ocr   — text spotting: строки вида ``текст(x1,y1),(x2,y2)``
  - dots_ocr      — JSON ``[{"bbox":[x1,y1,x2,y2], "category":..., "text":...}]``
  - unlimited_ocr — grounded markdown с токенами ``<ref>...</ref><box>...</box>``
  - paddleocr_vl  — JSON pipeline-вывода (элементы с ``bbox`` + ``text``)
  - glm_ocr       — только markdown без боксов (боксы даёт backend/vlm_layout.py)

Паттерн — как у backend/recognizers.py: узкая функция, свои исключения не
пробрасывает, на битом/пустом ответе возвращает ``[]`` (для glm_ocr — ``[]``
список строк), а не падает.
"""

import json
import re
from typing import List, Tuple

from backend.vlm_geometry import Polygon, rect_polygon

# Точные строки промптов — из карточек моделей / техотчётов (см. research-док).
PROMPTS = {
    "hunyuan_ocr": (
        "Detect and recognize text in the image, and output the text "
        "coordinates in a formatted manner."
    ),
    "dots_ocr": (
        "Parse the layout of this document image. For every text region output a "
        "JSON array of objects with keys: bbox ([x1, y1, x2, y2] in pixels), "
        "category and text. Return only the JSON array."
    ),
    "paddleocr_vl": (
        "Recognize all text in the image. Return a JSON array of objects with "
        "keys bbox ([x1, y1, x2, y2] in pixels) and text, one object per line."
    ),
    "glm_ocr": "Convert the document in the image to Markdown. Output only the content.",
    "unlimited_ocr": (
        "Convert the document to grounded markdown: wrap each text span as "
        "<ref>text</ref><box>(x1,y1),(x2,y2)</box>."
    ),
}

# Минимальный LaTeX→Unicode (перенос идеи из Folio-OCR latex_unicode.json —
# полную таблицу тянуть не стали, VLM-markdown у нас кладётся построчно).
_LATEX_UNICODE = {
    r"\times": "×",
    r"\div": "÷",
    r"\pm": "±",
    r"\mp": "∓",
    r"\leq": "≤",
    r"\geq": "≥",
    r"\neq": "≠",
    r"\approx": "≈",
    r"\infty": "∞",
    r"\rightarrow": "→",
    r"\leftarrow": "←",
    r"\Rightarrow": "⇒",
    r"\deg": "°",
    r"\alpha": "α",
    r"\beta": "β",
    r"\gamma": "γ",
    r"\delta": "δ",
    r"\pi": "π",
    r"\mu": "µ",
    r"\Omega": "Ω",
}

_FENCE_OPEN_RE = re.compile(r"^```[a-zA-Z]*\n?")
_FENCE_CLOSE_RE = re.compile(r"\n?```$")
_WS_RE = re.compile(r"[ \t]+")


def postprocess_text(text: str) -> str:
    """Снимает ```-обрамление, заменяет частые LaTeX-макросы на Unicode,
    схлопывает пробелы. Пустой/None → ``""``."""
    if not text:
        return ""
    cleaned = text.strip()
    cleaned = _FENCE_OPEN_RE.sub("", cleaned)
    cleaned = _FENCE_CLOSE_RE.sub("", cleaned)
    cleaned = cleaned.strip()
    for macro, uni in _LATEX_UNICODE.items():
        cleaned = cleaned.replace(macro, uni)
    cleaned = _WS_RE.sub(" ", cleaned)
    return cleaned.strip()


def _strip_json_fence(raw: str) -> str:
    """Модели часто оборачивают JSON в ```json ... ``` — срезаем до json.loads."""
    if not raw:
        return ""
    text = raw.strip()
    text = _FENCE_OPEN_RE.sub("", text)
    text = _FENCE_CLOSE_RE.sub("", text)
    return text.strip()


# Координатные соглашения различаются по моделям и НЕ угадываются по значению
# (пиксельный x0=900 на странице 2000px неотличим от промилле). Поэтому:
#   - hunyuan_ocr / dots_ocr / paddleocr_vl — пиксели, берём как есть;
#   - unlimited_ocr (линейка DeepSeek-OCR) — промилле 0..999, делим на 1000 и
#     умножаем на размер страницы (если он передан парсеру).


def _permille_to_px(value: float, axis_size: int) -> float:
    """Промилле (0..1000) → пиксели по размеру оси. Без размера — как есть."""
    if axis_size <= 0:
        return value
    return value / 1000.0 * axis_size


_HUNYUAN_RE = re.compile(
    r"([^\n]+?)\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)\s*,\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)"
)


def parse_hunyuan_spotting(
    raw: str, image_w: int = 0, image_h: int = 0
) -> List[Tuple[Polygon, str]]:
    """HunyuanOCR text spotting: строки ``текст(x1,y1),(x2,y2)`` (пиксели)."""
    lines: List[Tuple[Polygon, str]] = []
    for match in _HUNYUAN_RE.finditer(raw or ""):
        text = match.group(1).strip()
        if not text:
            continue
        x1, y1, x2, y2 = (float(match.group(i)) for i in range(2, 6))
        lines.append((rect_polygon(x1, y1, x2, y2), text))
    return lines


_DOTS_SKIP_CATEGORIES = {"Picture", "Figure", "Formula"}


def parse_dotsocr(raw: str, image_w: int = 0, image_h: int = 0) -> List[Tuple[Polygon, str]]:
    """dots.ocr: JSON ``[{"bbox":[x1,y1,x2,y2], "category":..., "text":...}]``."""
    try:
        data = json.loads(_strip_json_fence(raw))
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    lines: List[Tuple[Polygon, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        if item.get("category") in _DOTS_SKIP_CATEGORIES:
            continue
        bbox = item.get("bbox")
        text = (item.get("text") or "").strip()
        if not text or not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            continue
        lines.append((rect_polygon(*(float(v) for v in bbox)), text))
    return lines


_UNLIMITED_RE = re.compile(
    r"<ref>(.*?)</ref>\s*<box>\s*\(?\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)?\s*,"
    r"\s*\(?\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)?\s*</box>",
    re.DOTALL,
)


def parse_unlimited_ocr(raw: str, image_w: int = 0, image_h: int = 0) -> List[Tuple[Polygon, str]]:
    """Unlimited-OCR (линейка DeepSeek-OCR): токены ``<ref>...</ref><box>...</box>``
    с координатами в промилле (0..999) — приводим к пикселям по размеру страницы."""
    lines: List[Tuple[Polygon, str]] = []
    for match in _UNLIMITED_RE.finditer(raw or ""):
        text = match.group(1).strip()
        if not text:
            continue
        x1 = _permille_to_px(float(match.group(2)), image_w)
        y1 = _permille_to_px(float(match.group(3)), image_h)
        x2 = _permille_to_px(float(match.group(4)), image_w)
        y2 = _permille_to_px(float(match.group(5)), image_h)
        lines.append((rect_polygon(x1, y1, x2, y2), text))
    return lines


def _coerce_bbox(item):
    """bbox элемента → (x0, y0, x1, y1) в пикселях; поддерживает [x1,y1,x2,y2]
    и полигон [[x,y], ...]. Иначе None."""
    bbox = item.get("bbox") or item.get("box") or item.get("poly")
    if (
        isinstance(bbox, (list, tuple))
        and len(bbox) == 4
        and all(isinstance(v, (int, float)) for v in bbox)
    ):
        return tuple(float(v) for v in bbox)
    if isinstance(bbox, (list, tuple)) and bbox and isinstance(bbox[0], (list, tuple)):
        xs = [float(p[0]) for p in bbox]
        ys = [float(p[1]) for p in bbox]
        return min(xs), min(ys), max(xs), max(ys)
    return None


def parse_paddleocr_vl(raw: str, image_w: int = 0, image_h: int = 0) -> List[Tuple[Polygon, str]]:
    """PaddleOCR-VL pipeline JSON (пиксели): список элементов с ``bbox`` +
    ``text``/``rec_text`` либо словарь с параллельными массивами
    ``rec_polys``/``dt_polys`` + ``rec_texts``."""
    try:
        data = json.loads(_strip_json_fence(raw))
    except (ValueError, TypeError):
        return []

    lines: List[Tuple[Polygon, str]] = []

    if isinstance(data, dict) and "rec_texts" in data:
        polys = data.get("rec_polys") or data.get("dt_polys") or []
        for poly, text in zip(polys, data["rec_texts"], strict=False):
            text = (text or "").strip()
            if not text or not isinstance(poly, (list, tuple)) or not poly:
                continue
            if isinstance(poly[0], (list, tuple)):
                xs = [float(p[0]) for p in poly]
                ys = [float(p[1]) for p in poly]
                lines.append((rect_polygon(min(xs), min(ys), max(xs), max(ys)), text))
            elif len(poly) == 4:
                lines.append((rect_polygon(*(float(v) for v in poly)), text))
        return lines

    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("elements", [])
    else:
        items = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = (item.get("text") or item.get("rec_text") or "").strip()
        rect = _coerce_bbox(item)
        if not text or rect is None:
            continue
        lines.append((rect_polygon(*rect), text))
    return lines


def parse_glm_ocr(raw: str) -> List[str]:
    """GLM-OCR отдаёт только markdown — возвращаем список непустых строк текста
    (без боксов; их добавит backend/vlm_layout.py по стратегии ``layout``)."""
    cleaned = postprocess_text(raw)
    return [line.strip() for line in cleaned.splitlines() if line.strip()]


def parse(engine_id: str, raw: str, image_w: int = 0, image_h: int = 0):
    """Диспетчер: сырой ответ движка → [(полигон, текст)] (для glm_ocr — [str])."""
    if engine_id == "hunyuan_ocr":
        return parse_hunyuan_spotting(raw, image_w, image_h)
    if engine_id == "dots_ocr":
        return parse_dotsocr(raw, image_w, image_h)
    if engine_id == "unlimited_ocr":
        return parse_unlimited_ocr(raw, image_w, image_h)
    if engine_id == "paddleocr_vl":
        return parse_paddleocr_vl(raw, image_w, image_h)
    if engine_id == "glm_ocr":
        return parse_glm_ocr(raw)
    return []
