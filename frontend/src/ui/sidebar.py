from datetime import datetime

import streamlit as st

from src.annotations import AnnotationManager
from src.i18n import t


def render_sidebar(manager: AnnotationManager):
    """Отрисовывает сайдбар: статистика, сохранение, управление бэкапами"""
    st.sidebar.header(t("stats_header"))
    total = len(manager.records)
    marked = sum(1 for r in manager.records.values() if r.is_marked)
    st.sidebar.metric(t("total_label"), total)
    st.sidebar.metric(
        t("marked_label"), f"{marked} ({marked * 100 // total if total else 0}%)"
    )
    st.sidebar.metric(t("remaining_label"), total - marked)

    st.sidebar.divider()

    # Финальное сохранение
    if st.sidebar.button(
        t("save_all_btn"),
        use_container_width=True,
        type="primary",
        key="sidebar_save_all",
    ):
        success, msg = manager.save_changes()
        if success:
            st.session_state.unsaved_changes = 0
            st.sidebar.success(t("saved_all_msg"))
        else:
            st.sidebar.error(msg)

    # Управление бэкапами
    st.sidebar.divider()
    st.sidebar.header(t("backups_header"))

    backups = manager.backup_manager.get_backups_list()

    if backups:
        st.sidebar.caption(
            t("backups_count", count=len(backups), max=manager.backup_manager.max_backups)
        )

        if st.sidebar.button(
            "📋",
            use_container_width=True,
            key="show_backups_btn",
            help=t("toggle_backups_help"),
        ):
            st.session_state.show_backups = not st.session_state.show_backups

        if st.session_state.show_backups:
            for i, backup in enumerate(backups[:3]):  # Только последние 3
                timestamp_formatted = datetime.strptime(
                    backup["timestamp"], "%Y%m%d_%H%M%S"
                ).strftime("%d.%m %H:%M")

                operation_emoji = {"save": "💾", "delete": "🗑️", "manual": "✋"}.get(
                    backup["operation"], "📝"
                )

                st.sidebar.caption(f"{operation_emoji} {timestamp_formatted}")

                if st.sidebar.button(
                    "↩️",
                    key=f"restore_{i}",
                    use_container_width=True,
                    help=t("restore_help"),
                ):
                    if manager.backup_manager.restore_backup(
                        backup["file"], manager.annotation_file
                    ):
                        st.sidebar.success(t("restored_msg"))
                        st.sidebar.info(t("reload_msg"))
                    else:
                        st.sidebar.error(t("generic_error"))
    else:
        st.sidebar.caption(t("no_backups"))
