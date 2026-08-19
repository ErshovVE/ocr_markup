from dataclasses import dataclass


@dataclass
class ImageRecord:
    """Структура данных для одной записи изображения"""

    relative_path: str
    absolute_path: str
    annotation: str
    is_marked: bool = False
