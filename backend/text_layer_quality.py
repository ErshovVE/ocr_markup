"""Оценка качества текстового слоя PDF: можно ли ему доверять вместо OCR.

Невидимый текстовый слой сканов — чужое OCR (сканер, FineReader и т.п.). На
машинописи и плохих сканах он часто с ошибками или целиком мусорный, а
pdf_extract без этой проверки доверял бы любому непустому слою. Словаря нет —
проверяется только форма слов: смесь алфавитов, латиница из «кириллических»
букв посреди русского текста ("BATCH" вместо "ВАТСН"), длинные слова без
гласных, посторонние символы, буквы внутри чисел ("19В6").

Чистый Python без зависимостей: используется backend/pdf_extract.py и
скриптом scripts/scrape/stroyinf.py (диагностика скачанных документов).
"""

import re
import statistics
from typing import Dict, List, Optional

CYR = "а-яёА-ЯЁ"
LAT = "A-Za-zÀ-ÖØ-öø-ÿ"
VOWELS = set("аеёиоуыэюяАЕЁИОУЫЭЮЯ")
# Латинские буквы, неотличимые от кириллических (проверяются только на
# страницах с преобладанием кириллицы — в английском тексте это обычные слова).
HOMOGLYPHS = set("ABCEHKMOPTXaceopxy")
_UNIT = r"[а-яё]{1,4}\d?"  # единицы измерения: мм, см2, кгс/см2, т/ч
_CLEAN_WORD = re.compile(
    rf"^([{CYR}]+(-[{CYR}]+)*"  # слова, в т.ч. через дефис
    rf"|{_UNIT}(/{_UNIT})+|[а-яё]{{1,3}}\d"  # единицы измерения
    rf"|[а-яё]{{1,4}}(\.[а-яё]{{1,4}})+"  # сокращения: т.п, т.е
    rf"|[{LAT}]+('[{LAT}]+)?(-[{LAT}]+)*"  # латиница
    r"|\d+([.,:/-]\d+)*|[IVXL]+)$"  # числа, номера пунктов, римские цифры
)
_PUNCT = "«»„“”\"'()[]{}.,;:!?—–-№%°*+=<>/©"
# pdfium отдаёт мягкий перенос («стан\x02дартизации») как \x02, иногда как U+00AD
_SOFT_HYPHENS = str.maketrans("", "", "\x02\u00ad")
_CYR_LETTER = re.compile(rf"[{CYR}]")
_LAT_LETTER = re.compile(rf"[{LAT}]")
MAX_ACRONYM_LEN = 5  # заглавные без гласных до этой длины — аббревиатуры (СССР, ГКНТ)

# Пороги. Калибровка по сканам советских нормативов (files.stroyinf.ru):
# чистый типографский слой 0.98–1.0 на документ, мусорный слой машинописи ~0.65.
GOOD_PAGE_QUALITY = 0.85  # страница с таким качеством слоя — «хорошая»
MIN_GOOD_PAGES_SHARE = 0.8  # столько оценённых страниц должны быть хорошими
MIN_PAGE_WORDS = 5  # на странице с меньшим числом слов качество не оценивается


def word_ok(word: str, cyrillic_text: bool = True) -> bool:
    """Правдоподобно ли слово из текстового слоя (без словаря, только форма)."""
    core = word.translate(_SOFT_HYPHENS).strip(_PUNCT)
    if not core:
        return True
    if not _CLEAN_WORD.match(core):
        return False
    acronym = core.isupper() and len(core) <= MAX_ACRONYM_LEN
    if re.fullmatch(rf"[{CYR}]+", core) and len(core) >= 4 and not acronym:
        if not VOWELS & set(core):
            return False
    return not (cyrillic_text and len(core) >= 2 and set(core) <= HOMOGLYPHS)


def is_cyrillic_text(words: List[str]) -> bool:
    text = "".join(words)
    return len(_CYR_LETTER.findall(text)) > len(_LAT_LETTER.findall(text))


def text_quality(words: List[str]) -> float:
    """Доля символов в правдоподобных словах; 1.0 — всё чисто, 0.0 — пусто."""
    total = sum(len(w) for w in words)
    if not total:
        return 0.0
    cyrillic = is_cyrillic_text(words)
    return sum(len(w) for w in words if word_ok(w, cyrillic)) / total


def page_qualities(pages_words: List[List[str]]) -> List[Optional[float]]:
    """Качество слоя по страницам; None — слов слишком мало, чтобы судить."""
    return [
        round(text_quality(words), 3) if len(words) >= MIN_PAGE_WORDS else None
        for words in pages_words
    ]


def layer_is_trustworthy(qualities: List[Optional[float]]) -> bool:
    """Достаточная доля оценённых страниц хорошая. Нечего оценивать — доверяем
    (короткий текст цифрового PDF не с чем сравнивать)."""
    measured = [q for q in qualities if q is not None]
    if not measured:
        return True
    good = sum(q >= GOOD_PAGE_QUALITY for q in measured)
    return good / len(measured) >= MIN_GOOD_PAGES_SHARE


def diagnose_layer(pages_words: List[List[str]]) -> Dict:
    """Слова по страницам -> сводка по слою документа и рекомендация."""
    qualities = page_qualities(pages_words)
    measured = [q for q in qualities if q is not None]
    has_text = any(pages_words)
    return {
        "pages_without_text": sum(not words for words in pages_words),
        "median_quality": round(statistics.median(measured), 3) if measured else None,
        "good_pages_share": (
            round(sum(q >= GOOD_PAGE_QUALITY for q in measured) / len(measured), 3)
            if measured
            else None
        ),
        "page_quality": qualities,
        "recommend": "text_layer" if has_text and layer_is_trustworthy(qualities) else "ocr",
    }
