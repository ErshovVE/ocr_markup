"""Текст меток датасета: нормализация символов и проверка по словарю модели.

Общий источник правил для обоих генераторов датасета: этот пайплайн
(`normalize_labels` / `alphabet_file` в POST /run) и балансировщик
doc-generator (импортирует модуль из ocr_markup так же, как pdf_extract), —
чтобы одна и та же картинка не получала разные метки.

Нормализация меняет только метку, не картинку: модель учится читать
типографские варианты как один символ словаря.
"""

from typing import FrozenSet, List

# Среднее тире -> длинное (в русском Word «пробел-дефис-пробел» автозаменяется
# на среднее); все двойные типографские кавычки -> «"»; одинарные и апостроф ’ ->
# «'» (иначе «don’t» стало бы «don"t»). Ёлочки «» в словаре — остаются.
LABEL_NORMALIZATION = str.maketrans(
    {
        "–": "—",
        "“": '"',
        "”": '"',
        "„": '"',
        "‟": '"',
        "‘": "'",
        "’": "'",
        "‚": "'",
        "‛": "'",
    }
)


def normalize_label(text: str) -> str:
    """Метка с типографскими вариантами, заменёнными на символы словаря."""
    return text.translate(LABEL_NORMALIZATION)


def load_alphabet(path: str) -> FrozenSet[str]:
    """Словарь модели: по символу на строку (как ppocr/utils/dict/*.txt).
    Пробел допустим всегда (в PaddleOCR его добавляет use_space_char)."""
    with open(path, encoding="utf-8") as f:
        chars = {line.rstrip("\r\n") for line in f}
    chars.discard("")
    longer = sorted(c for c in chars if len(c) != 1)
    if longer:
        raise ValueError(
            f"{path}: в словаре должно быть по одному символу на строку, есть {longer[:5]}"
        )
    if not chars:
        raise ValueError(f"{path}: словарь пуст")
    return frozenset(chars | {" "})


def out_of_alphabet(text: str, alphabet: FrozenSet[str]) -> List[str]:
    """Символы метки, которых нет в словаре (по одному разу, в порядке появления)."""
    seen: List[str] = []
    for char in text:
        if char not in alphabet and char not in seen:
            seen.append(char)
    return seen
