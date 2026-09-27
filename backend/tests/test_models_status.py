from unittest.mock import MagicMock, patch

import pytest

from backend import models_status


@pytest.fixture(autouse=True)
def reset_model_state():
    """Изолирует тесты друг от друга — _state общий module-level словарь"""
    state = {
        "paddle": models_status.ModelState(),
        "surya": models_status.ModelState(),
        "paddle_detector": models_status.ModelState(),
        "surya_detector": models_status.ModelState(),
    }
    models_status._state = dict(state)
    models_status._vlm_cache = ()
    yield
    models_status._state = dict(state)
    models_status._vlm_cache = ()


def test_check_tesseract_missing_binary():
    with patch("shutil.which", return_value=None):
        state = models_status.check_tesseract()
    assert state.status == "error"


def test_check_tesseract_missing_rus_lang():
    with (
        patch("shutil.which", return_value="/usr/bin/tesseract"),
        patch("subprocess.run", return_value=MagicMock(stdout="eng\n")),
    ):
        state = models_status.check_tesseract()
    assert state.status == "error"


def test_check_tesseract_ready():
    with (
        patch("shutil.which", return_value="/usr/bin/tesseract"),
        patch("subprocess.run", return_value=MagicMock(stdout="eng\nrus\n")),
    ):
        state = models_status.check_tesseract()
    assert state.status == "ready"


def test_prepare_success_sets_ready():
    with patch("backend.recognizers._Engines.paddle_cyrillic", return_value=object()):
        models_status._prepare("paddle")
    assert models_status._state["paddle"].status == "ready"


def test_prepare_failure_sets_error_with_detail():
    with patch("backend.recognizers._Engines.paddle_cyrillic", side_effect=RuntimeError("boom")):
        models_status._prepare("paddle")
    assert models_status._state["paddle"].status == "error"
    assert "boom" in models_status._state["paddle"].detail


def test_prepare_unknown_model_raises():
    with pytest.raises(ValueError):
        models_status.prepare("unknown")


def test_prepare_detector_success_sets_ready():
    with patch("backend.detector._Engines.paddle", return_value=object()):
        models_status._prepare("paddle_detector")
    assert models_status._state["paddle_detector"].status == "ready"


def test_prepare_detector_failure_sets_error_with_detail():
    with patch("backend.detector._Engines.surya", side_effect=RuntimeError("boom")):
        models_status._prepare("surya_detector")
    assert models_status._state["surya_detector"].status == "error"
    assert "boom" in models_status._state["surya_detector"].detail


def test_get_status_exposes_vlm_keys(monkeypatch):
    with patch("httpx.get", side_effect=RuntimeError("x")):
        status = models_status.get_status()
    assert {"vlm_dots_ocr", "vlm_glm_ocr", "vlm_paddleocr_vl"} <= set(status)


def test_get_status_skips_vlm_probes_when_not_requested():
    with patch("httpx.get", side_effect=AssertionError("should not be called")):
        status = models_status.get_status(include_vlm=False)
    assert not any(k.startswith("vlm_") for k in status)


def test_prepare_rejects_vlm_models():
    with pytest.raises(ValueError):
        models_status.prepare("vlm_dots_ocr")


def test_check_vlm_endpoint_error_for_unknown_engine():
    with patch("httpx.get", side_effect=RuntimeError("x")):
        assert models_status.check_vlm_endpoint("no_such_engine").status == "error"


def _router_response(*entries):
    """Ответ GET /v1/models llama-server в router-режиме: пресеты со статусом."""
    response = MagicMock()
    response.json.return_value = {
        "object": "list",
        "data": [{"id": model_id, "status": status} for model_id, status in entries],
    }
    return response


def test_vlm_status_ready_for_loaded_and_unloaded_presets(monkeypatch):
    monkeypatch.setenv("VLM_ENDPOINT", "http://llama-vlm:8080")
    response = _router_response(
        ("hunyuan-ocr", {"value": "loaded"}), ("glm-ocr", {"value": "unloaded"})
    )
    with patch("httpx.get", return_value=response) as get:
        status = models_status.get_status()

    get.assert_called_once()  # один запрос на все VLM-движки
    assert get.call_args.args[0] == "http://llama-vlm:8080/v1/models"
    assert status["vlm_hunyuan_ocr"].status == "ready"
    assert status["vlm_hunyuan_ocr"].detail is None
    assert status["vlm_glm_ocr"].status == "ready"
    assert "первом запросе" in status["vlm_glm_ocr"].detail


def test_vlm_status_error_for_missing_or_failed_preset():
    response = _router_response(("dots-ocr", {"value": "unloaded", "failed": True}))
    with patch("httpx.get", return_value=response):
        status = models_status.get_status()

    assert status["vlm_dots_ocr"].status == "error"
    assert "не загрузилась" in status["vlm_dots_ocr"].detail
    assert status["vlm_paddleocr_vl"].status == "error"
    assert "пресетах" in status["vlm_paddleocr_vl"].detail


def test_vlm_status_error_when_server_unreachable_without_leaking_url():
    with patch("httpx.get", side_effect=RuntimeError("connection refused to http://secret:8080")):
        state = models_status.check_vlm_endpoint("dots_ocr")

    assert state.status == "error"
    assert state.detail == "эндпоинт недоступен"


def test_vlm_status_is_cached_between_requests():
    response = _router_response(("hunyuan-ocr", {"value": "loaded"}))
    with patch("httpx.get", return_value=response) as get:
        models_status.get_status()
        models_status.get_status()

    get.assert_called_once()
