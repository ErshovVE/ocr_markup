import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import streamlit as st


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
