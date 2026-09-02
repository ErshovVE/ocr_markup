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

from backend.config import (
    VLM_ENGINE_META,
    VLM_ENGINES,
    VLM_HEALTHCHECK_TIMEOUT_SECONDS,
)

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


def check_vlm_endpoint(engine_id: str) -> ModelState:
    """Пинг OpenAI-совместимого сервиса VLM-движка (GET {endpoint}/v1/models).

    В отличие от Paddle/Surya не кэшируется — endpoint (внешний сервис,
    llama-server / Ollama / vLLM) может подняться или упасть в любой момент,
    поэтому проверяется заново на каждый запрос статуса, как tesseract.
    """
    meta = VLM_ENGINE_META.get(engine_id)
    if meta is None:
        return ModelState("error", f"Неизвестный VLM-движок: {engine_id}")
    endpoint = os.environ.get(meta["endpoint_env"], "") or meta.get("default_endpoint", "")
    if not endpoint:
        return ModelState("error", f"{meta['endpoint_env']} не задан")
    try:
        import httpx

        response = httpx.get(
            f"{endpoint.rstrip('/')}/v1/models", timeout=VLM_HEALTHCHECK_TIMEOUT_SECONDS
        )
        response.raise_for_status()
    except Exception as e:
        return ModelState("error", f"Недоступен {endpoint}: {e}")
    return ModelState("ready", endpoint)


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


def get_status(include_vlm: bool = True) -> Dict[str, ModelState]:
    """Статус всех движков. include_vlm=False пропускает сетевые пинги
    VLM-endpoint'ов — нужно на классическом пути (_readiness_warnings в
    backend/main.py), чтобы обычный /run не платил за проверку 5 внешних
    сервисов, которые ему не нужны."""
    with _lock:
        snapshot = dict(_state)
    snapshot["tesseract"] = check_tesseract()
    for key, model_name in PADDLE_MODEL_NAMES.items():
        if snapshot[key].status == "not_checked" and _paddle_weights_on_disk(model_name):
            snapshot[key] = ModelState("ready", "Найдено в кэше на диске")
    for key, model_type in SURYA_MODEL_TYPES.items():
        if snapshot[key].status == "not_checked" and _surya_weights_on_disk(model_type):
            snapshot[key] = ModelState("ready", "Найдено в кэше на диске")
    if include_vlm:
        for engine_id in VLM_ENGINES:
            snapshot[f"vlm_{engine_id}"] = check_vlm_endpoint(engine_id)
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
    if name.startswith("vlm_"):
        raise ValueError(
            "VLM-модели поднимаются внешним сервисом (llama-server / Ollama / vLLM), "
            "/models/prepare для них не поддерживается — см. scripts/vlm/"
        )
    if name not in _state:
        raise ValueError(f"Неизвестная модель: {name}")
    threading.Thread(target=_prepare, args=(name,), daemon=True).start()
