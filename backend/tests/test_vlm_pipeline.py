"""Юнит-тесты VLM-пайплайна (backend/pipeline_vlm.py).

vlm_client.chat и _save_crop замоканы — ни сети, ни записи кропов на диск.
Native-движки в тестах — hunyuan_ocr (``текст(x1,y1),(x2,y2)``) и paddleocr_vl
("Spotting:", 4 точки); координаты обоих нормированы к [0, 1000].
"""

import json
import os

import numpy as np
import pytest
from PIL import Image

from backend import pipeline_vlm
from backend.config import VLM_MAX_IMAGE_SIDE

PAGE_W, PAGE_H = 300, 200


def _permille(x0, y0, x1, y1, w=PAGE_W, h=PAGE_H):
    return (
        round(x0 * 1000 / w),
        round(y0 * 1000 / h),
        round(x1 * 1000 / w),
        round(y1 * 1000 / h),
    )


def _hunyuan(text, x0, y0, x1, y1, w=PAGE_W, h=PAGE_H):
    """Ответ HunyuanOCR spotting для бокса в пикселях страницы w×h."""
    a, b, c, d = _permille(x0, y0, x1, y1, w, h)
    return f"{text}({a},{b}),({c},{d})"


def _paddle(text, x0, y0, x1, y1, w=PAGE_W, h=PAGE_H):
    """Ответ PaddleOCR-VL "Spotting:" для бокса в пикселях страницы w×h."""
    a, b, c, d = _permille(x0, y0, x1, y1, w, h)
    locs = "".join(f"<|LOC_{v}|>" for v in (a, b, c, b, c, d, a, d))
    return f"<|TEXT_START|>{text}<|TEXT_END|><|LOC_BEGIN|>{locs}<|LOC_END|>"


_ANSWER = _hunyuan("ПРИВЕТ МИР", 10, 10, 180, 45)
_LINE_BOX = [[0, 0], [200, 0], [200, 40], [0, 40]]


@pytest.fixture(autouse=True)
def _route_reason_calls_through_chat(monkeypatch):
    """Тесты ниже подменяют vlm_client.chat (строка ответа), а пайплайн зовёт
    chat_with_reason — направляем его через подменённый chat."""
    monkeypatch.setattr(
        pipeline_vlm.vlm_client,
        "chat_with_reason",
        lambda *a, **k: (pipeline_vlm.vlm_client.chat(*a, **k), None),
    )


def _collector():
    events = {"lines": [], "files": 0, "errors": []}

    def on_line_done(bucket, diverged):
        events["lines"].append((bucket, diverged))

    def on_file_done():
        events["files"] += 1

    def on_error(msg):
        events["errors"].append(msg)

    return events, on_line_done, on_file_done, on_error


@pytest.fixture
def one_png(tmp_path):
    Image.new("RGB", (PAGE_W, PAGE_H), "white").save(tmp_path / "page.png")
    return tmp_path


def _run(input_dir, output_dir, **overrides):
    events, on_line_done, on_file_done, on_error = _collector()
    kwargs = dict(
        vlm_engines=["hunyuan_ocr"],
        vlm_min_agree=1,
        iou_threshold=0.5,
        on_found=lambda n: events.__setitem__("found", n),
        on_file_done=on_file_done,
        on_line_done=on_line_done,
        on_error=on_error,
        should_cancel=None,
    )
    kwargs.update(overrides)
    good, review = pipeline_vlm.run(str(input_dir), str(output_dir), **kwargs)
    return events, good, review


def _no_save(monkeypatch):
    monkeypatch.setattr(pipeline_vlm, "_save_crop", lambda *a, **k: None)


def test_writes_good_line_in_crop_tab_text_format(monkeypatch, one_png, tmp_path):
    monkeypatch.setattr(pipeline_vlm.vlm_client, "chat", lambda *a, **k: _ANSWER)
    _no_save(monkeypatch)
    out = tmp_path / "out"

    events, good, review = _run(one_png, out)

    assert (good, review) == (1, 0)
    assert events["found"] == 1
    assert events["files"] == 1
    lines = (out / "good.txt").read_text(encoding="utf-8").splitlines()
    assert lines == ["crops/0/image_00001.webp\tПРИВЕТ МИР"]


def test_writes_one_debug_record_per_line(monkeypatch, one_png, tmp_path):
    monkeypatch.setattr(pipeline_vlm.vlm_client, "chat", lambda *a, **k: _ANSWER)
    _no_save(monkeypatch)
    out = tmp_path / "out"

    _run(one_png, out)

    records = [
        json.loads(line) for line in (out / "debug.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(records) == 1
    assert records[0]["engines"] == {"hunyuan_ocr": {"text": "ПРИВЕТ МИР", "score": 1.0}}


def test_empty_model_answer_triggers_on_error_and_writes_no_lines(monkeypatch, one_png, tmp_path):
    monkeypatch.setattr(pipeline_vlm.vlm_client, "chat", lambda *a, **k: "")
    _no_save(monkeypatch)
    out = tmp_path / "out"

    events, good, review = _run(one_png, out)

    assert (good, review) == (0, 0)
    assert events["errors"]
    assert (out / "good.txt").read_text(encoding="utf-8") == ""


def test_should_cancel_stops_before_any_http_call(monkeypatch, one_png, tmp_path):
    calls = []
    monkeypatch.setattr(pipeline_vlm.vlm_client, "chat", lambda *a, **k: calls.append(1) or _ANSWER)
    _no_save(monkeypatch)

    events, good, review = _run(
        one_png,
        tmp_path / "out",
        vlm_engines=["paddleocr_vl", "hunyuan_ocr"],
        should_cancel=lambda: True,
    )

    assert calls == []
    assert (good, review) == (0, 0)


def test_empty_input_dir_creates_empty_good_txt(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline_vlm.vlm_client, "chat", lambda *a, **k: _ANSWER)
    empty_in = tmp_path / "empty_in"
    os.makedirs(empty_in)
    out = tmp_path / "out"

    events, good, review = _run(empty_in, out)

    assert (good, review) == (0, 0)
    assert events["found"] == 0
    assert (out / "good.txt").exists()


def test_rejects_empty_engine_list(tmp_path):
    with pytest.raises(ValueError):
        pipeline_vlm.run(str(tmp_path), str(tmp_path / "o"), vlm_engines=[])


@pytest.mark.parametrize("engine", ["glm_ocr", "dots_ocr", "unlimited_ocr"])
def test_layout_engines_read_detector_line_crops(monkeypatch, one_png, tmp_path, engine):
    """GLM-OCR, dots.ocr и Unlimited-OCR читают кроп строки от детектора."""
    prompts = []
    monkeypatch.setattr(pipeline_vlm.vlm_layout, "region_boxes", lambda img: [_LINE_BOX])
    monkeypatch.setattr(
        pipeline_vlm.vlm_client,
        "chat",
        lambda engine_id, prompt, image: prompts.append(prompt) or "```\nтекст строки\n```",
    )
    _no_save(monkeypatch)
    out = tmp_path / "out"

    events, good, review = _run(one_png, out, vlm_engines=[engine])

    assert good == 1
    assert (out / "good.txt").read_text(encoding="utf-8").split("\t")[1].strip() == "текст строки"
    assert prompts == [pipeline_vlm.vlm_adapters.PROMPTS[engine]]


def test_paddleocr_vl_spotting_lines_are_written(monkeypatch, one_png, tmp_path):
    monkeypatch.setattr(
        pipeline_vlm.vlm_client, "chat", lambda *a, **k: _paddle("ПРИВЕТ МИР", 10, 10, 180, 45)
    )
    _no_save(monkeypatch)
    out = tmp_path / "out"

    events, good, review = _run(one_png, out, vlm_engines=["paddleocr_vl"])

    assert (good, review) == (1, 0)
    assert (out / "good.txt").read_text(encoding="utf-8").strip().endswith("\tПРИВЕТ МИР")


def test_paddleocr_vl_small_page_is_upscaled_x2_before_request(monkeypatch, one_png, tmp_path):
    """Официальная предобработка Spotting: обе стороны < 1500 → ×2."""
    shapes = []
    monkeypatch.setattr(
        pipeline_vlm.vlm_client,
        "chat",
        lambda engine_id, prompt, image: shapes.append(image.shape) or "",
    )
    _no_save(monkeypatch)

    _run(one_png, tmp_path / "out", vlm_engines=["paddleocr_vl"])

    assert shapes == [(PAGE_H * 2, PAGE_W * 2, 3)]


def test_two_engines_diverge_when_texts_differ(monkeypatch, one_png, tmp_path):
    def fake_chat(engine_id, prompt, image):
        if engine_id == "paddleocr_vl":
            return _paddle("версия А", 10, 10, 180, 45)
        return _hunyuan("версия Б", 10, 10, 180, 45)

    monkeypatch.setattr(pipeline_vlm.vlm_client, "chat", fake_chat)
    _no_save(monkeypatch)

    events, good, review = _run(
        one_png, tmp_path / "out", vlm_engines=["paddleocr_vl", "hunyuan_ocr"], vlm_min_agree=2
    )

    assert (good, review) == (0, 1)
    assert events["lines"] == [("needs_review", True)]


def test_engines_run_one_after_another_over_the_whole_folder(monkeypatch, tmp_path):
    """llama-server держит одну модель: вся папка первой моделью, потом второй —
    смен модели ровно по числу моделей, а не на каждой странице."""
    for name in ("a.png", "b.png"):
        Image.new("RGB", (PAGE_W, PAGE_H), "white").save(tmp_path / name)
    calls = []

    def fake_chat(engine_id, prompt, image):
        calls.append(engine_id)
        if engine_id == "paddleocr_vl":
            return _paddle("СТРОКА", 10, 10, 180, 45)
        return _hunyuan("СТРОКА", 10, 10, 180, 45)

    monkeypatch.setattr(pipeline_vlm.vlm_client, "chat", fake_chat)
    _no_save(monkeypatch)

    events, good, review = _run(
        tmp_path, tmp_path / "out", vlm_engines=["paddleocr_vl", "hunyuan_ocr"], vlm_min_agree=2
    )

    assert calls == ["paddleocr_vl", "paddleocr_vl", "hunyuan_ocr", "hunyuan_ocr"]
    assert (good, review) == (2, 0)
    assert events["files"] == 2


def test_tiny_box_below_min_crop_pix_is_skipped(monkeypatch, one_png, tmp_path):
    monkeypatch.setattr(pipeline_vlm.vlm_client, "chat", lambda *a, **k: _hunyuan("x", 0, 0, 5, 5))
    _no_save(monkeypatch)

    events, good, review = _run(one_png, tmp_path / "out")

    assert (good, review) == (0, 0)


def test_layout_region_without_text_reports_error(monkeypatch, one_png, tmp_path):
    monkeypatch.setattr(pipeline_vlm.vlm_layout, "region_boxes", lambda img: [_LINE_BOX])
    monkeypatch.setattr(pipeline_vlm.vlm_client, "chat", lambda *a, **k: "")
    _no_save(monkeypatch)

    events, good, review = _run(one_png, tmp_path / "out", vlm_engines=["glm_ocr"])

    assert (good, review) == (0, 0)
    assert events["errors"]


def test_unreadable_pdf_is_reported_once_and_does_not_abort_run(monkeypatch, tmp_path):
    (tmp_path / "broken.pdf").write_bytes(b"not really a pdf")
    monkeypatch.setattr(pipeline_vlm.vlm_client, "chat", lambda *a, **k: _ANSWER)

    events, good, review = _run(
        tmp_path, tmp_path / "out", vlm_engines=["paddleocr_vl", "hunyuan_ocr"]
    )

    # ошибка чтения — один раз, а не на каждый проход модели
    assert len([e for e in events["errors"] if "broken.pdf" in e]) == 1
    assert events["files"] == 1


def test_pdf_render_failure_is_reported_per_page(monkeypatch, tmp_path):
    Image.new("RGB", (200, 150), "white").save(tmp_path / "doc.pdf")

    def boom(_page):
        raise RuntimeError("render exploded")

    monkeypatch.setattr(pipeline_vlm.pdf_extract, "render_page", boom)
    monkeypatch.setattr(pipeline_vlm.vlm_client, "chat", lambda *a, **k: _ANSWER)

    events, good, review = _run(tmp_path, tmp_path / "out")

    assert (good, review) == (0, 0)
    assert any("render exploded" in msg for msg in events["errors"])


def test_engine_exception_is_reported_and_does_not_abort_the_page(monkeypatch, one_png, tmp_path):
    def fake_chat(engine_id, prompt, image):
        if engine_id == "paddleocr_vl":
            raise RuntimeError("unexpected engine crash")
        return _ANSWER

    monkeypatch.setattr(pipeline_vlm.vlm_client, "chat", fake_chat)
    _no_save(monkeypatch)

    events, good, review = _run(
        one_png, tmp_path / "out", vlm_engines=["paddleocr_vl", "hunyuan_ocr"], vlm_min_agree=1
    )

    # paddleocr_vl упал, hunyuan_ocr отработал — страница не потеряна
    assert good == 1
    assert any("unexpected engine crash" in m for m in events["errors"])


def test_out_of_bounds_bbox_is_clamped_to_the_page(monkeypatch, one_png, tmp_path):
    saved = []
    monkeypatch.setattr(
        pipeline_vlm.vlm_client, "chat", lambda *a, **k: "весь лист(0,0),(2000,2000)"
    )
    monkeypatch.setattr(pipeline_vlm, "_save_crop", lambda crop, path: saved.append(crop.shape))

    events, good, review = _run(one_png, tmp_path / "out")

    assert good == 1
    assert saved == [(PAGE_H, PAGE_W, 3)]


def test_native_boxes_align_after_page_downscale(monkeypatch, tmp_path):
    """H1-регресс: страница > VLM_MAX_IMAGE_SIDE даунскейлится для модели, а бокс
    должен попасть в ту же область оригинала. Правая половина листа чёрная;
    модель отдаёт бокс правой половины."""
    w = VLM_MAX_IMAGE_SIDE * 2  # 4096 -> после даунскейла 2048
    arr = np.full((w // 4, w, 3), 255, dtype=np.uint8)
    arr[:, w // 2 :] = 0  # правая половина — чёрная
    Image.fromarray(arr).save(tmp_path / "wide.png")

    saved = []
    monkeypatch.setattr(
        pipeline_vlm.vlm_client, "chat", lambda *a, **k: "чёрная зона(500,0),(1000,500)"
    )
    monkeypatch.setattr(pipeline_vlm, "_save_crop", lambda crop, path: saved.append(crop))

    events, good, review = _run(tmp_path, tmp_path / "out")

    assert good == 1
    assert saved and float(saved[0].mean()) < 10  # кроп попал в чёрную зону, не в белую
    # B.8: кроп режется из оригинала — правая половина листа в полном разрешении
    assert saved[0].shape[1] == w // 2


def test_duplicate_lines_across_engines_are_deduped(monkeypatch, one_png, tmp_path):
    """M18-регресс: vlm_min_agree=1 + 2 движка с почти совпадающими боксами и
    одинаковым текстом — одна строка, не две."""

    def fake_chat(engine_id, prompt, image):
        if engine_id == "paddleocr_vl":
            return _paddle("ПРИВЕТ", 10, 10, 180, 44)
        return _hunyuan("ПРИВЕТ", 12, 12, 182, 46)  # чуть смещён: IoU < 0.9, но пересекается

    monkeypatch.setattr(pipeline_vlm.vlm_client, "chat", fake_chat)
    _no_save(monkeypatch)
    out = tmp_path / "out"

    events, good, review = _run(
        one_png,
        out,
        vlm_engines=["paddleocr_vl", "hunyuan_ocr"],
        vlm_min_agree=1,
        iou_threshold=0.9,
    )

    assert (good, review) == (1, 0)
    assert len((out / "good.txt").read_text(encoding="utf-8").splitlines()) == 1


def test_pdf_pages_are_rasterised_and_processed(monkeypatch, tmp_path):
    Image.new("RGB", (PAGE_W, PAGE_H), "white").save(tmp_path / "doc.pdf")
    monkeypatch.setattr(pipeline_vlm.vlm_client, "chat", lambda *a, **k: _ANSWER)
    _no_save(monkeypatch)

    events, good, review = _run(tmp_path, tmp_path / "out")

    assert good == 1
    assert events["files"] == 1


def test_request_failure_reason_reaches_on_error(monkeypatch, one_png, tmp_path):
    """F: в UI видна причина (HTTP 404 / таймаут), а не просто «пустой ответ»."""
    monkeypatch.setattr(
        pipeline_vlm.vlm_client, "chat_with_reason", lambda *a, **k: ("", "HTTP 404")
    )

    events, good, review = _run(one_png, tmp_path / "out")

    assert (good, review) == (0, 0)
    assert any("HTTP 404" in e for e in events["errors"])


def test_unparseable_answer_is_reported_as_no_lines(monkeypatch, one_png, tmp_path):
    monkeypatch.setattr(pipeline_vlm.vlm_client, "chat", lambda *a, **k: "просто текст без боксов")

    events, _, _ = _run(one_png, tmp_path / "out")

    assert any("нет строк в ответе модели" in e for e in events["errors"])


def test_layout_detector_is_never_called_concurrently(monkeypatch, one_png, tmp_path):
    """Общий Paddle-детектор не thread-safe — vlm_layout.region_boxes
    сериализует detect() (страховка, даже если вызовы станут конкурентными)."""
    import time

    active = []
    overlaps = []

    class SlowDetector:
        def detect(self, image):
            active.append(1)
            if len(active) > 1:
                overlaps.append(True)
            time.sleep(0.05)
            active.pop()
            return [_LINE_BOX]

    pipeline_vlm.vlm_layout.set_detector(SlowDetector())
    monkeypatch.setattr(pipeline_vlm.vlm_client, "chat", lambda *a, **k: "текст")
    _no_save(monkeypatch)
    try:
        events, good, _ = _run(
            one_png, tmp_path / "out", vlm_engines=["glm_ocr", "dots_ocr"], vlm_min_agree=2
        )
    finally:
        pipeline_vlm.vlm_layout.reset()

    assert overlaps == []
    assert good == 1


def test_cancel_during_final_pass_still_writes_lines_of_earlier_models(monkeypatch, tmp_path):
    """Отмена после прохода ранней модели не теряет её строки: они пишутся без
    новых вызовов моделей (без второй модели согласия нет — needs_review)."""
    for name in ("a.png", "b.png"):
        Image.new("RGB", (PAGE_W, PAGE_H), "white").save(tmp_path / name)
    calls = []
    cancel = {"now": False}

    def fake_chat(engine_id, prompt, image):
        calls.append(engine_id)
        if engine_id == "paddleocr_vl":
            return _paddle("СТРОКА", 10, 10, 180, 45)
        cancel["now"] = True  # отмена приходит во время первого вызова последней модели
        return ""

    monkeypatch.setattr(pipeline_vlm.vlm_client, "chat", fake_chat)
    _no_save(monkeypatch)

    events, good, review = _run(
        tmp_path,
        tmp_path / "out",
        vlm_engines=["paddleocr_vl", "hunyuan_ocr"],
        vlm_min_agree=2,
        should_cancel=lambda: cancel["now"],
    )

    assert calls == ["paddleocr_vl", "paddleocr_vl", "hunyuan_ocr"]
    assert (good, review) == (0, 2)


def test_paddleocr_vl_upscale_is_capped_in_one_lanczos_resize(monkeypatch, tmp_path):
    """1400x1000 → ×2 было бы 2800 px; сразу ограничиваем VLM_MAX_IMAGE_SIDE,
    чтобы клиент не ужимал картинку второй раз другим фильтром."""
    Image.new("RGB", (1400, 1000), "white").save(tmp_path / "page.png")
    shapes = []
    monkeypatch.setattr(
        pipeline_vlm.vlm_client,
        "chat",
        lambda engine_id, prompt, image: shapes.append(image.shape) or "",
    )

    _run(tmp_path, tmp_path / "out", vlm_engines=["paddleocr_vl"])

    assert shapes == [(1463, VLM_MAX_IMAGE_SIDE, 3)]
