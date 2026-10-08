"""Промпты и парсеры ответов VLM: сырой ответ модели → [(полигон, текст)].

Две стратегии (backend/config.py::VLM_ENGINE_META["box_strategy"]):
  - native — модель сама отдаёт строки с боксами по всей странице:
      paddleocr_vl — PaddleOCR-VL 1.6, "Spotting:": ``<|TEXT_START|>текст
                     <|TEXT_END|><|LOC_BEGIN|><|LOC_x|>…×8<|LOC_END|>``,
                     4 точки в [0, 1000] (порт PaddleX paddleocr_vl/uilts.py::
                     post_process_for_spotting)
      hunyuan_ocr  — spotting: строки ``текст(x1,y1),(x2,y2)`` в [0, 1000]
                     (HunyuanOCR_v1.0/infer/utils.py::denormalize_coordinates)
  - layout — модель читает текст одной строки-кропа, боксы даёт детектор
    строк (backend/vlm_layout.py): glm_ocr, dots_ocr, unlimited_ocr; ответ
    разбирает parse_region_text.

Паттерн — как у backend/recognizers.py: узкая функция, свои исключения не
пробрасывает, на битом/пустом ответе возвращает ``[]``, а не падает.
"""

import logging
import re
from typing import List, Tuple

from backend.vlm_geometry import Polygon, rect_polygon

logger = logging.getLogger(__name__)

# Промпты — дословно официальные: модели обучены на фиксированных инструкциях,
# и перефразированный промпт (английский перевод, «верни JSON с bbox») даёт
# другой формат ответа или его отсутствие.
#   paddleocr_vl  — карточка PaddlePaddle/PaddleOCR-VL-1.6: "Spotting:" (строки+боксы)
#   hunyuan_ocr   — Tencent-Hunyuan/HunyuanOCR inference/utils/tasks.py, spotting_hunyuan
#   glm_ocr       — ollama.com/library/glm-ocr: "Text Recognition:"
#   dots_ocr      — rednote-hilab/dots.ocr dots_ocr/utils/prompts.py, prompt_ocr
#                   (построчного режима у dots.ocr нет: prompt_layout_all_en даёт
#                   абзацы/таблицы, поэтому — кроп строки от детектора + prompt_ocr)
#   unlimited_ocr — карточка GGUF (промпты линейки DeepSeek-OCR): "Free OCR." —
#                   только текст; режим с боксами (<|grounding|>) опирается на
#                   спецтокены <|ref|>/<|det|>, которые сервер вырезает из ответа
PROMPTS = {
    "paddleocr_vl": "Spotting:",
    "hunyuan_ocr": "检测并识别图片中的文字，将文本坐标格式化输出。",
    "glm_ocr": "Text Recognition:",
    "dots_ocr": "Extract the text content from this image.",
    "unlimited_ocr": "Free OCR.",
}

# Промпты движка "vlm_line" консенсуса (backend/recognizers.py::
# recognize_vlm_line_batch): модель читает одну строку-кроп. Layout-движки —
# те же промпты, что выше; PaddleOCR-VL — "OCR:" (задача распознавания из
# карточки модели, не Spotting). "OCR:" проверить на живой модели перед
# прогоном: если ответ — Spotting-разметка, убрать paddleocr_vl из
# backend/config.py::LINE_VLM_ENGINES.
LINE_PROMPTS = {
    "glm_ocr": PROMPTS["glm_ocr"],
    "dots_ocr": PROMPTS["dots_ocr"],
    "unlimited_ocr": PROMPTS["unlimited_ocr"],
    "paddleocr_vl": "OCR:",
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
    r"\mu": "μ",  # U+03BC GREEK SMALL LETTER MU (не U+00B5 MICRO SIGN)
    r"\Omega": "Ω",
}
# Замена макросов только когда за ними НЕ идёт буква — иначе "\pi" схлопнул бы
# начало "\piecewise". Ключи отсортированы по убыванию длины, чтобы "\rightarrow"
# матчился раньше "\right"-подобных префиксов.
_LATEX_RE = re.compile(
    "(?:"
    + "|".join(re.escape(m) for m in sorted(_LATEX_UNICODE, key=len, reverse=True))
    + r")(?![a-zA-Z])"
)

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
    cleaned = _LATEX_RE.sub(lambda m: _LATEX_UNICODE[m.group(0)], cleaned)
    cleaned = _WS_RE.sub(" ", cleaned)
    return cleaned.strip()


# Координаты обоих native-движков нормированы к [0, 1000] относительно
# картинки, ушедшей в модель, — поэтому не зависят от её масштаба (даунскейл
# страницы, апскейл ×2 для Spotting) и переводятся в пиксели страницы image_w×image_h.


def _permille_to_px(value: float, axis_size: int) -> float:
    """Промилле (0..1000) → пиксели по размеру оси. Без размера — как есть."""
    if axis_size <= 0:
        return value
    return value / 1000.0 * axis_size


_PVL_TEXT_RE = re.compile(r"<\|TEXT_START\|>(.*?)<\|TEXT_END\|>", re.S)
_PVL_LOC_BLOCK_RE = re.compile(r"<\|LOC_BEGIN\|>(.*?)<\|LOC_END\|>", re.S)
_PVL_LOC_RE = re.compile(r"<\|LOC_(\d+)\|>")
_PVL_MARKER_RE = re.compile(r"<\|(?:TEXT_START|TEXT_END|LOC_BEGIN|LOC_END)\|>")


def parse_paddleocr_vl_spotting(
    raw: str, image_w: int = 0, image_h: int = 0
) -> List[Tuple[Polygon, str]]:
    """PaddleOCR-VL 1.6 "Spotting:" → строки с осевым bbox по 4 точкам.

    Основной формат — пары блоков ``<|TEXT_START|>…<|TEXT_END|>`` и
    ``<|LOC_BEGIN|>…<|LOC_END|>``. LOC_BEGIN/LOC_END в токенизаторе помечены
    special (TEXT_*/LOC_n — нет), и OpenAI-совместимый сервер может их вырезать —
    тогда, как и PaddleX, режем поток на группы по 8 токенов <|LOC_n|>, а
    текстом строки считаем кусок перед группой."""
    raw = raw or ""
    pairs: List[Tuple[str, List[int]]] = []
    for text, block in zip(_PVL_TEXT_RE.findall(raw), _PVL_LOC_BLOCK_RE.findall(raw), strict=False):
        values = [int(v) for v in _PVL_LOC_RE.findall(block)]
        if len(values) >= 8:
            pairs.append((text, values[:8]))
    if not pairs:
        matches = list(_PVL_LOC_RE.finditer(raw))
        last_end = 0
        for start in range(0, len(matches) - 7, 8):
            group = matches[start : start + 8]
            text = _PVL_MARKER_RE.sub("", raw[last_end : group[0].start()])
            pairs.append((text, [int(m.group(1)) for m in group]))
            last_end = group[-1].end()

    lines: List[Tuple[Polygon, str]] = []
    for text, values in pairs:
        text = text.strip()
        if not text:
            continue
        xs = [_permille_to_px(v, image_w) for v in values[0::2]]
        ys = [_permille_to_px(v, image_h) for v in values[1::2]]
        lines.append((rect_polygon(min(xs), min(ys), max(xs), max(ys)), text))
    return lines


_HUNYUAN_RE = re.compile(
    r"([^\n]+?)\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)\s*,\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)"
)


def parse_hunyuan_spotting(
    raw: str, image_w: int = 0, image_h: int = 0
) -> List[Tuple[Polygon, str]]:
    """HunyuanOCR text spotting: строки ``текст(x1,y1),(x2,y2)`` с координатами
    в [0, 1000] — приводим к пикселям страницы image_w×image_h."""
    lines: List[Tuple[Polygon, str]] = []
    for match in _HUNYUAN_RE.finditer(raw or ""):
        text = match.group(1).strip()
        if not text:
            continue
        x1 = _permille_to_px(float(match.group(2)), image_w)
        y1 = _permille_to_px(float(match.group(3)), image_h)
        x2 = _permille_to_px(float(match.group(4)), image_w)
        y2 = _permille_to_px(float(match.group(5)), image_h)
        lines.append((rect_polygon(x1, y1, x2, y2), text))
    return lines


def parse_region_text(raw: str) -> List[str]:
    """Ответ layout-движка (GLM-OCR, dots.ocr, Unlimited-OCR) на одну строку-кроп —
    только текст, без боксов (их даёт backend/vlm_layout.py): список непустых строк."""
    cleaned = postprocess_text(raw)
    return [line.strip() for line in cleaned.splitlines() if line.strip()]


def parse_line_text(raw: str) -> str:
    """Ответ VLM на одну строку-кроп → один текст: строки ответа через пробел
    (модель иногда переносит длинную строку), пустой/битый ответ → ""."""
    try:
        return " ".join(parse_region_text(raw))
    except Exception as e:  # noqa: BLE001 — как parse()
        logger.warning("Ошибка парсера строки VLM: %s", e)
        return ""


_NATIVE_PARSERS = {
    "paddleocr_vl": parse_paddleocr_vl_spotting,
    "hunyuan_ocr": parse_hunyuan_spotting,
}
_LAYOUT_ENGINES = ("glm_ocr", "dots_ocr", "unlimited_ocr")


def parse(engine_id: str, raw: str, image_w: int = 0, image_h: int = 0):
    """Диспетчер: сырой ответ движка → [(полигон, текст)] для native-движков;
    для layout-движков — [str] (см. parse_region_text).

    Последний рубеж: любую неожиданную ошибку парсера гасим в ``[]`` + лог
    (как recognize_* в backend/recognizers.py) — битый ответ модели не должен
    ронять страницу/весь job (см. backend/pipeline_vlm.py)."""
    try:
        if engine_id in _NATIVE_PARSERS:
            return _NATIVE_PARSERS[engine_id](raw, image_w, image_h)
        if engine_id in _LAYOUT_ENGINES:
            return parse_region_text(raw)
    except Exception as e:  # noqa: BLE001
        logger.warning("Ошибка парсера VLM %s: %s", engine_id, e)
        return []
    return []
