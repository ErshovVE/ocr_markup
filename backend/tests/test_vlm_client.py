"""Юнит-тесты HTTP-клиента VLM (backend/vlm_client.py) — httpx замокан."""

import base64
import io

import numpy as np
import pytest
from PIL import Image

from backend import vlm_client
from backend.config import VLM_MAX_IMAGE_SIDE


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, payload=None, error=None):
        self._payload = payload
        self._error = error
        self.calls = []

    def post(self, url, json):  # noqa: A002 — сигнатура httpx.Client.post
        self.calls.append((url, json))
        if self._error is not None:
            raise self._error
        return _FakeResponse(self._payload)


@pytest.fixture(autouse=True)
def _reset_client():
    vlm_client._client_instance = None
    yield
    vlm_client._client_instance = None


def test_chat_returns_message_content(monkeypatch):
    fake = _FakeClient(payload={"choices": [{"message": {"content": "распознанный текст"}}]})
    monkeypatch.setattr(vlm_client, "_client", lambda: fake)

    result = vlm_client.chat("dots_ocr", "prompt", np.zeros((20, 20, 3), dtype=np.uint8))

    assert result == "распознанный текст"
    assert fake.calls[0][0].endswith("/v1/chat/completions")


def test_chat_swallows_network_error(monkeypatch, capsys):
    fake = _FakeClient(error=ConnectionError("boom"))
    monkeypatch.setattr(vlm_client, "_client", lambda: fake)

    result = vlm_client.chat("dots_ocr", "prompt", np.zeros((20, 20, 3), dtype=np.uint8))

    assert result == ""
    assert "Ошибка VLM dots_ocr" in capsys.readouterr().out


def test_chat_returns_empty_on_unexpected_payload_shape(monkeypatch):
    monkeypatch.setattr(vlm_client, "_client", lambda: _FakeClient(payload={"nope": 1}))

    assert vlm_client.chat("dots_ocr", "p", np.zeros((5, 5, 3), dtype=np.uint8)) == ""


def test_encode_image_emits_webp_data_uri():
    uri = vlm_client._encode_image(np.zeros((10, 10, 3), dtype=np.uint8))

    assert uri.startswith("data:image/webp;base64,")


def test_encode_image_downscales_when_longer_than_max_side():
    tall = np.zeros((VLM_MAX_IMAGE_SIDE * 2, 100, 3), dtype=np.uint8)

    uri = vlm_client._encode_image(tall)

    raw = base64.b64decode(uri.split(",", 1)[1])
    decoded = Image.open(io.BytesIO(raw))
    assert max(decoded.size) <= VLM_MAX_IMAGE_SIDE
