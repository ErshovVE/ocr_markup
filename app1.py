import streamlit as st
import os
import shutil
from PIL import Image
from typing import Dict, List, Set, Tuple, Optional
from dataclasses import dataclass
from pathlib import Path

st.set_page_config(layout="wide", page_title="Инструмент разметки OCR")


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
    
    def delete_record(self, img_name: str) -> bool:
        """Удаляет запись об изображении"""
        if img_name not in self.records:
            return False
        
        record = self.records[img_name]
        
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
    
    def save_changes(self) -> Tuple[bool, str]:
        """Сохраняет все изменения"""
        if not self.modified_records and not self.records:
            return True, ""
        
        try:
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
        'unsaved_changes': 0
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
    
    # Форма редактирования
    with st.form(key=f"form_{current_name}"):
        text_value = st.text_input(
            "Текст с изображения",
            value=record.annotation,
            key=f"input_{current_name}"
        )
        
        col1, col2 = st.columns(2)
        with col1:
            submit = st.form_submit_button("✓ Подтвердить")
        with col2:
            handwritten = st.form_submit_button("✍ Рукописный текст")
        
        if submit:
            clean_text = text_value.replace('\n', ' ').replace('\r', ' ').strip()
            manager.update_annotation(current_name, clean_text)
            st.session_state.unsaved_changes += 1
            
            # Автосохранение каждые 10 изменений
            if st.session_state.unsaved_changes >= 10:
                success, msg = manager.save_changes()
                if success:
                    st.session_state.unsaved_changes = 0
                    st.success("Автосохранение выполнено")
            
            # Переход к следующему
            if st.session_state.current_idx < len(img_names) - 1:
                st.session_state.current_idx += 1
            st.rerun()
        
        if handwritten:
            clean_text = text_value.replace('\n', ' ').replace('\r', ' ').strip()
            if save_as_handwritten(manager, current_name, clean_text):
                st.success("Сохранено как рукописный текст")
    
    # Действия вне формы
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        if st.button("🗑 Удалить"):
            if manager.delete_record(current_name):
                manager.save_changes()
                st.success("Изображение удалено")
                st.rerun()
    
    with col2:
        if st.button("↶ Влево"):
            if rotate_image(record.absolute_path, "left"):
                st.success("Повернуто влево")
                st.rerun()
    
    with col3:
        if st.button("↷ Вправо"):
            if rotate_image(record.absolute_path, "right"):
                st.success("Повернуто вправо")
                st.rerun()
    
    with col4:
        if st.button("← Пред.") and st.session_state.current_idx > 0:
            st.session_state.current_idx -= 1
            st.rerun()
    
    with col5:
        if st.button("След. →") and st.session_state.current_idx < len(img_names) - 1:
            st.session_state.current_idx += 1
            st.rerun()
    
    # Индикатор несохраненных изменений
    if st.session_state.unsaved_changes > 0:
        st.warning(f"⚠️ Несохраненных изменений: {st.session_state.unsaved_changes}")
        if st.button("💾 Сохранить сейчас"):
            success, msg = manager.save_changes()
            if success:
                st.session_state.unsaved_changes = 0
                st.success(msg)
                st.rerun()


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
            
            st.success(f"Загружено {len(st.session_state.manager.records)} изображений")
        
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
        
        # Статистика
        st.sidebar.header("📊 Статистика")
        total = len(manager.records)
        marked = sum(1 for r in manager.records.values() if r.is_marked)
        st.sidebar.metric("Всего изображений", total)
        st.sidebar.metric("Размечено", f"{marked} ({marked*100//total if total else 0}%)")
        st.sidebar.metric("Осталось", total - marked)
        
        # Финальное сохранение
        if st.sidebar.button("💾 Сохранить все изменения"):
            success, msg = manager.save_changes()
            if success:
                st.session_state.unsaved_changes = 0
                st.sidebar.success("✓ Все изменения сохранены")
            else:
                st.sidebar.error(msg)


if __name__ == "__main__":
    main()