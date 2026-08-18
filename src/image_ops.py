import streamlit as st
from PIL import Image


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


# NOTE: load_and_resize_image.clear() only works because both functions live in this module — see docs/architecture.md
def rotate_image(image_path: str, direction: str) -> bool:
    """Поворачивает изображение на 90 градусов"""
    try:
        image = Image.open(image_path)
        angle = -90 if direction == "right" else 90
        rotated = image.rotate(angle, expand=True)
        rotated.save(image_path)
        load_and_resize_image.clear()
        return True
    except Exception as e:
        st.error(f"Ошибка поворота: {e}")
        return False
