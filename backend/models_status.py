"""Статус готовности движков распознавания (Paddle/Surya/Tesseract).

Состояние Paddle/Surya хранится в памяти процесса (см. backend/jobs.py) —
при перезапуске backend'а сбрасывается в "not_checked". Tesseract
проверяется заново при каждом запросе статуса, т.к. это системный бинарник,
а не lazy-loaded Python-объект.
"""

import shutil
import subprocess
import threading
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class ModelState:
    status: str = "not_checked"  # not_checked | checking | ready | error
    detail: Optional[str] = None


_state: Dict[str, ModelState] = {"paddle": ModelState(), "surya": ModelState()}
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


def get_status() -> Dict[str, ModelState]:
    with _lock:
        snapshot = dict(_state)
    snapshot["tesseract"] = check_tesseract()
    return snapshot


def _prepare(name: str):
    with _lock:
        _state[name] = ModelState("checking")
    try:
        from backend.recognizers import _Engines

        if name == "paddle":
            _Engines.paddle_cyrillic()
        elif name == "surya":
            _Engines.surya_recognition()
        with _lock:
            _state[name] = ModelState("ready")
    except Exception as e:
        with _lock:
            _state[name] = ModelState("error", str(e))


def prepare(name: str) -> None:
    if name not in _state:
        raise ValueError(f"Неизвестная модель: {name}")
    threading.Thread(target=_prepare, args=(name,), daemon=True).start()
