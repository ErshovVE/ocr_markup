import streamlit as st
import os
import shutil
from PIL import Image
from typing import Dict, List, Set, Tuple, Optional
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime
import json
from streamlit.components.v1 import html

st.set_page_config(layout="wide", page_title="Инструмент разметки OCR")


def register_hotkeys():
    """Регистрирует горячие клавиши через HTML/JS компонент"""
    hotkeys_html = """
    <script>
    // Удаляем предыдущий обработчик если есть
    if (window.hotkeyHandler) {
        document.removeEventListener('keydown', window.hotkeyHandler);
    }
    
    window.hotkeyHandler = function(e) {
        const parent = window.parent;
        
        // Игнорируем если фокус в input/textarea
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
            return;
        }
        
        let action = null;
        
        // Стрелка влево
        if (e.key === 'ArrowLeft') {
            e.preventDefault();
            action = 'prev';
        }
        // Стрелка вправо
        else if (e.key === 'ArrowRight') {
            e.preventDefault();
            action = 'next';
        }
        
        if (action) {
            // Находим и кликаем соответствующую кнопку
            const buttons = parent.document.querySelectorAll('button');
            buttons.forEach(btn => {
                const text = btn.textContent;
                if (action === 'prev' && text.includes('Пред.')) {
                    if (!btn.disabled) btn.click();
                } else if (action === 'next' && text.includes('След.')) {
                    if (!btn.disabled) btn.click();
                }
            });
        }
    };
    
    document.addEventListener('keydown', window.hotkeyHandler);
    parent.document.addEventListener('keydown', window.hotkeyHandler);
    </script>
    """
    html(hotkeys_html, height=0)


class BackupManager:
    """Управление резервными копиями с ротацией"""

    def __init__(self, base_dir: Path, max_backups: int = 5):
        self.base_dir = base_dir
        self.backup_dir = base_dir / ".backups"
        self.max_backups = max_backups
        self.backup_dir.mkdir(exist_ok=True)

        # Метаданные бэкапов
        self.metadata_file = self.backup_dir / "metadata.json"
        self.metadata = self._load_metadata()

    def _load_metadata(self) -> Dict:
        """Загружает метаданные бэкапов"""
        if self.metadata_file.exists():
            try:
                return json.loads(self.metadata_file.read_text(encoding="utf-8"))
            except:
                return {"backups": []}
        return {"backups": []}

    def _save_metadata(self):
        """Сохраняет метаданные"""
        self.metadata_file.write_text(
            json.dumps(self.metadata, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def create_backup(
        self, source_file: Path, operation: str = "manual"
    ) -> Optional[Path]:
        """Создает резервную копию"""
        if not source_file.exists():
            return None

        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"{source_file.stem}_{timestamp}.backup{source_file.suffix}"
            backup_path = self.backup_dir / backup_name

            shutil.copy2(source_file, backup_path)

            # Добавляем в метаданные
            self.metadata["backups"].append(
                {
                    "file": backup_name,
                    "timestamp": timestamp,
                    "operation": operation,
                    "original": str(source_file.name),
                }
            )

            # Ротация старых бэкапов
            self._rotate_backups()
            self._save_metadata()

            return backup_path
        except Exception as e:
            st.error(f"Ошибка создания бэкапа: {e}")
            return None

    def _rotate_backups(self):
        """Удаляет старые бэкапы, оставляя только последние max_backups"""
        backups = self.metadata["backups"]

        if len(backups) > self.max_backups:
            # Удаляем самые старые
            to_remove = backups[: -self.max_backups]

            for backup_info in to_remove:
                backup_file = self.backup_dir / backup_info["file"]
                if backup_file.exists():
                    backup_file.unlink()

            # Оставляем только последние
            self.metadata["backups"] = backups[-self.max_backups :]

    def restore_backup(self, backup_name: str, target_file: Path) -> bool:
        """Восстанавливает из бэкапа"""
        backup_path = self.backup_dir / backup_name

        if not backup_path.exists():
            return False

        try:
            shutil.copy2(backup_path, target_file)
            return True
        except Exception as e:
            st.error(f"Ошибка восстановления: {e}")
            return False

    def get_backups_list(self) -> List[Dict]:
        """Возвращает список доступных бэкапов"""
        return sorted(
            self.metadata.get("backups", []), key=lambda x: x["timestamp"], reverse=True
        )


@dataclass
class ImageRecord:
    """Структура данных для одной записи изображения"""

    relative_path: str
    absolute_path: str
    annotation: str
    is_marked: bool = False


class AnnotationManager:
    """Класс для управления аннотациями с отложенным сохранением"""

    def __init__(self, base_dir: str, annotation_file: str):
        self.base_dir = Path(base_dir)
        self.annotation_file = Path(annotation_file)
        self.records: Dict[str, ImageRecord] = {}
        self.modified_records: Set[str] = set()
        self.cache_path: Optional[Path] = None
        self.backup_manager = BackupManager(self.base_dir)

    def load_from_file(self, file_contents: str) -> Tuple[bool, str]:
        """Загружает данные из файла"""
        try:
            lines = file_contents.splitlines()
            image_extensions = (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp")

            for line in lines:
                if not line.strip():
                    continue

                parts = line.split("\t", 1)
                relative_path = parts[0].strip()
                annotation = parts[1].strip() if len(parts) == 2 else ""

                absolute_path = (self.base_dir / relative_path).resolve()

                if (
                    absolute_path.exists()
                    and absolute_path.suffix.lower() in image_extensions
                ):
                    img_name = absolute_path.name
                    self.records[img_name] = ImageRecord(
                        relative_path=relative_path,
                        absolute_path=str(absolute_path),
                        annotation=annotation,
                    )

            if not self.records:
                return False, "Не удалось найти файлы изображений"

            # Загружаем статусы из кэша
            self._load_status_cache()
            return True, ""

        except Exception as e:
            return False, f"Ошибка загрузки: {e}"

    def _load_status_cache(self):
        """Загружает кэш статусов"""
        if not self.records:
            return

        # Определяем путь к кэшу на основе первой директории
        first_rel_path = next(iter(self.records.values())).relative_path
        first_dir = Path(first_rel_path).parts[0] if first_rel_path else None

        if first_dir:
            self.cache_path = self.base_dir / first_dir / "status_cache.txt"
        else:
            self.cache_path = self.base_dir / "status_cache.txt"

        if self.cache_path.exists():
            try:
                marked_images = self.cache_path.read_text(encoding="utf-8").splitlines()
                for img_name in marked_images:
                    img_name = img_name.strip()
                    if img_name in self.records:
                        self.records[img_name].is_marked = True
            except Exception:
                pass

    def update_annotation(self, img_name: str, new_text: str):
        """Обновляет аннотацию для изображения"""
        if img_name in self.records:
            self.records[img_name].annotation = new_text
            self.records[img_name].is_marked = True
            self.modified_records.add(img_name)

    def delete_record(self, img_name: str, create_backup: bool = True) -> bool:
        """Удаляет запись об изображении"""
        if img_name not in self.records:
            return False

        record = self.records[img_name]

        # Создаем бэкап перед удалением
        if create_backup:
            self.backup_manager.create_backup(self.annotation_file, operation="delete")

        # Удаляем файл
        try:
            os.remove(record.absolute_path)
        except OSError as e:
            st.error(f"Ошибка удаления файла: {e}")
            return False

        # Удаляем из структур данных
        del self.records[img_name]
        self.modified_records.discard(img_name)

        return True

    def save_changes(self, create_backup: bool = True) -> Tuple[bool, str]:
        """Сохраняет все изменения"""
        if not self.modified_records and not self.records:
            return True, ""

        try:
            # Создаем бэкап перед сохранением
            if create_backup and self.annotation_file.exists():
                backup_path = self.backup_manager.create_backup(
                    self.annotation_file, operation="save"
                )
                if backup_path:
                    st.info(f"📦 Бэкап создан: {backup_path.name}")

            # Сохраняем файл аннотаций
            lines = []
            for record in self.records.values():
                lines.append(f"{record.relative_path}\t{record.annotation}\n")

            self.annotation_file.write_text("".join(lines), encoding="utf-8")

            # Сохраняем кэш статусов
            if self.cache_path:
                self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                marked_names = [
                    name for name, rec in self.records.items() if rec.is_marked
                ]
                self.cache_path.write_text(
                    "\n".join(sorted(marked_names)) + "\n", encoding="utf-8"
                )

            self.modified_records.clear()
            return True, "Изменения сохранены"

        except Exception as e:
            return False, f"Ошибка сохранения: {e}"

    def get_image_list(self, filter_type: str = "all") -> List[str]:
        """Возвращает отфильтрованный список имен изображений"""
        if filter_type == "unmarked":
            return [name for name, rec in self.records.items() if not rec.is_marked]
        elif filter_type == "marked":
            return [name for name, rec in self.records.items() if rec.is_marked]
        else:
            return list(self.records.keys())


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


def save_as_handwritten(
    manager: AnnotationManager, img_name: str, annotation: str
) -> bool:
    """Сохраняет изображение как рукописный текст"""
    try:
        record = manager.records[img_name]

        # Путь назначения
        handwritten_root = manager.base_dir / "handwritten_images"
        dest_path = handwritten_root / record.relative_path
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        # Копируем файл
        shutil.copy2(record.absolute_path, dest_path)

        # Добавляем в handwritten.txt
        handwritten_txt = manager.base_dir / "handwritten.txt"
        rel_path = f"handwritten_images/{record.relative_path}".replace("\\", "/")
        new_line = f"{rel_path}\t{annotation}\n"

        # Проверяем дубликаты
        if handwritten_txt.exists():
            content = handwritten_txt.read_text(encoding="utf-8")
            if new_line in content:
                st.info("Запись уже существует в handwritten.txt")
                return True

        with open(handwritten_txt, "a", encoding="utf-8") as f:
            f.write(new_line)

        return True
    except Exception as e:
        st.error(f"Ошибка сохранения как рукописный: {e}")
        return False


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
    if st.session_state.confirm_delete == current_name:
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
        return

    # Форма редактирования
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

    # Компактные действия
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
            "◀",
            use_container_width=True,
            disabled=prev_disabled,
            key=f"prev_{current_name}",
            help="Предыдущее (←)",
        ):
            st.session_state.current_idx -= 1
            st.rerun()

    with col5:
        next_disabled = st.session_state.current_idx >= len(img_names) - 1
        if st.button(
            "▶",
            use_container_width=True,
            disabled=next_disabled,
            key=f"next_{current_name}",
            help="Следующее (→)",
        ):
            st.session_state.current_idx += 1
            st.rerun()

    # Компактный индикатор несохраненных изменений
    if st.session_state.unsaved_changes > 0:
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

    # Компактная подсказка
    st.caption("💡 **← →** для навигации")

    # Встраиваем обработчик горячих клавиш
    register_hotkeys()


def main():
    # Компактный CSS
    st.markdown(
        """
        <style>
        [data-testid="stToolbar"], [data-testid="stDecoration"], 
        [data-testid="stStatusWidget"], header {visibility: hidden;}
        .block-container {padding-top: 0.5rem; padding-bottom: 0.5rem;}
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

            st.success(
                f"✓ Загружено {len(st.session_state.manager.records)} изображений"
            )

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
        st.sidebar.header("📊 Статистика")
        total = len(manager.records)
        marked = sum(1 for r in manager.records.values() if r.is_marked)
        st.sidebar.metric("Всего", total)
        st.sidebar.metric(
            "Размечено", f"{marked} ({marked * 100 // total if total else 0}%)"
        )
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
                st.sidebar.success("✓ Сохранено в handwritten.txt")
            else:
                st.sidebar.error(msg)

        # Управление бэкапами
        st.sidebar.divider()
        st.sidebar.header("🗂️ Бэкапы")

        backups = manager.backup_manager.get_backups_list()

        if backups:
            st.sidebar.caption(
                f"{len(backups)} из {manager.backup_manager.max_backups}"
            )

            if st.sidebar.button(
                "📋",
                use_container_width=True,
                key="show_backups_btn",
                help="Показать/скрыть бэкапы",
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


if __name__ == "__main__":
    main()
