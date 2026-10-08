"""Ключи сравнения текстов движков при голосовании (backend/consensus.py::vote).

Ключ нужен только для группировки голосов: тексты «2 .5 .1» и «2.5.1» — один
голос, если ключ убирает пробелы. В good.txt/needs_review.txt всегда пишется
текст движка-победителя, а не ключ.

  exact      — посимвольно (прежнее поведение vote, ключ не применяется)
  normalized — типографские варианты -> символы словаря (backend/labels.py),
               пробельные серии -> один пробел, «ё» -> «е»
  no_spaces  — normalized без пробелов вообще (лечит «п р и я ти я»/«приятия»)
"""

from typing import Callable, Optional

from backend.labels import normalize_label

VOTE_KEYS = ("exact", "normalized", "no_spaces")
DEFAULT_VOTE_KEY = "exact"


def normalized_key(text: str) -> str:
    """Ключ без различий типографики, лишних пробелов и «ё»/«е»."""
    collapsed = " ".join(normalize_label(text).split())
    return collapsed.replace("ё", "е").replace("Ё", "Е")


def no_spaces_key(text: str) -> str:
    """normalized_key без пробелов: расставленные OCR пробелы не важны."""
    return normalized_key(text).replace(" ", "")


_KEYS = {"normalized": normalized_key, "no_spaces": no_spaces_key}


def vote_key(name: str) -> Optional[Callable[[str], str]]:
    """Функция-ключ по имени; None для "exact" (vote сравнивает как раньше)."""
    if name == "exact":
        return None
    if name not in _KEYS:
        raise ValueError(f"Неизвестный ключ сравнения {name!r}, допустимы {VOTE_KEYS}")
    return _KEYS[name]
