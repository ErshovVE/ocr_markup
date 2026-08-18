from typing import List

import streamlit as st

from src.annotations import AnnotationManager


def render_image_list(manager: AnnotationManager, filtered_images: List[str]):
    """Отрисовывает список изображений с пагинацией"""
    st.subheader("Список изображений")

    # Фильтр
    filter_options = {
        "all": "Все",
        "unmarked": "Неразмеченные",
        "marked": "Размеченные",
    }

    selected = st.radio(
        "Показать:",
        list(filter_options.values()),
        index=list(filter_options.keys()).index(st.session_state.filter_option),
        key="filter_radio",
        horizontal=True,
    )

    new_filter = list(filter_options.keys())[
        list(filter_options.values()).index(selected)
    ]
    if new_filter != st.session_state.filter_option:
        st.session_state.filter_option = new_filter
        st.session_state.current_page = 0
        st.session_state.current_idx = 0
        st.rerun()

    # Пагинация
    total = len(filtered_images)
    total_pages = max(
        1, (total + st.session_state.page_size - 1) // st.session_state.page_size
    )

    if st.session_state.current_page >= total_pages:
        st.session_state.current_page = total_pages - 1

    start = st.session_state.current_page * st.session_state.page_size
    end = min(start + st.session_state.page_size, total)

    # Список
    with st.container(height=350):
        for i, img_name in enumerate(filtered_images[start:end]):
            record = manager.records[img_name]
            status = "✅" if record.is_marked else "❓"
            display = f"{status} {img_name}"

            # Находим глобальный индекс
            global_idx = list(manager.records.keys()).index(img_name)

            if global_idx == st.session_state.current_idx:
                st.markdown(f"**→ {display}**")
            else:
                if st.button(
                    display, key=f"img_{global_idx}", use_container_width=True
                ):
                    st.session_state.current_idx = global_idx
                    st.rerun()

    # Компактные кнопки пагинации
    col1, col2, col3 = st.columns([1, 2, 1])
    with col1:
        if st.button(
            "◀",
            disabled=st.session_state.current_page == 0,
            key="prev_page_btn",
            use_container_width=True,
        ):
            st.session_state.current_page -= 1
            st.rerun()
    with col2:
        st.markdown(
            f"<center>{st.session_state.current_page + 1} / {total_pages}</center>",
            unsafe_allow_html=True,
        )
    with col3:
        if st.button(
            "▶",
            disabled=st.session_state.current_page == total_pages - 1,
            key="next_page_btn",
            use_container_width=True,
        ):
            st.session_state.current_page += 1
            st.rerun()
