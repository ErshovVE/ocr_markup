import os

import streamlit as st
from PIL import Image

# Потолок против decompression-bomb: крафтовая огромная картинка из
# произвольной папки иначе раздувает память при декоде. За 2× порога PIL
# сам кидает Image.DecompressionBombError (ловится вызывающими try/except).
Image.MAX_IMAGE_PIXELS = 64_000_000


@st.cache_data
def load_and_resize_image(
    image_path: str, max_height: int = 100, max_width: int = 1000
):
    """Загружает и изменяет размер изображения с кэшированием"""
    try:
        image = Image.open(image_path).convert("RGB")
        w, h = image.size

        scale = min(max_height / h, max_width / w)
        new_w, new_h = int(w * scale), int(h * scale)

        return image.resize((new_w, new_h), Image.Resampling.LANCZOS)
    except Exception as e:
        st.error(f"Ошибка загрузки изображения: {e}")
        return None


# NOTE: load_and_resize_image.clear() only works because both functions live
# in this module — see docs/architecture.md
def rotate_image(image_path: str, direction: str) -> bool:
    """Поворачивает изображение на 90 градусов.

    Пишет во временный файл рядом и атомарно подменяет оригинал — на Windows
    Image.open держит хендл лениво, и save() в тот же путь периодически падал
    PermissionError, оставляя единственную копию картинки битой (бэкапа, в
    отличие от правок аннотаций, здесь нет).
    """
    base, ext = os.path.splitext(image_path)
    tmp_path = f"{base}.rot.tmp{ext}"  # тот же ext — PIL сам выберет формат по нему
    try:
        with Image.open(image_path) as image:
            image.load()
            angle = -90 if direction == "right" else 90
            rotated = image.rotate(angle, expand=True)
        rotated.save(tmp_path)
        os.replace(tmp_path, image_path)
        load_and_resize_image.clear()
        return True
    except Exception as e:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        st.error(f"Ошибка поворота: {e}")
        return False
