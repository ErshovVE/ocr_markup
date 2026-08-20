import os

import streamlit as st

from src.annotations import AnnotationManager
from src.ui.editor_view import render_image_editor
from src.ui.list_view import render_image_list
from src.ui.sidebar import render_sidebar


def render_manual_mode():
    """Отрисовывает режим ручной разметки: загрузка файла + список/редактор/сайдбар"""
    if st.session_state.manager is None:
        uploaded_file = st.file_uploader("Загрузите файл разметки (.txt)", type=["txt"])
        if not uploaded_file:
            return

        working_dir = st.text_input(
            "Укажите рабочую директорию", placeholder="Например: /data/Датасет"
        )

        if not working_dir:
            st.warning("Укажите рабочую директорию")
            return

        if not os.path.isdir(working_dir):
            st.error("Указанная директория не существует")
            return

        annotation_file = os.path.join(working_dir, uploaded_file.name)
        manager = AnnotationManager(working_dir, annotation_file)

        file_contents = uploaded_file.read().decode("utf-8")
        success, error = manager.load_from_file(file_contents)

        if not success:
            st.error(error)
            return

        st.session_state.manager = manager

    manager = st.session_state.manager

    filtered = manager.get_image_list(st.session_state.filter_option)

    if not filtered:
        st.warning("Нет изображений по выбранному фильтру")

        filter_opts = {
            "all": "Все",
            "unmarked": "Неразмеченные",
            "marked": "Размеченные",
        }
        st.radio("Показать:", list(filter_opts.values()), key="empty_filter")
        return

    col1, col2 = st.columns([1, 2])

    with col1:
        render_image_list(manager, filtered)

    with col2:
        render_image_editor(manager)

    render_sidebar(manager)
