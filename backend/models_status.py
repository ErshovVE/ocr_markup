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

PADDLE_MODEL_NAMES = {
    "paddle": "cyrillic_PP-OCRv5_mobile_rec",
    "paddle_detector": "PP-OCRv6_medium_det",
}
SURYA_MODEL_TYPES = {
    "surya": "text_recognition",
    "surya_detector": "text_detection",
}


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


def _surya_weights_on_disk(model_type: str) -> bool:
    model_type_dir = Path(user_cache_dir("datalab")) / "models" / model_type
    if not model_type_dir.is_dir():
        return False
    return any(_manifest_complete(d) for d in model_type_dir.iterdir() if d.is_dir())


def _paddle_weights_on_disk(model_name: str) -> bool:
    cache_dir = os.environ.get("PADDLE_PDX_CACHE_HOME", os.path.expanduser("~/.paddlex"))
    model_dir = Path(cache_dir) / "official_models" / model_name
    return model_dir.is_dir() and any(model_dir.iterdir())


def get_status() -> Dict[str, ModelState]:
    with _lock:
        snapshot = dict(_state)
    snapshot["tesseract"] = check_tesseract()
    for key, model_name in PADDLE_MODEL_NAMES.items():
        if snapshot[key].status == "not_checked" and _paddle_weights_on_disk(model_name):
            snapshot[key] = ModelState("ready", "Найдено в кэше на диске")
    for key, model_type in SURYA_MODEL_TYPES.items():
        if snapshot[key].status == "not_checked" and _surya_weights_on_disk(model_type):
            snapshot[key] = ModelState("ready", "Найдено в кэше на диске")
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
