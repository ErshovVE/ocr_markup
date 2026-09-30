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
# pdfium отдаёт мягкий перенос («стан\x02дартизации») как \x02, U+FFFE или U+00AD
SOFT_HYPHENS = "\x02\ufffe\u00ad"
_STRIP_SOFT_HYPHENS = str.maketrans("", "", SOFT_HYPHENS)
_CYR_LETTER = re.compile(rf"[{CYR}]")
_LAT_LETTER = re.compile(rf"[{LAT}]")
MAX_ACRONYM_LEN = 5  # заглавные без гласных до этой длины — аббревиатуры (СССР, ГКНТ)
# Столько одиночных букв подряд — текст вразрядку («Н е г а т и в н ы е») или
# обрывки из пятен/печатей: слой разбил строку на буквы, подпись к кропу негодная.
MIN_SPACED_RUN = 3

# Решение «слой или OCR» — постраничное. Калибровка по 16 сканам советских
# нормативов (files.stroyinf.ru): на страницах с оценкой >= 0.98 ошибочных
# строк ~3%, на 0.95–0.98 уже ~12%, ниже 0.9 — ~20%.
PAGE_MIN_QUALITY = 0.98  # страница с таким качеством слоя берётся без OCR
MIN_PAGE_WORDS = 5  # на странице с меньшим числом слов качество не оценивается


def word_ok(word: str, cyrillic_text: bool = True) -> bool:
    """Правдоподобно ли слово из текстового слоя (без словаря, только форма)."""
    core = word.translate(_STRIP_SOFT_HYPHENS).strip(_PUNCT)
    if not core:
        return True
    if not _CLEAN_WORD.match(core):
        return False
    acronym = core.isupper() and len(core) <= MAX_ACRONYM_LEN
    if re.fullmatch(rf"[{CYR}]+", core) and len(core) >= 4 and not acronym:
        if not VOWELS & set(core):
            return False
    if cyrillic_text and _LAT_LETTER.search(core):
        # Посреди русского текста латиница — почти всегда ошибка OCR: слово из
        # «кириллических» латинских букв ("BATCH"), строчные обрывки ("oma",
        # "rfP"), одиночные буквы. Допустимы только заглавные аббревиатуры (ISO).
        return core.isupper() and len(core) >= 2 and not set(core) <= HOMOGLYPHS
    return True


def _single_letter(word: str) -> bool:
    core = word.translate(_STRIP_SOFT_HYPHENS).strip(_PUNCT)
    return len(core) == 1 and core.isalpha()


def spaced_letter_mask(words: List[str]) -> List[bool]:
    """True для слов из серий одиночных букв длиной >= MIN_SPACED_RUN."""
    mask = [False] * len(words)
    start = 0
    while start < len(words):
        end = start
        while end < len(words) and _single_letter(words[end]):
            end += 1
        if end - start >= MIN_SPACED_RUN:
            mask[start:end] = [True] * (end - start)
        start = max(end, start + 1)
    return mask


def is_cyrillic_text(words: List[str]) -> bool:
    text = "".join(words)
    return len(_CYR_LETTER.findall(text)) > len(_LAT_LETTER.findall(text))


def text_quality(words: List[str]) -> float:
    """Доля символов в правдоподобных словах; 1.0 — всё чисто, 0.0 — пусто."""
    total = sum(len(w) for w in words)
    if not total:
        return 0.0
    cyrillic = is_cyrillic_text(words)
    spaced = spaced_letter_mask(words)
    good = sum(len(w) for w, s in zip(words, spaced, strict=True) if not s and word_ok(w, cyrillic))
    return good / total


def page_qualities(pages_words: List[List[str]]) -> List[Optional[float]]:
    """Качество слоя по страницам; None — слов слишком мало, чтобы судить."""
    return [
        round(text_quality(words), 3) if len(words) >= MIN_PAGE_WORDS else None
        for words in pages_words
    ]


def page_is_usable(words: List[str]) -> bool:
    """Можно ли взять текстовый слой страницы вместо OCR. Слов слишком мало,
    чтобы оценить (короткий текст цифрового PDF), — берём, если текст есть."""
    if not words:
        return False
    if len(words) < MIN_PAGE_WORDS:
        return True
    return text_quality(words) >= PAGE_MIN_QUALITY


def diagnose_layer(pages_words: List[List[str]]) -> Dict:
    """Слова по страницам -> сводка по слою документа. recommend: "text_layer" —
    слой годится на всех страницах с текстом, "ocr" — ни на одной, "mixed" —
    часть страниц пойдёт через OCR (backend решает постранично)."""
    qualities = page_qualities(pages_words)
    measured = [q for q in qualities if q is not None]
    with_text = [words for words in pages_words if words]
    usable = sum(page_is_usable(words) for words in with_text)
    if with_text and usable == len(with_text):
        recommend = "text_layer"
    elif usable:
        recommend = "mixed"
    else:
        recommend = "ocr"
    return {
        "pages_without_text": len(pages_words) - len(with_text),
        "usable_pages": usable,
        "median_quality": round(statistics.median(measured), 3) if measured else None,
        "page_quality": qualities,
        "recommend": recommend,
    }
