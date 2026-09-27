"""Статус готовности движков распознавания (Paddle/Surya/Tesseract) и VLM.

Состояние Paddle/Surya хранится в памяти процесса (см. backend/jobs.py) —
при перезапуске backend'а сбрасывается в "not_checked". Пока оно не было
проверено в текущем запуске, статус дополняется проверкой кэша моделей на
диске (веса переживают перезапуск контейнера, см. volumes в
docker-compose.yml) — по тому же алгоритму, что используют сами
paddlex/surya для решения "уже скачано, докачивать не нужно". Tesseract
проверяется заново при каждом запросе статуса, т.к. это системный бинарник,
а не lazy-loaded Python-объект.

VLM-движки обслуживает один llama-server (router): их статус — один запрос
GET /v1/models с коротким TTL-кэшем (фронтенд опрашивает /models/status по таймеру).
"""

import json
import logging
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

import httpx
from platformdirs import user_cache_dir

from backend import vlm_client
from backend.config import (
    VLM_ENGINE_META,
    VLM_ENGINES,
    VLM_HEALTHCHECK_TIMEOUT_SECONDS,
    VLM_STATUS_CACHE_TTL_SECONDS,
)

logger = logging.getLogger(__name__)

PADDLE_MODEL_NAMES = {
    "paddle": "cyrillic_PP-OCRv5_mobile_rec",
    "paddle_detector": "PP-OCRv6_medium_det",
}
SURYA_MODEL_TYPES = {
    "surya": "text_recognition",
    "surya_detector": "text_detection",
}


def _resolve_tesseract() -> Optional[str]:
    """Путь к бинарнику tesseract: приоритет у явного TESSERACT_CMD, иначе
    резолвим через PATH. Явный путь убирает риск PATH/CWD-hijack (на Windows
    shutil.which исторически смотрел в текущий каталог)."""
    return os.environ.get("TESSERACT_CMD") or shutil.which("tesseract")


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
# Отдельный лок на ленивую конструкцию тяжёлых движков в _prepare — _lock
# защищает только _state, а сами _Engines.* не потокобезопасны при
# одновременной первой инициализации.
_prepare_lock = threading.Lock()

# TTL-кэш статусов VLM: (monotonic_ts, {"vlm_<id>": ModelState}) или () — пусто.
_vlm_cache: Tuple = ()
_vlm_cache_lock = threading.Lock()


def check_tesseract() -> ModelState:
    binary = _resolve_tesseract()
    if not binary:
        return ModelState("error", "Бинарник tesseract не найден (задайте TESSERACT_CMD)")
    try:
        output = subprocess.run(
            [binary, "--list-langs"], capture_output=True, text=True, timeout=5
        ).stdout
    except Exception as e:
        return ModelState("error", f"Не удалось запустить tesseract: {e}")
    if "rus" not in output:
        return ModelState("error", "Языковой пакет rus не установлен")
    return ModelState("ready")


def _fetch_router_models() -> Optional[Dict[str, dict]]:
    """{id модели: запись} из GET /v1/models llama-server'а (router-режим
    перечисляет все пресеты, в т.ч. ещё не загруженные, со status.value
    loaded/unloaded и status.failed после неудачной загрузки). None — сервер
    недоступен. URL и текст ошибки наружу не отдаём (M8 в ревью) — только в лог."""
    base = vlm_client.endpoint()
    try:
        response = httpx.get(
            f"{base}/v1/models", timeout=VLM_HEALTHCHECK_TIMEOUT_SECONDS, follow_redirects=False
        )
        response.raise_for_status()
        items = response.json().get("data", [])
    except Exception as e:
        logger.warning("llama-server VLM недоступен (%s): %s", base, e)
        return None
    return {item["id"]: item for item in items if isinstance(item, dict) and "id" in item}


def _model_state(engine_id: str, models: Optional[Dict[str, dict]]) -> ModelState:
    """Статус движка по записи его пресета в /v1/models."""
    meta = VLM_ENGINE_META.get(engine_id)
    if meta is None:
        return ModelState("error", f"Неизвестный VLM-движок: {engine_id}")
    if models is None:
        return ModelState("error", "эндпоинт недоступен")
    entry = models.get(meta["served_model_name"])
    if entry is None:
        return ModelState("error", "модели нет в пресетах llama-server (scripts/vlm/models.ini)")
    status = entry.get("status") or {}
    if status.get("failed"):
        return ModelState("error", "модель не загрузилась — см. логи llama-vlm")
    if status.get("value") == "loaded":
        return ModelState("ready")
    return ModelState("ready", "загрузится при первом запросе")


def _check_all_vlm() -> Dict[str, ModelState]:
    """Статус всех VLM-движков одним запросом к llama-server, с TTL-кэшем
    (VLM_STATUS_CACHE_TTL_SECONDS): фронтенд опрашивает /models/status по таймеру."""
    global _vlm_cache
    now = time.monotonic()
    with _vlm_cache_lock:
        if _vlm_cache and now - _vlm_cache[0] < VLM_STATUS_CACHE_TTL_SECONDS:
            return dict(_vlm_cache[1])
    models = _fetch_router_models()
    states = {f"vlm_{engine_id}": _model_state(engine_id, models) for engine_id in VLM_ENGINES}
    with _vlm_cache_lock:
        _vlm_cache = (now, states)
    return dict(states)


def check_vlm_endpoint(engine_id: str) -> ModelState:
    """Статус одного VLM-движка (из общего кэшированного ответа llama-server)."""
    return _check_all_vlm().get(f"vlm_{engine_id}") or _model_state(engine_id, {})


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
        snapshot.update(_check_all_vlm())
    return snapshot


def _prepare(name: str):
    with _lock:
        _state[name] = ModelState("checking")
    try:
        from backend.detector import _Engines as DetectorEngines
        from backend.recognizers import _Engines as RecognizerEngines

        with _prepare_lock:
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
            "VLM-модели обслуживает llama-server (скачивает init-контейнер vlm-models), "
            "/models/prepare для них не поддерживается — см. scripts/vlm/"
        )
    if name not in _state:
        raise ValueError(f"Неизвестная модель: {name}")
    threading.Thread(target=_prepare, args=(name,), daemon=True).start()
