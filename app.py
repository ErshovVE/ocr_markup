import os

import streamlit as st

from src.annotations import AnnotationManager
from src.ui.editor_view import render_image_editor
from src.ui.list_view import render_image_list
from src.ui.sidebar import render_sidebar

st.set_page_config(layout="wide", page_title="Инструмент разметки OCR")


def init_session_state():
    """Инициализирует session state"""
    defaults = {
        "manager": None,
        "current_idx": 0,
        "current_page": 0,
        "page_size": 50,  # Уменьшено с 100 до 50
        "filter_option": "all",
        "unsaved_changes": 0,
        "confirm_delete": None,
        "show_backups": False,
        "hotkey_trigger": 0,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def check_hotkeys():
    """Проверяет нажатие горячих клавиш через query params"""
    # Альтернативный метод через session storage и query params
    pass


def main():
    # Компактный CSS
    st.markdown(
        """
        <style>
        [data-testid="stStatusWidget"], header {visibility: hidden;}
        .block-container {padding-top: 1.5rem; padding-bottom: 0.5rem;}
        img {border: 2px solid #4CAF50; box-shadow: 2px 2px 5px rgba(0,0,0,0.2);}
        .stButton button {padding: 0.25rem 0.5rem; font-size: 0.9rem;}
        h1 {margin-bottom: 0.5rem; font-size: 1.8rem;}
        h2 {margin-top: 0.5rem; margin-bottom: 0.5rem; font-size: 1.3rem;}
        h3 {margin-top: 0.3rem; margin-bottom: 0.3rem; font-size: 1.1rem;}
        </style>
    """,
        unsafe_allow_html=True,
    )

    st.title("🖼️ OCR Разметка")

    init_session_state()

    # Загрузка файла
    uploaded_file = st.file_uploader("Загрузите файл разметки (.txt)", type=["txt"])

    if uploaded_file:
        # Путь к рабочей директории
        working_dir = st.text_input(
            "Укажите рабочую директорию", placeholder="Например: G:/Датасет"
        )

        if not working_dir:
            st.warning("Укажите рабочую директорию")
            return

        if not os.path.isdir(working_dir):
            st.error("Указанная директория не существует")
            return

        # Инициализация менеджера
        if st.session_state.manager is None:
            annotation_file = os.path.join(working_dir, uploaded_file.name)
            st.session_state.manager = AnnotationManager(working_dir, annotation_file)

            file_contents = uploaded_file.read().decode("utf-8")
            success, error = st.session_state.manager.load_from_file(file_contents)

            if not success:
                st.error(error)
                return

        manager = st.session_state.manager

        # Получаем отфильтрованный список
        filtered = manager.get_image_list(st.session_state.filter_option)

        if not filtered:
            st.warning("Нет изображений по выбранному фильтру")

            # Позволяем изменить фильтр
            filter_opts = {
                "all": "Все",
                "unmarked": "Неразмеченные",
                "marked": "Размеченные",
            }
            st.radio("Показать:", list(filter_opts.values()), key="empty_filter")
            return

        # Основной интерфейс
        col1, col2 = st.columns([1, 2])

        with col1:
            render_image_list(manager, filtered)

        with col2:
            render_image_editor(manager)

        # Сайдбар - Статистика и управление бэкапами
        render_sidebar(manager)


if __name__ == "__main__":
    main()
