"""Статус готовности движков распознавания (Paddle/Surya/Tesseract).

Состояние Paddle/Surya хранится в памяти процесса (см. backend/jobs.py) —
при перезапуске backend'а сбрасывается в "not_checked". Пока оно не было
проверено в текущем запуске, статус дополняется проверкой кэша моделей на
диске (веса переживают перезапуск контейнера, см. volumes в
docker-compose.yml) — по тому же алгоритму, что используют сами
paddlex/surya для решения "уже скачано, докачивать не нужно". Tesseract
проверяется заново при каждом запросе статуса, т.к. это системный бинарник,
а не lazy-loaded Python-объект.
"""

import json
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from platformdirs import user_cache_dir

PADDLE_CYRILLIC_MODEL_NAME = "cyrillic_PP-OCRv5_mobile_rec"


@dataclass
class ModelState:
    status: str = "not_checked"  # not_checked | checking | ready | error
    detail: Optional[str] = None


_state: Dict[str, ModelState] = {
    "paddle": ModelState(),
    "surya": ModelState(),
    "paddle_detector": ModelState(),
    "surya_detector": ModelState(),
}
_lock = threading.Lock()


def check_tesseract() -> ModelState:
    binary = shutil.which("tesseract")
    if not binary:
        return ModelState("error", "Бинарник tesseract не найден в PATH")
    try:
        output = subprocess.run(
            [binary, "--list-langs"], capture_output=True, text=True, timeout=5
        ).stdout
    except Exception as e:
        return ModelState("error", f"Не удалось запустить tesseract: {e}")
    if "rus" not in output:
        return ModelState("error", "Языковой пакет rus не установлен")
    return ModelState("ready")


def _manifest_complete(model_dir: Path) -> bool:
    """Повторяет check_manifest() из surya/common/s3.py: модель считается
    скачанной, если рядом с файлами лежит manifest.json и все перечисленные
    в нём файлы присутствуют на диске."""
    manifest_path = model_dir / "manifest.json"
    if not manifest_path.is_file():
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return all((model_dir / f).exists() for f in manifest["files"])
    except Exception:
        return False


def _surya_weights_on_disk() -> bool:
    recognition_dir = Path(user_cache_dir("datalab")) / "models" / "text_recognition"
    if not recognition_dir.is_dir():
        return False
    return any(_manifest_complete(d) for d in recognition_dir.iterdir() if d.is_dir())


def _paddle_weights_on_disk() -> bool:
    cache_dir = os.environ.get("PADDLE_PDX_CACHE_HOME", os.path.expanduser("~/.paddlex"))
    model_dir = Path(cache_dir) / "official_models" / PADDLE_CYRILLIC_MODEL_NAME
    return model_dir.is_dir() and any(model_dir.iterdir())


def get_status() -> Dict[str, ModelState]:
    with _lock:
        snapshot = dict(_state)
    snapshot["tesseract"] = check_tesseract()
    if snapshot["paddle"].status == "not_checked" and _paddle_weights_on_disk():
        snapshot["paddle"] = ModelState("ready", "Найдено в кэше на диске")
    if snapshot["surya"].status == "not_checked" and _surya_weights_on_disk():
        snapshot["surya"] = ModelState("ready", "Найдено в кэше на диске")
    return snapshot


def _prepare(name: str):
    with _lock:
        _state[name] = ModelState("checking")
    try:
        from backend.detector import _Engines as DetectorEngines
        from backend.recognizers import _Engines as RecognizerEngines

        if name == "paddle":
            RecognizerEngines.paddle_cyrillic()
        elif name == "surya":
            RecognizerEngines.surya_recognition()
        elif name == "paddle_detector":
            DetectorEngines.paddle()
        elif name == "surya_detector":
            DetectorEngines.surya()
        with _lock:
            _state[name] = ModelState("ready")
    except Exception as e:
        with _lock:
            _state[name] = ModelState("error", str(e))


def prepare(name: str) -> None:
    if name not in _state:
        raise ValueError(f"Неизвестная модель: {name}")
    threading.Thread(target=_prepare, args=(name,), daemon=True).start()
