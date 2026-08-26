import streamlit as st

from src.annotations import AnnotationManager, save_as_handwritten
from src.hotkeys import register_hotkeys
from src.i18n import t
from src.image_ops import load_and_resize_image, rotate_image


def _render_delete_confirm(manager: AnnotationManager, current_name: str) -> bool:
    """Отрисовывает модальное окно подтверждения удаления. Возвращает True, если окно показано."""
    if st.session_state.confirm_delete != current_name:
        return False

    st.error(t("confirm_delete_msg", name=current_name))

    col_confirm1, col_confirm2 = st.columns(2)
    with col_confirm1:
        if st.button(
            t("yes_btn"),
            type="primary",
            key=f"delete_confirm_{current_name}",
            use_container_width=True,
        ):
            if manager.delete_record(current_name, create_backup=True):
                manager.save_changes(create_backup=False)
                st.success(t("deleted_success"))
                st.session_state.confirm_delete = None
                st.rerun()
    with col_confirm2:
        if st.button(
            t("cancel_btn"),
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
            t("text_label"), value=record.annotation, key=f"input_{current_name}", height=80
        )

        col1, col2 = st.columns(2)
        with col1:
            submit = st.form_submit_button(
                t("confirm_btn"), use_container_width=True, type="primary"
            )
        with col2:
            handwritten = st.form_submit_button(
                t("handwritten_btn"), use_container_width=True
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
                    st.success(t("autosave_msg"))
            else:
                st.success(t("in_memory_msg", count=st.session_state.unsaved_changes))

            # Переход к следующему
            if st.session_state.current_idx < len(img_names) - 1:
                st.session_state.current_idx += 1
            st.rerun()

        if handwritten:
            clean_text = text_value.replace("\n", " ").replace("\r", " ").strip()
            if save_as_handwritten(manager, current_name, clean_text):
                st.success(t("saved_msg"))


def _render_action_buttons(manager: AnnotationManager, record, current_name: str, img_names):
    """Отрисовывает кнопки действий: удаление, поворот, навигация"""
    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        if st.button(
            "🗑️",
            use_container_width=True,
            key=f"delete_btn_{current_name}",
            help=t("delete_help"),
        ):
            st.session_state.confirm_delete = current_name
            st.rerun()

    with col2:
        if st.button(
            "↶",
            use_container_width=True,
            key=f"rotate_left_{current_name}",
            help=t("rotate_left_help"),
        ):
            if rotate_image(record.absolute_path, "left"):
                st.rerun()

    with col3:
        if st.button(
            "↷",
            use_container_width=True,
            key=f"rotate_right_{current_name}",
            help=t("rotate_right_help"),
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
            help=t("prev_help"),
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
            help=t("next_help"),
        ):
            st.session_state.current_idx += 1
            st.rerun()


def _render_unsaved_banner(manager: AnnotationManager, current_name: str):
    """Отрисовывает индикатор несохраненных изменений с кнопкой сохранения"""
    if st.session_state.unsaved_changes <= 0:
        return

    col_warn, col_save = st.columns([2, 1])
    with col_warn:
        st.caption(t("unsaved_caption", count=st.session_state.unsaved_changes))
    with col_save:
        if st.button(
            t("save_btn"),
            type="primary",
            key=f"save_now_{current_name}",
            use_container_width=True,
        ):
            success, msg = manager.save_changes()
            if success:
                st.session_state.unsaved_changes = 0
                st.success("✓")
                st.rerun()


def _render_engine_details(manager: AnnotationManager, record):
    """Показывает, что видел каждый движок авторазметки — данные из
    debug.jsonl (см. AnnotationManager._load_debug_file). Для чисто ручной
    разметки (без прогона через backend) debug_by_path пуст, и функция
    просто ничего не рисует."""
    debug_record = manager.debug_by_path.get(record.relative_path)
    if not debug_record:
        return

    label = t("engines_seen_label")
    if record.diverged:
        label += t("diverged_suffix")

    with st.expander(label):
        winner = debug_record.get("engine")
        for engine_name, engine_result in debug_record.get("engines", {}).items():
            text = engine_result.get("text", "")
            score = engine_result.get("score", 0.0)
            marker = "🏆 " if engine_name == winner else ""
            st.caption(f"{marker}**{engine_name}** ({score:.2f}): {text or t('empty_placeholder')}")


def render_image_editor(manager: AnnotationManager):
    """Отрисовывает редактор изображения"""
    if not manager.records:
        st.warning(t("no_images_editor"))
        return

    # Получаем текущее изображение
    img_names = list(manager.records.keys())
    if st.session_state.current_idx >= len(img_names):
        st.session_state.current_idx = len(img_names) - 1

    current_name = img_names[st.session_state.current_idx]
    record = manager.records[current_name]

    title = f"📷 {current_name}"
    if record.diverged:
        title += " ⚠️"
    st.subheader(title)

    # Отображение изображения
    image = load_and_resize_image(record.absolute_path, max_height=80, max_width=1200)
    if image:
        st.image(image)

    # Детали авторазметки (что видел каждый движок), если есть debug.jsonl
    _render_engine_details(manager, record)

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
    st.caption(t("nav_hint"))

    # Встраиваем обработчик горячих клавиш
    register_hotkeys()
