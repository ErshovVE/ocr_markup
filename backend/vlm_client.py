"""Тонкий OpenAI-совместимый HTTP-клиент к VLM-движкам.

Единственная новая зависимость backend'а для VLM-режима — httpx. Модели
поднимаются внешними сервисами (llama-server / Ollama / vLLM), клиент только
шлёт ``POST {endpoint}/v1/chat/completions`` с картинкой в ``image_url`` и
возвращает ``choices[0].message.content``.

Паттерн — как у backend/recognizers.py: свои исключения гасит, наверх не
пробрасывает, на любой ошибке возвращает ``""`` + запись в лог. Клиент
синхронный: отмену (should_cancel) обрабатывает backend/pipeline_vlm.py
снаружи — прервать уже начатый запрос нельзя, можно только больше не ждать
следующего.

Таймаут гранулярный (см. backend/config.py): read держим длинным (VLM на CPU
отвечают минутами), а connect/write/pool — короткими, чтобы молчащий после
handshake хост не держал поток job'а всё это время. На connect-ошибке и 5xx —
одна повторная попытка.
"""

import base64
import io
import json
import logging
import os
import threading
from typing import Optional, Tuple

import httpx
import numpy as np
from PIL import Image

from backend.config import (
    VLM_CONNECT_TIMEOUT_SECONDS,
    VLM_DEFAULT_ENDPOINT,
    VLM_ENDPOINT_ENV,
    VLM_ENGINE_META,
    VLM_MAX_IMAGE_SIDE,
    VLM_MAX_OUTPUT_TOKENS,
    VLM_MAX_RESPONSE_BYTES,
    VLM_REQUEST_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS = frozenset({500, 502, 503, 504})

_client_instance: Optional[httpx.Client] = None
_client_lock = threading.Lock()


def _client() -> httpx.Client:
    """Ленивый module-level httpx.Client с гранулярным таймаутом на запрос.

    Ленивая инициализация под локом — иначе два одновременных первых вызова
    (маловероятно при одном job'е за раз, но JobState-гарантия отдельная)
    создали бы два клиента и один потёк бы.
    """
    global _client_instance
    if _client_instance is None:
        with _client_lock:
            if _client_instance is None:
                _client_instance = httpx.Client(
                    timeout=httpx.Timeout(
                        connect=VLM_CONNECT_TIMEOUT_SECONDS,
                        read=VLM_REQUEST_TIMEOUT_SECONDS,
                        write=30.0,
                        pool=VLM_CONNECT_TIMEOUT_SECONDS,
                    ),
                    follow_redirects=False,
                )
    return _client_instance


def close() -> None:
    """Закрывает module-level клиент (вызывается на shutdown FastAPI)."""
    global _client_instance
    with _client_lock:
        if _client_instance is not None:
            _client_instance.close()
            _client_instance = None


def endpoint() -> str:
    """Базовый URL llama-server (router, общий для всех VLM-движков):
    VLM_ENDPOINT из окружения, иначе VLM_DEFAULT_ENDPOINT."""
    return (os.environ.get(VLM_ENDPOINT_ENV, "") or VLM_DEFAULT_ENDPOINT).rstrip("/")


def downscale_page(image) -> np.ndarray:
    """np.ndarray | PIL.Image → np.ndarray (RGB) с длинной стороной <=
    VLM_MAX_IMAGE_SIDE.

    Вызывается в backend/pipeline_vlm.py ДО прогонки страницы через движки,
    чтобы модель, парсер боксов и вырезание кропа работали в одной системе
    координат: раньше даунскейл жил только внутри _encode_image, модель
    возвращала пиксели в уменьшенном пространстве, а кроп резался из
    полноразмерного массива — боксы съезжали на любой странице > 2048px.
    """
    pil = Image.fromarray(image) if isinstance(image, np.ndarray) else image
    pil = pil.convert("RGB")
    longest = max(pil.size)
    if longest > VLM_MAX_IMAGE_SIDE:
        scale = VLM_MAX_IMAGE_SIDE / longest
        new_size = (max(1, round(pil.size[0] * scale)), max(1, round(pil.size[1] * scale)))
        pil = pil.resize(new_size)
    return np.array(pil)


def _encode_image(image) -> str:
    """np.ndarray | PIL.Image → data:image/webp;base64,...

    Страница обычно уже приведена к <= VLM_MAX_IMAGE_SIDE в pipeline_vlm
    (downscale_page); здесь тот же зажим остаётся как страховка (например,
    для крупных region-кропов layout-стратегии, которые режутся из оригинала)."""
    pil = Image.fromarray(downscale_page(image))
    buffer = io.BytesIO()
    # quality=95: картинка идёт на вход OCR-модели, агрессивное lossy-сжатие
    # текста (дефолт webp — 80) режет мелкие буквы; lossless раздул бы запрос.
    pil.save(buffer, "WEBP", quality=95, method=4)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/webp;base64,{encoded}"


def _read_capped(response: httpx.Response) -> bytes:
    """Читает тело ответа по кускам, обрывая на VLM_MAX_RESPONSE_BYTES."""
    chunks = []
    total = 0
    for chunk in response.iter_bytes():
        total += len(chunk)
        if total > VLM_MAX_RESPONSE_BYTES:
            raise RuntimeError(f"тело ответа VLM превысило {VLM_MAX_RESPONSE_BYTES} байт")
        chunks.append(chunk)
    return b"".join(chunks)


def _post_once(url: str, payload: dict) -> str:
    """Один POST + разбор ответа. Бросает httpx-исключения / RuntimeError."""
    client = _client()
    stream = getattr(client, "stream", None)
    if stream is None:  # тестовый фейк без .stream — обычный .post
        response = client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
    else:
        with stream("POST", url, json=payload) as response:
            response.raise_for_status()
            data = json.loads(_read_capped(response))
    return data["choices"][0]["message"]["content"] or ""


def _error_reason(error: Exception) -> str:
    """Короткая причина ошибки для UI — без URL сервиса (его не показываем
    наружу, см. M8 в backend/models_status.py); детали — в лог сервера."""
    if isinstance(error, httpx.HTTPStatusError):
        return f"HTTP {error.response.status_code}"
    if isinstance(error, httpx.TimeoutException):
        return "таймаут ответа модели"
    if isinstance(error, httpx.ConnectError):
        return "сервис модели недоступен"
    if isinstance(error, (KeyError, IndexError, TypeError, ValueError)):
        return "неожиданный формат ответа"
    return type(error).__name__


def chat(engine_id: str, prompt: str, image) -> str:
    """Один forward VLM по картинке. Возвращает текст ответа или ``""`` при
    любой ошибке (endpoint не задан, сеть, не-200, неожиданная форма ответа).

    На connect-ошибке / 5xx — одна повторная попытка; прочие ошибки (в т.ч.
    неожиданная форма ответа) сразу дают ``""``."""
    return chat_with_reason(engine_id, prompt, image)[0]


def chat_with_reason(engine_id: str, prompt: str, image) -> Tuple[str, Optional[str]]:
    """Как chat(), но вместе с причиной неудачи: (текст, None) или ("", причина).

    Причина уходит в on_error задания (backend/pipeline_vlm.py) — раньше в UI
    было видно только «пустой ответ», а таймаут/HTTP 404/недоступный сервис
    различались лишь в логе сервера."""
    try:
        if engine_id not in VLM_ENGINE_META:
            raise RuntimeError(f"Неизвестный VLM-движок: {engine_id}")
        url = f"{endpoint()}/v1/chat/completions"
        payload = {
            "model": VLM_ENGINE_META[engine_id]["served_model_name"],
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": _encode_image(image)}},
                    ],
                }
            ],
            "temperature": 0.0,
            "max_tokens": VLM_MAX_OUTPUT_TOKENS,
        }
        last_exc: Optional[Exception] = None
        for attempt in range(2):
            try:
                return _post_once(url, payload), None
            except httpx.HTTPStatusError as e:
                last_exc = e
                if e.response.status_code not in _RETRYABLE_STATUS:
                    raise
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as e:
                last_exc = e
            if attempt == 0:
                logger.warning("VLM %s: повтор после %s", engine_id, last_exc)
        raise last_exc  # type: ignore[misc]
    except Exception as e:  # noqa: BLE001 — как recognize_* в backend/recognizers.py
        logger.warning("Ошибка VLM %s: %s", engine_id, e)
        return "", _error_reason(e)
