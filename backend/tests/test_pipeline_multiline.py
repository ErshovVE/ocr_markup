import numpy as np
from PIL import Image

from backend import pipeline

_BOX = [[0, 0], [30, 0], [30, 30], [0, 30]]


def _make_args(**overrides):
    numpy_image = np.zeros((40, 40, 3), dtype=np.uint8)
    args = dict(
        image=Image.fromarray(numpy_image),
        numpy_image=numpy_image,
        boxes=[_BOX],
        threshold=0.5,
        preferred_model=None,
        lang="ru",
        latin_model_size="small",
        tesseract_lang="rus",
        source_label="test.png",
        write_line=lambda bucket, line: written.append((bucket, line)),
        allocate_crop_path=lambda: ("crops/0/image_00001.webp", "/tmp/crops/0/image_00001.webp"),
        engines=["paddle", "surya"],
        min_agree=1,
    )
    args.update(overrides)
    return args


written = []


def test_multiline_surya_result_is_skipped_when_surya_is_the_detector(monkeypatch, tmp_path):
    global written
    written = []
    errors = []
    monkeypatch.setattr(pipeline, "recognize_paddle", lambda crop: ("одна строка", 0.9))
    monkeypatch.setattr(pipeline, "recognize_surya", lambda image, box: ("строка1\nстрока2", 0.9))
    monkeypatch.setattr(pipeline, "_save_crop", lambda *a, **k: None)

    pipeline._process_boxes(
        **_make_args(on_error=errors.append, detector_engine="surya"),
    )

    assert written == []
    assert len(errors) == 1
    assert "Surya" in errors[0]
    assert "test.png" in errors[0]


def test_multiline_result_is_not_skipped_when_surya_is_not_the_detector(monkeypatch):
    global written
    written = []
    errors = []
    monkeypatch.setattr(pipeline, "recognize_paddle", lambda crop: ("одна строка", 0.9))
    monkeypatch.setattr(pipeline, "recognize_surya", lambda image, box: ("строка1\nстрока2", 0.9))
    monkeypatch.setattr(pipeline, "_save_crop", lambda *a, **k: None)

    pipeline._process_boxes(
        **_make_args(on_error=errors.append, detector_engine="paddle"),
    )

    assert len(written) == 1
    assert errors == []


def test_single_line_results_are_not_flagged_when_surya_is_the_detector(monkeypatch):
    global written
    written = []
    errors = []
    monkeypatch.setattr(pipeline, "recognize_paddle", lambda crop: ("одна строка", 0.9))
    monkeypatch.setattr(pipeline, "recognize_surya", lambda image, box: ("одна строка", 0.9))
    monkeypatch.setattr(pipeline, "_save_crop", lambda *a, **k: None)

    pipeline._process_boxes(
        **_make_args(on_error=errors.append, detector_engine="surya"),
    )

    assert len(written) == 1
    assert errors == []
