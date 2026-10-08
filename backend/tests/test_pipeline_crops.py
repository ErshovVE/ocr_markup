"""Режим готовых кропов (backend/pipeline_crops.py) на моках движков:
recognize_*_batch подменены в backend.pipeline (там их зовёт _recognize_batch)."""

import json

import numpy as np
import pytest
from PIL import Image

from backend import pipeline, pipeline_crops
from backend.config import RECOGNITION_BATCH_SIZE
from backend.pipeline import RecognitionOptions


def _const_batch(text, score=0.9):
    return lambda crops, *a: [(text, score)] * len(crops)


def _patch(monkeypatch, **engine_texts):
    names = {
        "paddle": "recognize_paddle_batch",
        "surya": "recognize_surya_batch",
        "custom": "recognize_custom_batch",
        "vlm_line": "recognize_vlm_line_batch",
    }
    for engine, text in engine_texts.items():
        fn = text if callable(text) else _const_batch(text)
        monkeypatch.setattr(pipeline, names[engine], fn)


@pytest.fixture
def dataset(tmp_path):
    """Корень кропов с 3 картинками и файл меток к ним."""
    root = tmp_path / "data"
    (root / "crops" / "0").mkdir(parents=True)
    paths = []
    for i in range(3):
        rel = f"crops/0/image_{i}.png"
        Image.fromarray(np.full((20, 50 + i, 3), 255, dtype=np.uint8)).save(root / rel)
        paths.append(rel)
    labels = tmp_path / "labels.txt"
    labels.write_text(
        "".join(f"{p}\tметка {i}\t{50 + i}\t20\n" for i, p in enumerate(paths)), encoding="utf-8"
    )
    return {"root": str(root), "labels": str(labels), "paths": paths, "out": tmp_path / "out"}


def _run(dataset, **kwargs):
    args = dict(
        label_file=dataset["labels"],
        data_dir=dataset["root"],
        output_dir=str(dataset["out"]),
        threshold=0.5,
        engines=["custom", "surya", "vlm_line"],
        min_agree=2,
        options=RecognitionOptions(custom_model_dir="/m", line_vlm_engine="glm_ocr"),
    )
    args.update(kwargs)
    return pipeline_crops.run(**args)


def _lines(dataset, name):
    return (dataset["out"] / name).read_text(encoding="utf-8").splitlines()


def test_crops_run_writes_original_paths(monkeypatch, dataset):
    _patch(monkeypatch, custom="2.5.1", surya="2.5.1", vlm_line="2.8.1")

    assert _run(dataset) == (3, 0)

    assert _lines(dataset, "good.txt") == [f"{p}\t2.5.1" for p in dataset["paths"]]
    assert _lines(dataset, "needs_review.txt") == []
    assert not (dataset["out"] / "crops").exists()


def test_crops_run_vote_key_no_spaces(monkeypatch, dataset):
    _patch(monkeypatch, custom="2.5.1", surya="2 .5 .1", vlm_line="2.8.1")

    assert _run(dataset, options=RecognitionOptions(vote_key="no_spaces")) == (3, 0)
    assert _run(dataset) == (0, 3)


def test_crops_run_needs_review_without_agreement(monkeypatch, dataset):
    _patch(monkeypatch, custom="а", surya="б", vlm_line="в")

    assert _run(dataset, preferred_model="surya") == (0, 3)

    assert _lines(dataset, "needs_review.txt")[0] == f"{dataset['paths'][0]}\tб"


def test_crops_run_label_votes(monkeypatch, dataset):
    surya = lambda crops, *a: [("метка 0", 0.9)] + [("x", 0.9)] * (len(crops) - 1)  # noqa: E731
    _patch(monkeypatch, custom="другое", surya=surya)

    good, review = _run(dataset, engines=["custom", "surya"], label_votes=True)

    assert (good, review) == (1, 2)
    assert _lines(dataset, "good.txt") == [f"{dataset['paths'][0]}\tметка 0"]


def test_crops_debug_has_label_and_engines(monkeypatch, dataset):
    _patch(monkeypatch, custom="а", surya="а")

    _run(dataset, engines=["custom", "surya"], label_votes=True)

    record = json.loads(_lines(dataset, "debug.jsonl")[0])
    assert record["crop"] == dataset["paths"][0]
    assert record["label"] == "метка 0"
    assert record["bucket"] == "good"
    assert set(record["engines"]) == {"custom", "surya"}


def test_crops_run_append_crop_size_from_image(monkeypatch, dataset):
    _patch(monkeypatch, custom="а", surya="а")

    _run(dataset, engines=["custom", "surya"], append_crop_size=True)

    assert _lines(dataset, "good.txt")[1] == f"{dataset['paths'][1]}\tа\t51\t20"


def test_crops_run_text_with_tab_or_newline_keeps_tsv(monkeypatch, dataset):
    _patch(monkeypatch, custom="а\tб\nв", surya="а\tб\nв")

    _run(dataset, engines=["custom", "surya"])

    assert _lines(dataset, "good.txt")[0] == f"{dataset['paths'][0]}\tа б в"


def test_crops_run_missing_image(monkeypatch, dataset):
    with open(dataset["labels"], "a", encoding="utf-8") as f:
        f.write("crops/0/nope.png\tметка\n")
    _patch(monkeypatch, custom="а", surya="а")
    errors = []

    assert _run(dataset, engines=["custom", "surya"], on_error=errors.append) == (3, 0)
    assert any("nope.png" in e for e in errors)


def test_crops_run_rejects_path_outside_data_dir(monkeypatch, dataset, tmp_path):
    Image.fromarray(np.zeros((20, 50, 3), dtype=np.uint8)).save(tmp_path / "outside.png")
    with open(dataset["labels"], "a", encoding="utf-8") as f:
        f.write("../outside.png\tметка\n")
    _patch(monkeypatch, custom="а", surya="а")
    errors = []

    assert _run(dataset, engines=["custom", "surya"], on_error=errors.append) == (3, 0)
    assert any("outside.png" in e and "вне" in e for e in errors)


def test_crops_run_bad_label_line(monkeypatch, dataset):
    with open(dataset["labels"], "a", encoding="utf-8") as f:
        f.write("строка без таба\n\n")
    _patch(monkeypatch, custom="а", surya="а")
    errors = []

    assert _run(dataset, engines=["custom", "surya"], on_error=errors.append) == (3, 0)
    assert len(errors) == 1 and ":4:" in errors[0]


def test_crops_run_empty_label_file(monkeypatch, dataset):
    open(dataset["labels"], "w").close()
    found = []

    assert _run(dataset, on_found=found.append) == (0, 0)
    assert found == [0]


def test_crops_run_cancel_after_first_batch(monkeypatch, dataset):
    paths = dataset["paths"]
    with open(dataset["labels"], "w", encoding="utf-8") as f:
        for i in range(RECOGNITION_BATCH_SIZE + 2):
            f.write(f"{paths[i % 3]}\tм\n")
    _patch(monkeypatch, custom="а", surya="а")
    done = []
    found = []

    good, _ = _run(
        dataset,
        engines=["custom", "surya"],
        on_found=found.append,
        on_file_done=lambda: done.append(1),
        should_cancel=lambda: len(done) >= 1,
    )

    assert found == [2]
    assert good == RECOGNITION_BATCH_SIZE


def test_crops_run_passes_options_to_engines(monkeypatch, dataset):
    seen = {}

    def fake_custom(crops, model_dir):
        seen["custom"] = model_dir
        return [("а", 0.9)] * len(crops)

    def fake_vlm(crops, engine_id, on_error):
        seen["vlm_line"] = engine_id
        return [("а", 1.0)] * len(crops)

    _patch(monkeypatch, custom=fake_custom, vlm_line=fake_vlm)

    _run(dataset, engines=["custom", "vlm_line"])

    assert seen == {"custom": "/m", "vlm_line": "glm_ocr"}


def test_consensus_build_engine_calls_includes_new_engines():
    options = RecognitionOptions(custom_model_dir="/m", line_vlm_engine="glm_ocr")

    calls = pipeline._build_engine_calls(
        ["paddle", "custom", "vlm_line"], [], "ru", "small", "rus", options, None
    )

    assert set(calls) == {"paddle", "custom", "vlm_line"}
    assert calls["custom"][1][1] == "/m"
    assert calls["vlm_line"][1][1] == "glm_ocr"


def test_crops_label_vote_does_not_count_as_diverged(monkeypatch, dataset):
    _patch(monkeypatch, custom="другое", surya="другое")
    diverged = []

    _run(
        dataset,
        engines=["custom", "surya"],
        label_votes=True,
        on_line_done=lambda bucket, d: diverged.append(d),
    )

    assert diverged == [False, False, False]
    record = json.loads(_lines(dataset, "debug.jsonl")[0])
    assert record["diverged"] is False


def test_crops_run_reads_label_file_with_bom(monkeypatch, dataset):
    path = dataset["paths"][0]
    with open(dataset["labels"], "w", encoding="utf-8-sig") as f:
        f.write(f"{path}\tметка\n")
    _patch(monkeypatch, custom="а", surya="а")
    errors = []

    assert _run(dataset, engines=["custom", "surya"], on_error=errors.append) == (1, 0)
    assert errors == []


def test_iter_batches_counts_bad_lines_in_batch_size(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline_crops, "RECOGNITION_BATCH_SIZE", 2)
    labels = tmp_path / "l.txt"
    labels.write_text("a\tx\nbad\n\nb\ty\nc\tz\n", encoding="utf-8")

    batches = list(pipeline_crops.iter_batches(str(labels)))

    assert [[line.path for line in b] for b in batches] == [["a"], ["b", "c"]]
    assert pipeline_crops.count_batches(str(labels)) == len(batches)
