"""Тонкий OpenAI-совместимый HTTP-клиент к VLM-движкам.

Единственная новая зависимость backend'а для VLM-режима — httpx. Модели
поднимаются внешними сервисами (llama-server / Ollama / vLLM), клиент только
шлёт ``POST {endpoint}/v1/chat/completions`` с картинкой в ``image_url`` и
возвращает ``choices[0].message.content``.

Паттерн — как у backend/recognizers.py: свои исключения гасит, наверх не
пробрасывает, на любой ошибке возвращает ``""`` + ``print``. Клиент
синхронный: отмену (should_cancel) обрабатывает backend/pipeline_vlm.py
снаружи — прервать уже начатый запрос нельзя, можно только больше не ждать
следующего.
"""

import base64
import io
import os
from typing import Optional

import httpx
import numpy as np
from PIL import Image

from backend.config import (
    VLM_ENGINE_META,
    VLM_MAX_IMAGE_SIDE,
    VLM_MAX_OUTPUT_TOKENS,
    VLM_REQUEST_TIMEOUT_SECONDS,
)

_client_instance: Optional[httpx.Client] = None


def _client() -> httpx.Client:
    """Ленивый module-level httpx.Client с общим таймаутом на запрос."""
    global _client_instance
    if _client_instance is None:
        _client_instance = httpx.Client(timeout=VLM_REQUEST_TIMEOUT_SECONDS)
    return _client_instance


def _endpoint(engine_id: str) -> str:
    """Базовый URL сервиса движка: из переменной окружения, иначе дефолт из
    config. Пусто → RuntimeError (ловится в chat() и уходит в ``""``)."""
    meta = VLM_ENGINE_META.get(engine_id)
    if meta is None:
        raise RuntimeError(f"Неизвестный VLM-движок: {engine_id}")
    endpoint = os.environ.get(meta["endpoint_env"], "") or meta.get("default_endpoint", "")
    if not endpoint:
        raise RuntimeError(f"{meta['endpoint_env']} не задан для движка {engine_id}")
    return endpoint.rstrip("/")


def _encode_image(image) -> str:
    """np.ndarray | PIL.Image → data:image/webp;base64,... с даунскейлом самой
    длинной стороны до VLM_MAX_IMAGE_SIDE."""
    pil = Image.fromarray(image) if isinstance(image, np.ndarray) else image
    pil = pil.convert("RGB")
    longest = max(pil.size)
    if longest > VLM_MAX_IMAGE_SIDE:
        scale = VLM_MAX_IMAGE_SIDE / longest
        new_size = (max(1, round(pil.size[0] * scale)), max(1, round(pil.size[1] * scale)))
        pil = pil.resize(new_size)
    buffer = io.BytesIO()
    # quality=95: картинка идёт на вход OCR-модели, агрессивное lossy-сжатие
    # текста (дефолт webp — 80) режет мелкие буквы; lossless раздул бы запрос.
    pil.save(buffer, "WEBP", quality=95, method=4)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/webp;base64,{encoded}"


def chat(engine_id: str, prompt: str, image) -> str:
    """Один forward VLM по картинке. Возвращает текст ответа или ``""`` при
    любой ошибке (endpoint не задан, сеть, не-200, неожиданная форма ответа)."""
    try:
        endpoint = _endpoint(engine_id)
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
        response = _client().post(f"{endpoint}/v1/chat/completions", json=payload)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"] or ""
    except Exception as e:
        print(f"Ошибка VLM {engine_id}: {e}")
        return ""
