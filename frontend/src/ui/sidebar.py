from datetime import datetime

import streamlit as st

from src.annotations import AnnotationManager


def render_sidebar(manager: AnnotationManager):
    """Отрисовывает сайдбар: статистика, сохранение, управление бэкапами"""
    st.sidebar.header("📊 Статистика")
    total = len(manager.records)
    marked = sum(1 for r in manager.records.values() if r.is_marked)
    st.sidebar.metric("Всего", total)
    st.sidebar.metric("Размечено", f"{marked} ({marked * 100 // total if total else 0}%)")
    st.sidebar.metric("Осталось", total - marked)

    st.sidebar.divider()

    # Финальное сохранение
    if st.sidebar.button(
        "💾 Сохранить всё",
        use_container_width=True,
        type="primary",
        key="sidebar_save_all",
    ):
        success, msg = manager.save_changes()
        if success:
            st.session_state.unsaved_changes = 0
            st.sidebar.success("✓ Сохранено")
        else:
            st.sidebar.error(msg)

    # Управление бэкапами
    st.sidebar.divider()
    st.sidebar.header("🗂️ Бэкапы")

    backups = manager.backup_manager.get_backups_list()

    if backups:
        st.sidebar.caption(f"{len(backups)} из {manager.backup_manager.max_backups}")

        if st.sidebar.button(
            "📋",
            use_container_width=True,
            key="show_backups_btn",
            help="Показать/скрыть",
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
                    help="Восстановить",
                ):
                    if manager.backup_manager.restore_backup(
                        backup["file"], manager.annotation_file
                    ):
                        st.sidebar.success("✓ Восстановлено!")
                        st.sidebar.info("Перезагрузите")
                    else:
                        st.sidebar.error("Ошибка")
    else:
        st.sidebar.caption("Нет бэкапов")
