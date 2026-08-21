from dataclasses import dataclass


@dataclass
class ImageRecord:
    """Структура данных для одной записи изображения"""

    relative_path: str
    absolute_path: str
    annotation: str
    is_marked: bool = False
    # True, если 2+ движка авторазметки независимо уверены, но разошлись в
    # тексте (см. backend/consensus.py::vote, поле "diverged" в debug.jsonl).
    # Заполняется AnnotationManager при загрузке debug.jsonl, если он есть
    # рядом с рабочей директорией — для ручной разметки без авторазметки
    # всегда остаётся False.
    diverged: bool = False
