import streamlit as st

from src.i18n import render_language_switch, t
from src.ui.generation_view import render_generation_mode
from src.ui.manual_mode import render_manual_mode

st.set_page_config(layout="wide", page_title="OCR Markup / Разметка OCR")


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
        "app_mode": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def check_hotkeys():
    """Проверяет нажатие горячих клавиш через query params"""
    # Альтернативный метод через session storage и query params
    pass


def render_mode_landing():
    """Отрисовывает стартовый экран с выбором режима работы"""
    st.subheader(t("mode_landing_subheader"))
    col1, col2 = st.columns(2)
    with col1:
        if st.button(t("mode_generation_btn"), use_container_width=True):
            st.session_state.app_mode = "generation"
            st.rerun()
    with col2:
        if st.button(t("mode_manual_btn"), use_container_width=True):
            st.session_state.app_mode = "manual"
            st.rerun()


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

    init_session_state()
    render_language_switch()

    st.title(t("app_title"))

    if st.session_state.app_mode is None:
        render_mode_landing()
        return

    if st.button(t("switch_mode_btn"), key="switch_mode"):
        st.session_state.app_mode = None
        st.rerun()

    if st.session_state.app_mode == "generation":
        render_generation_mode()
    else:
        render_manual_mode()


if __name__ == "__main__":
    main()
