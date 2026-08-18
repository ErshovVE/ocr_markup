import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import streamlit as st

from src.backup import BackupManager
from src.models import ImageRecord


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
            resolved_base_dir = self.base_dir.resolve()

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
                    and absolute_path.is_relative_to(resolved_base_dir)
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
