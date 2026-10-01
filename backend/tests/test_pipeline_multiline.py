import numpy as np

from backend import pipeline
from backend.config import RECOGNITION_BATCH_SIZE

_BOX = [[0, 0], [30, 0], [30, 30], [0, 30]]


def _make_args(written, **overrides):
    numpy_image = np.zeros((40, 40, 3), dtype=np.uint8)
    args = dict(
        numpy_image=numpy_image,
        boxes=[_BOX],
        threshold=0.5,
        preferred_model=None,
        lang="ru",
        latin_model_size="small",
        tesseract_lang="rus",
        source_label="test.png",
        write_line=lambda bucket, crop_rel, text, crop: written.append(
            (bucket, pipeline._dataset_line(crop_rel, text, crop, False))
        ),
        allocate_crop_path=lambda: ("crops/0/image_00001.webp", "/tmp/crops/0/image_00001.webp"),
        engines=["paddle", "surya"],
        min_agree=1,
    )
    args.update(overrides)
    return args


def _const_batch(text, score=0.9):
    return lambda crops, *a: [(text, score)] * len(crops)


def _patch_engines(monkeypatch, paddle_text, surya_text):
    monkeypatch.setattr(pipeline, "recognize_paddle_batch", _const_batch(paddle_text))
    monkeypatch.setattr(pipeline, "recognize_surya_batch", _const_batch(surya_text))
    monkeypatch.setattr(pipeline, "_save_crop", lambda *a, **k: None)


def test_multiline_surya_result_is_skipped_when_surya_is_the_detector(monkeypatch):
    written, errors = [], []
    _patch_engines(monkeypatch, "одна строка", "строка1\nстрока2")

    pipeline._process_boxes(
        **_make_args(written, on_error=errors.append, detector_engine="surya"),
    )

    assert written == []
    assert len(errors) == 1
    assert "Surya" in errors[0]
    assert "test.png" in errors[0]


def test_multiline_result_is_not_skipped_when_surya_is_not_the_detector(monkeypatch):
    written, errors = [], []
    _patch_engines(monkeypatch, "одна строка", "строка1\nстрока2")

    pipeline._process_boxes(
        **_make_args(written, on_error=errors.append, detector_engine="paddle"),
    )

    assert len(written) == 1
    assert errors == []


def test_single_line_results_are_not_flagged_when_surya_is_the_detector(monkeypatch):
    written, errors = [], []
    _patch_engines(monkeypatch, "одна строка", "одна строка")

    pipeline._process_boxes(
        **_make_args(written, on_error=errors.append, detector_engine="surya"),
    )

    assert len(written) == 1
    assert errors == []


def test_lines_are_recognized_in_batches_one_call_per_engine_per_batch(monkeypatch):
    """E.14: движок получает батч кропов, а не вызов на каждую строку."""
    written, calls = [], []

    def paddle_batch(crops):
        calls.append(len(crops))
        return [(f"строка {len(calls)}", 0.9)] * len(crops)

    monkeypatch.setattr(pipeline, "recognize_paddle_batch", paddle_batch)
    monkeypatch.setattr(pipeline, "_save_crop", lambda *a, **k: None)
    line_count = RECOGNITION_BATCH_SIZE + 4
    numpy_image = np.zeros((40 * line_count, 40, 3), dtype=np.uint8)
    boxes = [[[0, 40 * i], [30, 40 * i], [30, 40 * i + 30], [0, 40 * i + 30]] for i in range(20)]

    pipeline._process_boxes(
        **_make_args(written, numpy_image=numpy_image, boxes=boxes, engines=["paddle"])
    )

    assert calls == [RECOGNITION_BATCH_SIZE, 4]
    assert len(written) == line_count


def test_all_engines_get_the_same_crops(monkeypatch):
    seen = {}

    def record(name):
        def fn(crops, *a):
            seen[name] = [c.shape for c in crops]
            return [("x", 0.9)] * len(crops)

        return fn

    monkeypatch.setattr(pipeline, "recognize_paddle_batch", record("paddle"))
    monkeypatch.setattr(pipeline, "recognize_surya_batch", record("surya"))
    monkeypatch.setattr(pipeline, "recognize_tesseract_batch", record("tesseract"))
    monkeypatch.setattr(pipeline, "_save_crop", lambda *a, **k: None)

    pipeline._process_boxes(**_make_args([], engines=["paddle", "surya", "tesseract"]))

    assert seen["paddle"] == seen["surya"] == seen["tesseract"] == [(30, 30, 3)]


def test_skewed_and_out_of_bounds_boxes_are_cropped_by_all_vertices(monkeypatch):
    """B.6: наклонный четырёхугольник Paddle и координаты за краем картинки."""
    shapes = []
    monkeypatch.setattr(pipeline, "recognize_paddle_batch", _const_batch("x"))
    monkeypatch.setattr(pipeline, "_save_crop", lambda crop, path: shapes.append(crop.shape))
    skewed = [[12, 5], [35, 2], [33, 25], [10, 28]]  # box[0]/box[2] дали бы 21x23
    out_of_bounds = [[-5, -5], [50, -5], [50, 50], [-5, 50]]

    pipeline._process_boxes(**_make_args([], boxes=[skewed, out_of_bounds], engines=["paddle"]))

    assert shapes == [(26, 25, 3), (40, 40, 3)]


def test_cancel_before_batch_stops_recognition(monkeypatch):
    calls = []
    monkeypatch.setattr(
        pipeline, "recognize_paddle_batch", lambda crops: calls.append(1) or [("x", 0.9)]
    )

    pipeline._process_boxes(**_make_args([], engines=["paddle"], should_cancel=lambda: True))

    assert calls == []
