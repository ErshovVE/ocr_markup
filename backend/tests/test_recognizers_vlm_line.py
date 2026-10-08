"""recognize_vlm_line_batch / recognize_custom_batch без сети и без моделей:
vlm_client.chat_with_reason и _Engines.custom подменены."""

import numpy as np

from backend import recognizers


def _crops(n):
    return [np.full((20, 40 + i, 3), i, dtype=np.uint8) for i in range(n)]


def test_vlm_line_batch_order_and_empty(monkeypatch):
    seen = []

    def fake_chat(engine_id, prompt, crop, downscale=True):
        seen.append((engine_id, prompt, downscale))
        width = crop.shape[1]
        return ("" if width == 41 else f"строка {width}\n"), None

    monkeypatch.setattr(recognizers.vlm_client, "chat_with_reason", fake_chat)

    results = recognizers.recognize_vlm_line_batch(_crops(3), "glm_ocr")

    assert results == [("строка 40", 1.0), ("", 0.0), ("строка 42", 1.0)]
    assert all(e == "glm_ocr" and p == "Text Recognition:" and d is False for e, p, d in seen)


def test_vlm_line_batch_reports_failures_once_per_batch(monkeypatch):
    monkeypatch.setattr(
        recognizers.vlm_client,
        "chat_with_reason",
        lambda *a, **k: ("", "сервис недоступен"),
    )
    errors = []

    results = recognizers.recognize_vlm_line_batch(_crops(4), "glm_ocr", errors.append)

    assert results == [("", 0.0)] * 4
    assert errors == ["VLM glm_ocr: 4 из 4 строк без ответа: сервис недоступен"]


def test_vlm_line_batch_unknown_engine_gives_empty(monkeypatch):
    assert recognizers.recognize_vlm_line_batch(_crops(2), "hunyuan_ocr") == [("", 0.0)] * 2


def test_custom_batch_uses_model_dir_and_empty_on_load_error(monkeypatch):
    class _Predictor:
        def predict(self, crops, batch_size):
            return [{"rec_text": "ок", "rec_score": 0.8} for _ in crops]

    dirs = []
    monkeypatch.setattr(
        recognizers._Engines, "custom", classmethod(lambda cls, d: dirs.append(d) or _Predictor())
    )
    assert recognizers.recognize_custom_batch(_crops(2), "/m") == [("ок", 0.8)] * 2
    assert dirs == ["/m"]

    def boom(cls, d):
        raise RuntimeError("нет inference.yml")

    monkeypatch.setattr(recognizers._Engines, "custom", classmethod(boom))
    assert recognizers.recognize_custom_batch(_crops(2), "/m") == [("", 0.0)] * 2


def test_custom_cache_keeps_only_last_model_dir(monkeypatch):
    import sys
    import types

    created = []

    class _FakeTextRecognition:
        def __init__(self, model_dir, enable_mkldnn):
            created.append(model_dir)

    monkeypatch.setitem(
        sys.modules, "paddleocr", types.SimpleNamespace(TextRecognition=_FakeTextRecognition)
    )
    monkeypatch.setattr(recognizers._Engines, "_custom", None)

    first = recognizers._Engines.custom("/a")
    assert recognizers._Engines.custom("/a") is first
    recognizers._Engines.custom("/b")
    recognizers._Engines.custom("/a")

    assert created == ["/a", "/b", "/a"]
    assert recognizers._Engines._custom[0] == "/a"
