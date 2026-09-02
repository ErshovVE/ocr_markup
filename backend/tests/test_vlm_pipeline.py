"""Юнит-тесты VLM-пайплайна (backend/pipeline_vlm.py).

vlm_client.chat и _save_crop замоканы — ни сети, ни записи кропов на диск.
"""

import json
import os

import pytest
from PIL import Image

from backend import pipeline_vlm

_DOTS_ANSWER = '[{"bbox": [10, 10, 180, 45], "category": "Text", "text": "ПРИВЕТ МИР"}]'


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
    Image.new("RGB", (300, 200), "white").save(tmp_path / "page.png")
    return tmp_path


def _run(input_dir, output_dir, **overrides):
    events, on_line_done, on_file_done, on_error = _collector()
    kwargs = dict(
        vlm_engines=["dots_ocr"],
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


def test_writes_good_line_in_crop_tab_text_format(monkeypatch, one_png, tmp_path):
    monkeypatch.setattr(pipeline_vlm.vlm_client, "chat", lambda *a, **k: _DOTS_ANSWER)
    monkeypatch.setattr(pipeline_vlm, "_save_crop", lambda *a, **k: None)
    out = tmp_path / "out"

    events, good, review = _run(one_png, out)

    assert (good, review) == (1, 0)
    assert events["found"] == 1
    assert events["files"] == 1
    lines = (out / "good.txt").read_text(encoding="utf-8").splitlines()
    assert lines == ["crops/0/image_00001.webp\tПРИВЕТ МИР"]


def test_writes_one_debug_record_per_line(monkeypatch, one_png, tmp_path):
    monkeypatch.setattr(pipeline_vlm.vlm_client, "chat", lambda *a, **k: _DOTS_ANSWER)
    monkeypatch.setattr(pipeline_vlm, "_save_crop", lambda *a, **k: None)
    out = tmp_path / "out"

    _run(one_png, out)

    records = [
        json.loads(line) for line in (out / "debug.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(records) == 1
    assert records[0]["engines"] == {"dots_ocr": {"text": "ПРИВЕТ МИР", "score": 1.0}}


def test_empty_model_answer_triggers_on_error_and_writes_no_lines(monkeypatch, one_png, tmp_path):
    monkeypatch.setattr(pipeline_vlm.vlm_client, "chat", lambda *a, **k: "")
    monkeypatch.setattr(pipeline_vlm, "_save_crop", lambda *a, **k: None)
    out = tmp_path / "out"

    events, good, review = _run(one_png, out)

    assert (good, review) == (0, 0)
    assert events["errors"]
    assert (out / "good.txt").read_text(encoding="utf-8") == ""


def test_should_cancel_stops_before_any_http_call(monkeypatch, one_png, tmp_path):
    calls = []
    monkeypatch.setattr(
        pipeline_vlm.vlm_client, "chat", lambda *a, **k: calls.append(1) or _DOTS_ANSWER
    )
    monkeypatch.setattr(pipeline_vlm, "_save_crop", lambda *a, **k: None)
    out = tmp_path / "out"

    events, good, review = _run(one_png, out, should_cancel=lambda: True)

    assert calls == []
    assert (good, review) == (0, 0)


def test_empty_input_dir_creates_empty_good_txt(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline_vlm.vlm_client, "chat", lambda *a, **k: _DOTS_ANSWER)
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


def test_layout_strategy_slices_page_into_regions(monkeypatch, one_png, tmp_path):
    monkeypatch.setattr(
        pipeline_vlm.vlm_layout,
        "merged_region_boxes",
        lambda img: [[[0, 0], [200, 0], [200, 40], [0, 40]]],
    )
    monkeypatch.setattr(pipeline_vlm.vlm_client, "chat", lambda *a, **k: "```\nтекст региона\n```")
    monkeypatch.setattr(pipeline_vlm, "_save_crop", lambda *a, **k: None)
    out = tmp_path / "out"

    events, good, review = _run(one_png, out, vlm_engines=["glm_ocr"])

    assert good == 1
    assert (out / "good.txt").read_text(encoding="utf-8").split("\t")[1].strip() == "текст региона"


def test_two_engines_diverge_when_texts_differ(monkeypatch, one_png, tmp_path):
    def fake_chat(engine_id, prompt, image):
        if engine_id == "dots_ocr":
            return '[{"bbox": [10, 10, 180, 45], "category": "Text", "text": "версия А"}]'
        return "версия Б(10,10),(180,45)"

    monkeypatch.setattr(pipeline_vlm.vlm_client, "chat", fake_chat)
    monkeypatch.setattr(pipeline_vlm, "_save_crop", lambda *a, **k: None)
    out = tmp_path / "out"

    events, good, review = _run(
        one_png, out, vlm_engines=["dots_ocr", "hunyuan_ocr"], vlm_min_agree=2
    )

    assert (good, review) == (0, 1)
    assert events["lines"] == [("needs_review", True)]


def test_tiny_box_below_min_crop_pix_is_skipped(monkeypatch, one_png, tmp_path):
    monkeypatch.setattr(
        pipeline_vlm.vlm_client,
        "chat",
        lambda *a, **k: '[{"bbox": [0, 0, 5, 5], "category": "Text", "text": "x"}]',
    )
    monkeypatch.setattr(pipeline_vlm, "_save_crop", lambda *a, **k: None)
    out = tmp_path / "out"

    events, good, review = _run(one_png, out)

    assert (good, review) == (0, 0)


def test_layout_region_without_text_reports_error(monkeypatch, one_png, tmp_path):
    monkeypatch.setattr(
        pipeline_vlm.vlm_layout,
        "merged_region_boxes",
        lambda img: [[[0, 0], [200, 0], [200, 40], [0, 40]]],
    )
    monkeypatch.setattr(pipeline_vlm.vlm_client, "chat", lambda *a, **k: "")
    monkeypatch.setattr(pipeline_vlm, "_save_crop", lambda *a, **k: None)
    out = tmp_path / "out"

    events, good, review = _run(one_png, out, vlm_engines=["glm_ocr"])

    assert (good, review) == (0, 0)
    assert events["errors"]


def test_unreadable_pdf_is_reported_and_does_not_abort_run(monkeypatch, tmp_path):
    (tmp_path / "broken.pdf").write_bytes(b"not really a pdf")
    monkeypatch.setattr(pipeline_vlm.vlm_client, "chat", lambda *a, **k: _DOTS_ANSWER)
    out = tmp_path / "out"

    events, good, review = _run(tmp_path, out)

    assert events["errors"]
    assert events["files"] == 1


def test_pdf_render_failure_is_reported_per_page(monkeypatch, tmp_path):
    Image.new("RGB", (200, 150), "white").save(tmp_path / "doc.pdf")

    def boom(_page):
        raise RuntimeError("render exploded")

    monkeypatch.setattr(pipeline_vlm.pdf_extract, "render_page", boom)
    monkeypatch.setattr(pipeline_vlm.vlm_client, "chat", lambda *a, **k: _DOTS_ANSWER)
    out = tmp_path / "out"

    events, good, review = _run(tmp_path, out)

    assert (good, review) == (0, 0)
    assert any("render exploded" in msg for msg in events["errors"])


def test_engine_exception_is_reported_and_does_not_abort_the_page(monkeypatch, one_png, tmp_path):
    def fake_chat(engine_id, prompt, image):
        if engine_id == "dots_ocr":
            raise RuntimeError("unexpected engine crash")
        return "нормальный(10,10),(180,45)"

    monkeypatch.setattr(pipeline_vlm.vlm_client, "chat", fake_chat)
    monkeypatch.setattr(pipeline_vlm, "_save_crop", lambda *a, **k: None)
    out = tmp_path / "out"

    events, good, review = _run(
        one_png, out, vlm_engines=["dots_ocr", "hunyuan_ocr"], vlm_min_agree=1
    )

    # dots_ocr упал, hunyuan_ocr отработал — страница не потеряна
    assert good == 1
    assert any("unexpected engine crash" in m for m in events["errors"])


def test_out_of_bounds_bbox_is_clamped_not_wrapped(monkeypatch, one_png, tmp_path):
    saved = []
    answer = '[{"bbox": [-50, -20, 5000, 5000], "category": "Text", "text": "весь лист"}]'
    monkeypatch.setattr(pipeline_vlm.vlm_client, "chat", lambda *a, **k: answer)
    monkeypatch.setattr(pipeline_vlm, "_save_crop", lambda crop, path: saved.append(crop.shape))
    out = tmp_path / "out"

    events, good, review = _run(one_png, out)

    assert good == 1
    # 300x200 png → кроп зажат в границы страницы, без обёртки отрицательных индексов
    assert saved == [(200, 300, 3)]


def test_pdf_pages_are_rasterised_and_processed(monkeypatch, tmp_path):
    Image.new("RGB", (300, 200), "white").save(tmp_path / "doc.pdf")
    monkeypatch.setattr(pipeline_vlm.vlm_client, "chat", lambda *a, **k: _DOTS_ANSWER)
    monkeypatch.setattr(pipeline_vlm, "_save_crop", lambda *a, **k: None)
    out = tmp_path / "out"

    events, good, review = _run(tmp_path, out)

    assert good == 1
    assert events["files"] == 1
