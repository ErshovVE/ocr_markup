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
    yield
    models_status._state = dict(state)


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
