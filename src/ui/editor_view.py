import streamlit as st

from src.annotations import AnnotationManager, save_as_handwritten
from src.hotkeys import register_hotkeys
from src.image_ops import load_and_resize_image, rotate_image


def _render_delete_confirm(manager: AnnotationManager, current_name: str) -> bool:
    """Отрисовывает модальное окно подтверждения удаления. Возвращает True, если окно показано."""
    if st.session_state.confirm_delete != current_name:
        return False

    st.error(f"⚠️ Удалить **{current_name}**?")

    col_confirm1, col_confirm2 = st.columns(2)
    with col_confirm1:
        if st.button(
            "✓ Да",
            type="primary",
            key=f"delete_confirm_{current_name}",
            use_container_width=True,
        ):
            if manager.delete_record(current_name, create_backup=True):
                manager.save_changes(create_backup=False)
                st.success("✓ Удалено, бэкап создан")
                st.session_state.confirm_delete = None
                st.rerun()
    with col_confirm2:
        if st.button(
            "✗ Отмена",
            key=f"delete_cancel_{current_name}",
            use_container_width=True,
        ):
            st.session_state.confirm_delete = None
            st.rerun()
    return True


def _render_edit_form(manager: AnnotationManager, current_name: str, record, img_names):
    """Отрисовывает форму редактирования текста аннотации"""
    with st.form(key=f"form_{current_name}"):
        text_value = st.text_area(
            "Текст:", value=record.annotation, key=f"input_{current_name}", height=80
        )

        col1, col2 = st.columns(2)
        with col1:
            submit = st.form_submit_button(
                "✓ Подтвердить", use_container_width=True, type="primary"
            )
        with col2:
            handwritten = st.form_submit_button(
                "✍ Рукописный", use_container_width=True
            )

        if submit:
            clean_text = text_value.replace("\n", " ").replace("\r", " ").strip()
            manager.update_annotation(current_name, clean_text)
            st.session_state.unsaved_changes += 1

            # Автосохранение каждые 10 изменений
            if st.session_state.unsaved_changes >= 10:
                success, msg = manager.save_changes()
                if success:
                    st.session_state.unsaved_changes = 0
                    st.success("💾 Автосохранение")
            else:
                st.success(f"✓ В памяти ({st.session_state.unsaved_changes})")

            # Переход к следующему
            if st.session_state.current_idx < len(img_names) - 1:
                st.session_state.current_idx += 1
            st.rerun()

        if handwritten:
            clean_text = text_value.replace("\n", " ").replace("\r", " ").strip()
            if save_as_handwritten(manager, current_name, clean_text):
                st.success("✓ Сохранено")


def _render_action_buttons(manager: AnnotationManager, record, current_name: str, img_names):
    """Отрисовывает кнопки действий: удаление, поворот, навигация"""
    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        if st.button(
            "🗑️",
            use_container_width=True,
            key=f"delete_btn_{current_name}",
            help="Удалить",
        ):
            st.session_state.confirm_delete = current_name
            st.rerun()

    with col2:
        if st.button(
            "↶",
            use_container_width=True,
            key=f"rotate_left_{current_name}",
            help="Повернуть влево",
        ):
            if rotate_image(record.absolute_path, "left"):
                st.rerun()

    with col3:
        if st.button(
            "↷",
            use_container_width=True,
            key=f"rotate_right_{current_name}",
            help="Повернуть вправо",
        ):
            if rotate_image(record.absolute_path, "right"):
                st.rerun()

    with col4:
        prev_disabled = st.session_state.current_idx == 0
        if st.button(
            "←",
            use_container_width=True,
            disabled=prev_disabled,
            key=f"prev_{current_name}",
            help="Предыдущее изображение",
        ):
            st.session_state.current_idx -= 1
            st.rerun()

    with col5:
        next_disabled = st.session_state.current_idx >= len(img_names) - 1
        if st.button(
            "→",
            use_container_width=True,
            disabled=next_disabled,
            key=f"next_{current_name}",
            help="Следующее изображение",
        ):
            st.session_state.current_idx += 1
            st.rerun()


def _render_unsaved_banner(manager: AnnotationManager, current_name: str):
    """Отрисовывает индикатор несохраненных изменений с кнопкой сохранения"""
    if st.session_state.unsaved_changes <= 0:
        return

    col_warn, col_save = st.columns([2, 1])
    with col_warn:
        st.caption(f"⚠️ Несохранено: {st.session_state.unsaved_changes}")
    with col_save:
        if st.button(
            "💾 Сохранить",
            type="primary",
            key=f"save_now_{current_name}",
            use_container_width=True,
        ):
            success, msg = manager.save_changes()
            if success:
                st.session_state.unsaved_changes = 0
                st.success("✓")
                st.rerun()


def render_image_editor(manager: AnnotationManager):
    """Отрисовывает редактор изображения"""
    if not manager.records:
        st.warning("Нет изображений для редактирования")
        return

    # Получаем текущее изображение
    img_names = list(manager.records.keys())
    if st.session_state.current_idx >= len(img_names):
        st.session_state.current_idx = len(img_names) - 1

    current_name = img_names[st.session_state.current_idx]
    record = manager.records[current_name]

    st.subheader(f"📷 {current_name}")

    # Отображение изображения
    image = load_and_resize_image(record.absolute_path, max_height=80, max_width=1200)
    if image:
        st.image(image)

    # Модальное окно подтверждения удаления
    if _render_delete_confirm(manager, current_name):
        return

    # Форма редактирования
    _render_edit_form(manager, current_name, record, img_names)

    # Компактные действия
    _render_action_buttons(manager, record, current_name, img_names)

    # Компактный индикатор несохраненных изменений
    _render_unsaved_banner(manager, current_name)

    # Компактная подсказка
    st.caption("💡 **← →** для навигации")

    # Встраиваем обработчик горячих клавиш
    register_hotkeys()
