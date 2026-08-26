import streamlit as st

LANG_KEY = "lang"
DEFAULT_LANG = "ru"
FLAGS = {"ru": "🇷🇺", "en": "🇬🇧"}

STRINGS = {
    "ru": {
        # app.py
        "page_title": "Инструмент разметки OCR",
        "app_title": "🖼️ OCR Разметка",
        "mode_landing_subheader": "Выберите режим работы",
        "mode_generation_btn": "🤖 Авторазметка",
        "mode_manual_btn": "✍️ Ручная разметка",
        "switch_mode_btn": "🔁 Сменить режим",
        # manual_mode.py
        "upload_label": "Загрузите файл разметки (.txt)",
        "working_dir_label": "Укажите рабочую директорию",
        "working_dir_placeholder": "Например: /data/Датасет",
        "working_dir_warning": "Укажите рабочую директорию",
        "dir_not_exist_error": "Указанная директория не существует",
        "no_images_filter_warning": "Нет изображений по выбранному фильтру",
        "show_label": "Показать:",
        "filter_all": "Все",
        "filter_unmarked": "Неразмеченные",
        "filter_marked": "Размеченные",
        "filter_diverged": "Спорные",
        # list_view.py
        "image_list_header": "Список изображений",
        # editor_view.py
        "no_images_editor": "Нет изображений для редактирования",
        "confirm_delete_msg": "⚠️ Удалить **{name}**?",
        "yes_btn": "✓ Да",
        "cancel_btn": "✗ Отмена",
        "deleted_success": "✓ Удалено, бэкап создан",
        "text_label": "Текст:",
        "confirm_btn": "✓ Подтвердить",
        "handwritten_btn": "✍ Рукописный",
        "autosave_msg": "💾 Автосохранение",
        "in_memory_msg": "✓ В памяти ({count})",
        "saved_msg": "✓ Сохранено",
        "delete_help": "Удалить",
        "rotate_left_help": "Повернуть влево",
        "rotate_right_help": "Повернуть вправо",
        "prev_help": "Предыдущее изображение",
        "next_help": "Следующее изображение",
        "unsaved_caption": "⚠️ Несохранено: {count}",
        "save_btn": "💾 Сохранить",
        "engines_seen_label": "🔍 Что видели движки",
        "diverged_suffix": " · ⚠️ Разошлись",
        "empty_placeholder": "_пусто_",
        "nav_hint": "💡 **← →** для навигации",
        # sidebar.py
        "stats_header": "📊 Статистика",
        "total_label": "Всего",
        "marked_label": "Размечено",
        "remaining_label": "Осталось",
        "save_all_btn": "💾 Сохранить всё",
        "saved_all_msg": "✓ Сохранено",
        "backups_header": "🗂️ Бэкапы",
        "backups_count": "{count} из {max}",
        "toggle_backups_help": "Показать/скрыть",
        "restore_help": "Восстановить",
        "restored_msg": "✓ Восстановлено!",
        "reload_msg": "Перезагрузите",
        "generic_error": "Ошибка",
        "no_backups": "Нет бэкапов",
        # annotations.py / backup.py
        "no_image_files_found": "Не удалось найти файлы изображений",
        "load_error": "Ошибка загрузки: {err}",
        "file_delete_error": "Ошибка удаления файла: {err}",
        "changes_saved": "Изменения сохранены",
        "save_error": "Ошибка сохранения: {err}",
        "backup_created": "📦 Бэкап создан: {name}",
        "handwritten_exists": "Запись уже существует в handwritten.txt",
        "handwritten_save_error": "Ошибка сохранения как рукописный: {err}",
        "backup_create_error": "Ошибка создания бэкапа: {err}",
        "backup_restore_error": "Ошибка восстановления: {err}",
        # generation_view.py
        "gen_header": "🤖 Авторазметка",
        "gen_tab_models": "📦 Модели",
        "gen_tab_run": "▶ Запуск",
        "status_ready": "✅ Готово",
        "status_checking": "⏳ Проверка/скачивание...",
        "status_error": "❌ Ошибка",
        "status_not_checked": "⚪ Не проверено",
        "job_status_running": "⏳ Выполняется",
        "job_status_done": "✅ Готово",
        "job_status_error": "❌ Ошибка",
        "job_status_cancelled": "⏹ Отменено",
        "download_btn": "Скачать",
        "prepare_start_error": "Ошибка запуска подготовки: {err}",
        "backend_unavailable": "Backend недоступен: {err}",
        "engine_col": "**Движок**",
        "recognition_col": "**Распознавание**",
        "detection_col": "**Детекция строк**",
        "refresh_status_btn": "🔄 Обновить статус",
        "go_to_manual_btn": "📥 Перейти к разметке результатов",
        "input_dir_label": "Папка с документами",
        "output_dir_label": "Папка вывода",
        "output_dir_placeholder": "Например: /data/Датасет_результат",
        "detector_engine_label": "Детектор строк текста",
        "confidence_threshold_label": "Порог уверенности",
        "consensus_scheme_label": "Схема сверки движков распознавания",
        "scheme_1_of_1_label": "1 из 1 — один движок",
        "scheme_1_of_1_help": "Прогоняется один выбранный движок. Без сверки — самый "
        "быстрый вариант, но никто не подстрахует, если движок ошибётся.",
        "scheme_1_of_2_label": "1 из 2 — любой из двух уверен",
        "scheme_1_of_2_help": "Прогоняются два движка; строка засчитывается «хорошей», "
        "как только хотя бы один из них уверен в своём ответе — сверять тексты друг "
        "с другом не нужно.",
        "scheme_2_of_2_label": "2 из 2 — оба должны совпасть",
        "scheme_2_of_2_help": "Прогоняются два движка; строка засчитывается «хорошей», "
        "только если оба независимо распознали одинаковый текст.",
        "scheme_2_of_3_label": "2 из 3 — совпадение любых двух (по умолчанию)",
        "scheme_2_of_3_help": "Прогоняются все три движка; достаточно, чтобы любые два "
        "сошлись в тексте. Прежнее поведение — самая надёжная, но и самая медленная схема.",
        "engines_prefix": "Движки: ",
        "engine_select_label": "Движок распознавания",
        "engines_multiselect_label": "Движки распознавания (выберите {count})",
        "preferred_model_label": "Предпочитаемая модель (тай-брейк при разногласии)",
        "extract_pdf_label": "Извлекать текст из PDF напрямую, без OCR (если есть текстовый слой)",
        "run_btn": "▶ Запустить",
        "choose_exact_engines_error": "Выберите ровно {count} движков распознавания для этой схемы",
        "run_started": "Запущено",
        "run_start_error": "Ошибка запуска: {err}",
        "cancel_btn_gen": "⏹ Отменить",
        "cancelling_msg": "Останавливается...",
        "cancel_error": "Ошибка отмены: {err}",
        "check_last_run_btn": "🔍 Проверить статус последнего запуска",
        "no_runs_yet": "Для этой папки вывода ещё не было запусков",
        "check_status_error": "Ошибка проверки: {err}",
        "docs_progress_caption": "{status} · документов {processed} / {found}",
        "lines_total_metric": "Строк всего",
        "good_metric": "Хороших",
        "review_metric": "Плохих",
        "diverged_metric": "Разошедшихся",
        "errors_metric": "Ошибок",
        "errors_timeouts_expander": "⚠️ Ошибки/таймауты ({count})",
        "import_error": "{fname}: {err}",
        "import_general_error": "Ошибка импорта: {err}",
        "no_results_found": "В папке вывода не найдено результатов",
    },
    "en": {
        # app.py
        "page_title": "OCR Markup Tool",
        "app_title": "🖼️ OCR Markup",
        "mode_landing_subheader": "Choose a mode",
        "mode_generation_btn": "🤖 Auto-labeling",
        "mode_manual_btn": "✍️ Manual labeling",
        "switch_mode_btn": "🔁 Switch mode",
        # manual_mode.py
        "upload_label": "Upload an annotation file (.txt)",
        "working_dir_label": "Working directory",
        "working_dir_placeholder": "e.g.: /data/dataset",
        "working_dir_warning": "Specify a working directory",
        "dir_not_exist_error": "The specified directory does not exist",
        "no_images_filter_warning": "No images match the selected filter",
        "show_label": "Show:",
        "filter_all": "All",
        "filter_unmarked": "Unmarked",
        "filter_marked": "Marked",
        "filter_diverged": "Disputed",
        # list_view.py
        "image_list_header": "Image list",
        # editor_view.py
        "no_images_editor": "No images to edit",
        "confirm_delete_msg": "⚠️ Delete **{name}**?",
        "yes_btn": "✓ Yes",
        "cancel_btn": "✗ Cancel",
        "deleted_success": "✓ Deleted, backup created",
        "text_label": "Text:",
        "confirm_btn": "✓ Confirm",
        "handwritten_btn": "✍ Handwritten",
        "autosave_msg": "💾 Autosaved",
        "in_memory_msg": "✓ In memory ({count})",
        "saved_msg": "✓ Saved",
        "delete_help": "Delete",
        "rotate_left_help": "Rotate left",
        "rotate_right_help": "Rotate right",
        "prev_help": "Previous image",
        "next_help": "Next image",
        "unsaved_caption": "⚠️ Unsaved: {count}",
        "save_btn": "💾 Save",
        "engines_seen_label": "🔍 What the engines saw",
        "diverged_suffix": " · ⚠️ Diverged",
        "empty_placeholder": "_empty_",
        "nav_hint": "💡 **← →** to navigate",
        # sidebar.py
        "stats_header": "📊 Stats",
        "total_label": "Total",
        "marked_label": "Marked",
        "remaining_label": "Remaining",
        "save_all_btn": "💾 Save all",
        "saved_all_msg": "✓ Saved",
        "backups_header": "🗂️ Backups",
        "backups_count": "{count} of {max}",
        "toggle_backups_help": "Show/hide",
        "restore_help": "Restore",
        "restored_msg": "✓ Restored!",
        "reload_msg": "Reload the page",
        "generic_error": "Error",
        "no_backups": "No backups",
        # annotations.py / backup.py
        "no_image_files_found": "No image files found",
        "load_error": "Load error: {err}",
        "file_delete_error": "File delete error: {err}",
        "changes_saved": "Changes saved",
        "save_error": "Save error: {err}",
        "backup_created": "📦 Backup created: {name}",
        "handwritten_exists": "Entry already exists in handwritten.txt",
        "handwritten_save_error": "Error saving as handwritten: {err}",
        "backup_create_error": "Error creating backup: {err}",
        "backup_restore_error": "Error restoring backup: {err}",
        # generation_view.py
        "gen_header": "🤖 Auto-labeling",
        "gen_tab_models": "📦 Models",
        "gen_tab_run": "▶ Run",
        "status_ready": "✅ Ready",
        "status_checking": "⏳ Checking/downloading...",
        "status_error": "❌ Error",
        "status_not_checked": "⚪ Not checked",
        "job_status_running": "⏳ Running",
        "job_status_done": "✅ Done",
        "job_status_error": "❌ Error",
        "job_status_cancelled": "⏹ Cancelled",
        "download_btn": "Download",
        "prepare_start_error": "Failed to start preparation: {err}",
        "backend_unavailable": "Backend unavailable: {err}",
        "engine_col": "**Engine**",
        "recognition_col": "**Recognition**",
        "detection_col": "**Line detection**",
        "refresh_status_btn": "🔄 Refresh status",
        "go_to_manual_btn": "📥 Go to labeling results",
        "input_dir_label": "Documents folder",
        "output_dir_label": "Output folder",
        "output_dir_placeholder": "e.g.: /data/dataset_result",
        "detector_engine_label": "Text line detector",
        "confidence_threshold_label": "Confidence threshold",
        "consensus_scheme_label": "Recognition engine consensus scheme",
        "scheme_1_of_1_label": "1 of 1 — single engine",
        "scheme_1_of_1_help": "Runs one selected engine. No cross-check — the fastest option, "
        "but nothing catches it if the engine gets it wrong.",
        "scheme_1_of_2_label": "1 of 2 — either engine confident",
        "scheme_1_of_2_help": "Runs two engines; a line counts as \"good\" as soon as "
        "at least one of them is confident in its answer — texts aren't cross-checked "
        "against each other.",
        "scheme_2_of_2_label": "2 of 2 — both must agree",
        "scheme_2_of_2_help": "Runs two engines; a line counts as \"good\" only if both "
        "independently recognized the same text.",
        "scheme_2_of_3_label": "2 of 3 — any two agree (default)",
        "scheme_2_of_3_help": "Runs all three engines; any two agreeing on the text is enough. "
        "The original behavior — the most reliable, but also the slowest scheme.",
        "engines_prefix": "Engines: ",
        "engine_select_label": "Recognition engine",
        "engines_multiselect_label": "Recognition engines (choose {count})",
        "preferred_model_label": "Preferred model (tie-break on disagreement)",
        "extract_pdf_label": "Extract text from PDF directly, skipping OCR "
        "(if a text layer exists)",
        "run_btn": "▶ Run",
        "choose_exact_engines_error": "Choose exactly {count} recognition engines for this scheme",
        "run_started": "Started",
        "run_start_error": "Failed to start: {err}",
        "cancel_btn_gen": "⏹ Cancel",
        "cancelling_msg": "Stopping...",
        "cancel_error": "Cancel error: {err}",
        "check_last_run_btn": "🔍 Check last run status",
        "no_runs_yet": "No runs yet for this output folder",
        "check_status_error": "Check error: {err}",
        "docs_progress_caption": "{status} · documents {processed} / {found}",
        "lines_total_metric": "Total lines",
        "good_metric": "Good",
        "review_metric": "Needs review",
        "diverged_metric": "Diverged",
        "errors_metric": "Errors",
        "errors_timeouts_expander": "⚠️ Errors/timeouts ({count})",
        "import_error": "{fname}: {err}",
        "import_general_error": "Import error: {err}",
        "no_results_found": "No results found in the output folder",
    },
}


def get_lang() -> str:
    """Текущий язык интерфейса (по умолчанию — русский)"""
    return st.session_state.get(LANG_KEY, DEFAULT_LANG)


def set_lang(lang: str):
    st.session_state[LANG_KEY] = lang


def t(key: str, **kwargs) -> str:
    """Возвращает локализованную строку по ключу, с подстановкой параметров через .format()"""
    lang = get_lang()
    template = STRINGS.get(lang, STRINGS[DEFAULT_LANG]).get(key, key)
    return template.format(**kwargs) if kwargs else template


def render_language_switch():
    """Переключатель языка (флаги) — вызывается один раз в самом верху страницы"""
    if LANG_KEY not in st.session_state:
        st.session_state[LANG_KEY] = DEFAULT_LANG

    current = get_lang()
    _, col_ru, col_en = st.columns([10, 1, 1])
    with col_ru:
        if st.button(
            FLAGS["ru"],
            key="lang_switch_ru",
            help="Русский",
            type="primary" if current == "ru" else "secondary",
        ):
            set_lang("ru")
            st.rerun()
    with col_en:
        if st.button(
            FLAGS["en"],
            key="lang_switch_en",
            help="English",
            type="primary" if current == "en" else "secondary",
        ):
            set_lang("en")
            st.rerun()
