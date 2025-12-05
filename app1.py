import streamlit as st
import os
import shutil
from PIL import Image
from typing import Dict, List, Set, Tuple, Optional
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime
import json

st.set_page_config(layout="wide", page_title="Инструмент разметки OCR")

# Горячие клавиши через HTML/JavaScript
HOTKEYS_SCRIPT = """
<script>
document.addEventListener('keydown', function(e) {
    // Ctrl+S - сохранить
    if (e.ctrlKey && e.key === 's') {
        e.preventDefault();
        const saveBtn = document.querySelector('[data-testid="baseButton-secondary"]');
        if (saveBtn && saveBtn.textContent.includes('Сохранить')) {
            saveBtn.click();
        }
    }
    // Ctrl+Enter - подтвердить
    else if (e.ctrlKey && e.key === 'Enter') {
        e.preventDefault();
        const confirmBtn = Array.from(document.querySelectorAll('button')).find(
            btn => btn.textContent.includes('Подтвердить')
        );
        if (confirmBtn) confirmBtn.click();
    }
    // Стрелка влево - предыдущее изображение (только если не в поле ввода)
    else if (e.key === 'ArrowLeft' && e.target.tagName !== 'INPUT') {
        e.preventDefault();
        const prevBtn = Array.from(document.querySelectorAll('button')).find(
            btn => btn.textContent.includes('Пред.')
        );
        if (prevBtn && !prevBtn.disabled) prevBtn.click();
    }
    // Стрелка вправо - следующее изображение
    else if (e.key === 'ArrowRight' && e.target.tagName !== 'INPUT') {
        e.preventDefault();
        const nextBtn = Array.from(document.querySelectorAll('button')).find(
            btn => btn.textContent.includes('След.')
        );
        if (nextBtn && !nextBtn.disabled) nextBtn.click();
    }
});
</script>
"""


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
                return json.loads(self.metadata_file.read_text(encoding='utf-8'))
            except:
                return {"backups": []}
        return {"backups": []}
    
    def _save_metadata(self):
        """Сохраняет метаданные"""
        self.metadata_file.write_text(
            json.dumps(self.metadata, indent=2, ensure_ascii=False),
            encoding='utf-8'
        )
    
    def create_backup(self, source_file: Path, operation: str = "manual") -> Optional[Path]:
        """Создает резервную копию"""
        if not source_file.exists():
            return None
        
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"{source_file.stem}_{timestamp}.backup{source_file.suffix}"
            backup_path = self.backup_dir / backup_name
            
            shutil.copy2(source_file, backup_path)
            
            # Добавляем в метаданные
            self.metadata["backups"].append({
                "file": backup_name,
                "timestamp": timestamp,
                "operation": operation,
                "original": str(source_file.name)
            })
            
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
            to_remove = backups[:-self.max_backups]
            
            for backup_info in to_remove:
                backup_file = self.backup_dir / backup_info["file"]
                if backup_file.exists():
                    backup_file.unlink()
            
            # Оставляем только последние
            self.metadata["backups"] = backups[-self.max_backups:]
    
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
            self.metadata.get("backups", []),
            key=lambda x: x["timestamp"],
            reverse=True
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
            image_extensions = ('.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.webp')
            
            for line in lines:
                if not line.strip():
                    continue
                    
                parts = line.split('\t', 1)
                relative_path = parts[0].strip()
                annotation = parts[1].strip() if len(parts) == 2 else ""
                
                absolute_path = (self.base_dir / relative_path).resolve()
                
                if absolute_path.exists() and absolute_path.suffix.lower() in image_extensions:
                    img_name = absolute_path.name
                    self.records[img_name] = ImageRecord(
                        relative_path=relative_path,
                        absolute_path=str(absolute_path),
                        annotation=annotation
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
                marked_images = self.cache_path.read_text(encoding='utf-8').splitlines()
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
                    self.annotation_file, 
                    operation="save"
                )
                if backup_path:
                    st.info(f"📦 Бэкап создан: {backup_path.name}")
            
            # Сохраняем файл аннотаций
            lines = []
            for record in self.records.values():
                lines.append(f"{record.relative_path}\t{record.annotation}\n")
            
            self.annotation_file.write_text(''.join(lines), encoding='utf-8')
            
            # Сохраняем кэш статусов
            if self.cache_path:
                self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                marked_names = [name for name, rec in self.records.items() if rec.is_marked]
                self.cache_path.write_text('\n'.join(sorted(marked_names)) + '\n', encoding='utf-8')
            
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
def load_and_resize_image(image_path: str, max_height: int = 100, max_width: int = 1000):
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


def save_as_handwritten(manager: AnnotationManager, img_name: str, annotation: str) -> bool:
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
        rel_path = f"handwritten_images/{record.relative_path}".replace('\\', '/')
        new_line = f"{rel_path}\t{annotation}\n"
        
        # Проверяем дубликаты
        if handwritten_txt.exists():
            content = handwritten_txt.read_text(encoding='utf-8')
            if new_line in content:
                st.info("Запись уже существует в handwritten.txt")
                return True
        
        with open(handwritten_txt, 'a', encoding='utf-8') as f:
            f.write(new_line)
        
        return True
    except Exception as e:
        st.error(f"Ошибка сохранения как рукописный: {e}")
        return False


def init_session_state():
    """Инициализирует session state"""
    defaults = {
        'manager': None,
        'current_idx': 0,
        'current_page': 0,
        'page_size': 100,
        'filter_option': 'all',
        'unsaved_changes': 0,
        'confirm_delete': None,  # Имя изображения для подтверждения удаления
        'show_backups': False
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def render_image_list(manager: AnnotationManager, filtered_images: List[str]):
    """Отрисовывает список изображений с пагинацией"""
    st.subheader("Список изображений")
    
    # Фильтр
    filter_options = {
        "all": "Все изображения",
        "unmarked": "Только неразмеченные",
        "marked": "Только размеченные"
    }
    
    selected = st.radio(
        "Показать:",
        list(filter_options.values()),
        index=list(filter_options.keys()).index(st.session_state.filter_option),
        key="filter_radio"
    )
    
    new_filter = list(filter_options.keys())[list(filter_options.values()).index(selected)]
    if new_filter != st.session_state.filter_option:
        st.session_state.filter_option = new_filter
        st.session_state.current_page = 0
        st.session_state.current_idx = 0
        st.rerun()
    
    # Пагинация
    total = len(filtered_images)
    total_pages = max(1, (total + st.session_state.page_size - 1) // st.session_state.page_size)
    
    if st.session_state.current_page >= total_pages:
        st.session_state.current_page = total_pages - 1
    
    start = st.session_state.current_page * st.session_state.page_size
    end = min(start + st.session_state.page_size, total)
    
    # Список
    with st.container(height=400):
        for i, img_name in enumerate(filtered_images[start:end]):
            record = manager.records[img_name]
            status = "✅" if record.is_marked else "❓"
            display = f"{status} {img_name}"
            
            # Находим глобальный индекс
            global_idx = list(manager.records.keys()).index(img_name)
            
            if global_idx == st.session_state.current_idx:
                st.markdown(f"**→ {display}**")
            else:
                if st.button(display, key=f"img_{global_idx}"):
                    st.session_state.current_idx = global_idx
                    st.rerun()
    
    # Кнопки пагинации
    col1, col2, col3 = st.columns([1, 2, 1])
    with col1:
        if st.button("← Предыдущая", disabled=st.session_state.current_page == 0):
            st.session_state.current_page -= 1
            st.rerun()
    with col2:
        st.markdown(f"Страница {st.session_state.current_page + 1} из {total_pages}")
    with col3:
        if st.button("Следующая →", disabled=st.session_state.current_page == total_pages - 1):
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
    
    st.subheader(f"Текущее изображение: {current_name}")
    
    # Отображение изображения
    image = load_and_resize_image(record.absolute_path, max_height=80, max_width=1200)
    if image:
        st.image(image)
    
    # Модальное окно подтверждения удаления
    if st.session_state.confirm_delete == current_name:
        st.error(f"⚠️ Вы уверены, что хотите удалить **{current_name}**?")
        st.warning("Это действие необратимо! Файл будет удален с диска.")
        
        col_confirm1, col_confirm2, col_confirm3 = st.columns([1, 1, 2])
        with col_confirm1:
            if st.button("✓ Да, удалить", type="primary"):
                if manager.delete_record(current_name, create_backup=True):
                    manager.save_changes(create_backup=False)  # Уже создали бэкап в delete_record
                    st.success("✓ Изображение удалено, бэкап создан")
                    st.session_state.confirm_delete = None
                    st.rerun()
        with col_confirm2:
            if st.button("✗ Отмена"):
                st.session_state.confirm_delete = None
                st.rerun()
        
        st.divider()
        return  # Показываем только диалог подтверждения
    
    # Форма редактирования
    with st.form(key=f"form_{current_name}"):
        text_value = st.text_input(
            "Текст с изображения",
            value=record.annotation,
            key=f"input_{current_name}",
            help="Ctrl+Enter для быстрого подтверждения"
        )
        
        col1, col2 = st.columns(2)
        with col1:
            submit = st.form_submit_button("✓ Подтвердить", use_container_width=True)
        with col2:
            handwritten = st.form_submit_button("✍ Рукописный текст", use_container_width=True)
        
        if submit:
            clean_text = text_value.replace('\n', ' ').replace('\r', ' ').strip()
            manager.update_annotation(current_name, clean_text)
            st.session_state.unsaved_changes += 1
            
            # Автосохранение каждые 10 изменений
            if st.session_state.unsaved_changes >= 10:
                success, msg = manager.save_changes()
                if success:
                    st.session_state.unsaved_changes = 0
                    st.success("💾 Автосохранение выполнено")
            else:
                st.success(f"✓ Сохранено в памяти (несохранено: {st.session_state.unsaved_changes})")
            
            # Переход к следующему
            if st.session_state.current_idx < len(img_names) - 1:
                st.session_state.current_idx += 1
            st.rerun()
        
        if handwritten:
            clean_text = text_value.replace('\n', ' ').replace('\r', ' ').strip()
            if save_as_handwritten(manager, current_name, clean_text):
                st.success("✓ Сохранено как рукописный текст")
    
    # Действия вне формы
    st.markdown("### Действия")
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        if st.button("🗑 Удалить", use_container_width=True, type="secondary"):
            st.session_state.confirm_delete = current_name
            st.rerun()
    
    with col2:
        if st.button("↶ Влево", use_container_width=True):
            if rotate_image(record.absolute_path, "left"):
                st.success("↶ Повернуто влево")
                st.rerun()
    
    with col3:
        if st.button("↷ Вправо", use_container_width=True):
            if rotate_image(record.absolute_path, "right"):
                st.success("↷ Повернуто вправо")
                st.rerun()
    
    with col4:
        if st.button("← Пред.", use_container_width=True, disabled=st.session_state.current_idx == 0):
            st.session_state.current_idx -= 1
            st.rerun()
    
    with col5:
        if st.button("След. →", use_container_width=True, disabled=st.session_state.current_idx >= len(img_names) - 1):
            st.session_state.current_idx += 1
            st.rerun()
    
    # Индикатор несохраненных изменений
    if st.session_state.unsaved_changes > 0:
        st.warning(f"⚠️ Несохраненных изменений: {st.session_state.unsaved_changes}")
        if st.button("💾 Сохранить сейчас", type="primary"):
            success, msg = manager.save_changes()
            if success:
                st.session_state.unsaved_changes = 0
                st.success(msg)
                st.rerun()
    
    # Горячие клавиши - подсказка
    st.caption("💡 **Горячие клавиши:** Ctrl+S (сохранить) | Ctrl+Enter (подтвердить) | ← → (навигация)")


def main():
    # CSS
    st.markdown("""
        <style>
        [data-testid="stToolbar"], [data-testid="stDecoration"], 
        [data-testid="stStatusWidget"], header {visibility: hidden;}
        .block-container {padding-top: 1rem;}
        img {border: 2px solid #4CAF50; box-shadow: 2px 2px 5px rgba(0,0,0,0.2);}
        </style>
    """, unsafe_allow_html=True)
    
    # Горячие клавиши
    st.components.v1.html(HOTKEYS_SCRIPT, height=0)
    
    st.title("🖼️ Инструмент разметки OCR")
    
    init_session_state()
    
    # Загрузка файла
    uploaded_file = st.file_uploader("Загрузите файл разметки (.txt)", type=["txt"])
    
    if uploaded_file:
        # Путь к рабочей директории
        working_dir = st.text_input(
            "Укажите рабочую директорию",
            placeholder="Например: G:/Датасет"
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
            
            file_contents = uploaded_file.read().decode('utf-8')
            success, error = st.session_state.manager.load_from_file(file_contents)
            
            if not success:
                st.error(error)
                return
            
            st.success(f"✓ Загружено {len(st.session_state.manager.records)} изображений")
        
        manager = st.session_state.manager
        
        # Получаем отфильтрованный список
        filtered = manager.get_image_list(st.session_state.filter_option)
        
        if not filtered:
            st.warning("Нет изображений по выбранному фильтру")
            
            # Позволяем изменить фильтр
            filter_opts = {"all": "Все", "unmarked": "Неразмеченные", "marked": "Размеченные"}
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
        st.sidebar.metric("Всего изображений", total)
        st.sidebar.metric("Размечено", f"{marked} ({marked*100//total if total else 0}%)")
        st.sidebar.metric("Осталось", total - marked)
        
        st.sidebar.divider()
        
        # Финальное сохранение
        if st.sidebar.button("💾 Сохранить все изменения", use_container_width=True, type="primary"):
            success, msg = manager.save_changes()
            if success:
                st.session_state.unsaved_changes = 0
                st.sidebar.success("✓ Все изменения сохранены")
            else:
                st.sidebar.error(msg)
        
        # Управление бэкапами
        st.sidebar.divider()
        st.sidebar.header("🗂️ Резервные копии")
        
        backups = manager.backup_manager.get_backups_list()
        
        if backups:
            st.sidebar.caption(f"Всего бэкапов: {len(backups)} (макс. {manager.backup_manager.max_backups})")
            
            if st.sidebar.button("📋 Показать бэкапы", use_container_width=True):
                st.session_state.show_backups = not st.session_state.show_backups
            
            if st.session_state.show_backups:
                st.sidebar.markdown("---")
                for backup in backups[:5]:  # Показываем последние 5
                    timestamp_formatted = datetime.strptime(
                        backup["timestamp"], "%Y%m%d_%H%M%S"
                    ).strftime("%d.%m.%Y %H:%M:%S")
                    
                    operation_emoji = {
                        "save": "💾",
                        "delete": "🗑️",
                        "manual": "✋"
                    }.get(backup["operation"], "📝")
                    
                    st.sidebar.caption(f"{operation_emoji} {timestamp_formatted}")
                    st.sidebar.caption(f"Файл: `{backup['file'][:30]}...`")
                    
                    if st.sidebar.button(
                        "↩️ Восстановить",
                        key=f"restore_{backup['file']}",
                        use_container_width=True
                    ):
                        if manager.backup_manager.restore_backup(
                            backup["file"],
                            manager.annotation_file
                        ):
                            st.sidebar.success("✓ Восстановлено из бэкапа!")
                            st.sidebar.info("Перезагрузите приложение для применения изменений")
                        else:
                            st.sidebar.error("Ошибка восстановления")
                    
                    st.sidebar.markdown("---")
        else:
            st.sidebar.caption("Бэкапов пока нет")
        
        # Информация о горячих клавишах
        st.sidebar.divider()
        st.sidebar.header("⌨️ Горячие клавиши")
        st.sidebar.markdown("""
        - **Ctrl + S** — Сохранить все
        - **Ctrl + Enter** — Подтвердить текст
        - **← →** — Навигация по изображениям
        """)


if __name__ == "__main__":
    main()