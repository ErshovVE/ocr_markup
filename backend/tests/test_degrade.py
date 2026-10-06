"""Порча страниц PDF с текстовым слоем (backend/degrade.py) и её место в pipeline.run."""

import json
import random

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend import degrade, main, pipeline
from backend.degrade import DegradeOptions, GeometryChangedError, legible
from backend.tests.test_pdf_extract import _build_pdf

CLEAN = "The standard applies to washers for machine tools"


def _line(height=40, width=300, ink=0, paper=255):
    """Строка с «буквами» — вертикальными штрихами цвета ink на фоне paper."""
    image = np.full((height, width, 3), paper, np.uint8)
    for x in range(10, width - 10, 12):
        image[8 : height - 8, x : x + 4] = ink
    return image


# --- проверка читаемости ------------------------------------------------------


def test_legible_accepts_same_and_mildly_noisy_line():
    clean = _line()
    noise = np.random.default_rng(0).integers(-20, 20, clean.shape)
    assert legible(clean, clean)
    assert legible(clean, np.clip(clean.astype(int) + noise, 0, 255).astype(np.uint8))


def test_legible_rejects_washed_out_text_and_blob():
    clean = _line()
    washed = np.full_like(clean, 255)
    washed[clean < 128] = 240  # текст почти слился с фоном
    blob = clean.copy()
    blob[:, 100:200] = 0  # пятно закрыло треть строки
    assert not legible(clean, washed)
    assert not legible(clean, blob)


def test_legible_rejects_one_erased_or_blotted_word_in_a_long_line():
    clean = _line(width=1200)
    erased, blotted = clean.copy(), clean.copy()
    erased[:, 600:640] = 255  # белая полоса стёрла «слово»: по всей строке пропало ~3 % текста
    blotted[:, 600:640] = 0
    assert not legible(clean, erased)
    assert not legible(clean, blotted)


def test_legible_handles_light_text_on_dark_background():
    clean = _line(ink=255, paper=30)
    washed = clean.copy()
    washed[clean > 128] = 50  # светлый текст потемнел до фона
    assert legible(clean, clean)
    assert not legible(clean, washed)


def test_legible_compares_tiny_crops_pixelwise():
    dot = np.full((6, 6, 3), 255, np.uint8)
    dot[2:4, 2:4] = 0
    assert legible(dot, dot)
    assert not legible(dot, np.zeros_like(dot))


def test_choose_crop_distinguishes_untouched_degraded_and_illegible():
    clean = _line()
    noisy = np.clip(clean.astype(int) + 10, 0, 255).astype(np.uint8)
    assert degrade.choose_crop(clean, None, 25) is None
    assert degrade.choose_crop(clean, clean.copy(), 25) is None  # эффекты строку не задели
    assert degrade.choose_crop(clean, noisy, 25) is True
    assert degrade.choose_crop(clean, np.full_like(clean, 255), 25) is False


# --- описание эффектов и сид страницы ----------------------------------------


@pytest.mark.parametrize(
    "spec, fragment",
    [
        ("Jpeg", "словарём"),
        ({"name": "Jpeg", "p": 2}, "от 0 до 1"),
        ({"name": "Jpeg", "one_of": []}, "ровно один"),
        ({"name": "Jpeg", "params": [1]}, "'params'"),
        ({"one_of": [{"name": "Jpeg", "p": 0.5}]}, "не действует"),
    ],
)
def test_spec_errors_without_augraphy(spec, fragment):
    assert any(fragment in e for e in degrade.spec_errors(spec, "post[0]"))


def test_page_seed_depends_on_file_name_and_page_not_on_order():
    options = DegradeOptions(page_share=1.0, seed=3)
    a = degrade.page_seed(options, "/in/doc.pdf", 2).random()
    assert a == degrade.page_seed(options, "/other/doc.pdf", 2).random()
    assert a != degrade.page_seed(options, "/in/doc.pdf", 3).random()
    assert a != degrade.page_seed(DegradeOptions(page_share=1.0, seed=4), "/in/doc.pdf", 2).random()


def test_disabled_degradation_draws_nothing():
    rng = random.Random(1)
    state = rng.getstate()
    assert degrade.maybe_degrade_page(_line(), DegradeOptions(), rng) is None
    assert rng.getstate() == state


# --- pipeline.run: только текстовый слой --------------------------------------


@pytest.fixture
def pdf_dir(tmp_path):
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    (input_dir / "doc.pdf").write_bytes(_build_pdf([(CLEAN, 10, 300)], page_w=600))
    return input_dir


def _run(pdf_dir, out, fake_degrade, monkeypatch, errors=None):
    monkeypatch.setattr(pipeline.page_degrade, "maybe_degrade_page", fake_degrade)
    options = DegradeOptions(page_share=1.0)
    return pipeline.run(
        str(pdf_dir),
        str(out),
        0.5,
        pdf_ocr_fallback=False,
        degrade=options,
        on_error=errors.append if errors is not None else None,
    )


def _degrade_records(out):
    return [
        json.loads(line)
        for line in (out / "degrade.jsonl").read_text(encoding="utf-8").splitlines()
    ]


def test_text_layer_line_comes_from_degraded_page(pdf_dir, tmp_path, monkeypatch):
    out = tmp_path / "out"

    def noisy(image, options, rng):
        return np.clip(image.astype(int) - 12, 0, 255).astype(np.uint8)

    assert _run(pdf_dir, out, noisy, monkeypatch) == (1, 0)
    records = _degrade_records(out)
    assert len(records) == 1 and records[0]["degraded"] is True
    assert (out / "good.txt").read_text(encoding="utf-8").split("\t")[1].strip() == CLEAN


def test_illegible_line_keeps_clean_crop_and_label(pdf_dir, tmp_path, monkeypatch):
    out = tmp_path / "out"
    assert _run(pdf_dir, out, lambda image, o, r: np.full_like(image, 255), monkeypatch) == (1, 0)
    assert _degrade_records(out)[0]["degraded"] is False


def test_augraphy_crash_keeps_page_clean_and_reports(pdf_dir, tmp_path, monkeypatch):
    out, errors = tmp_path / "out", []

    def crash(image, options, rng):
        raise RuntimeError("numba typing failed")

    assert _run(pdf_dir, out, crash, monkeypatch, errors) == (1, 0)
    assert any("Порча страницы не удалась" in e for e in errors)
    assert _degrade_records(out) == []  # страница чистая: записей о порче нет


def test_geometry_change_fails_the_file(pdf_dir, tmp_path, monkeypatch):
    out, errors = tmp_path / "out", []

    def resize(image, options, rng):
        raise GeometryChangedError("changed")

    assert _run(pdf_dir, out, resize, monkeypatch, errors) == (0, 0)
    assert any("changed" in e for e in errors)


def test_run_without_degrade_writes_no_degrade_log(pdf_dir, tmp_path):
    out = tmp_path / "out"
    pipeline.run(str(pdf_dir), str(out), 0.5, pdf_ocr_fallback=False)
    assert not (out / "degrade.jsonl").exists()


# --- API ----------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main.models_status, "get_status", lambda include_vlm=True: {})
    return TestClient(main.app)


@pytest.mark.parametrize(
    "extra",
    [
        {"degrade_page_share": 1.5},
        {"degrade_page_share": 0.5, "mode": "vlm", "vlm_engines": ["qwen"]},
        {"degrade_page_share": 0.5, "extract_pdf_text_layer": False},
        {"degrade_page_share": 0.5, "degrade_effects": {"ink": ["Jpeg"]}},
        {"degrade_page_share": 0.5, "degrade_effects": {"scan": []}},
    ],
)
def test_run_rejects_bad_degrade_options(client, tmp_path, extra):
    (tmp_path / "in").mkdir()
    body = {"input_dir": str(tmp_path / "in"), "output_dir": str(tmp_path / "o"), **extra}
    assert client.post("/run", json=body).status_code == 422


def test_run_passes_degrade_options(client, tmp_path, monkeypatch):
    pytest.importorskip("augraphy")  # набор эффектов по умолчанию собирается при проверке запроса
    seen = {}
    monkeypatch.setattr(main, "start_job", lambda *a, **k: seen.update(k) or "job-1")
    (tmp_path / "in").mkdir()
    body = {"input_dir": str(tmp_path / "in"), "output_dir": str(tmp_path / "o")}

    assert client.post("/run", json=body).status_code == 200
    assert seen["degrade"] is None

    body.update(degrade_page_share=0.5, degrade_seed=7)
    assert client.post("/run", json=body).status_code == 200
    assert (seen["degrade"].page_share, seen["degrade"].seed) == (0.5, 7)


# --- настоящая Augraphy -------------------------------------------------------


def test_degrade_page_keeps_geometry_and_restores_global_rng():
    pytest.importorskip("augraphy")
    page = np.tile(_line(60, 400), (6, 1, 1))
    random.seed(123)
    expected_next = random.random()
    random.seed(123)

    out = degrade.degrade_page(page, degrade.DEFAULT_EFFECTS, seed=7)

    assert random.random() == expected_next
    assert out.shape == page.shape and out.dtype == np.uint8


def test_degrade_page_rejects_geometric_effects():
    pytest.importorskip("augraphy")
    page = np.tile(_line(60, 400), (4, 1, 1))
    squish = {"post": [{"name": "Squish", "p": 1.0, "params": {"squish_direction": 0}}]}
    with pytest.raises(GeometryChangedError):
        degrade.degrade_page(page, squish, seed=1)


def test_default_effects_build():
    pytest.importorskip("augraphy")
    assert degrade.effects_errors(degrade.DEFAULT_EFFECTS) == []


def test_preview_writes_pages_and_log(pdf_dir, tmp_path):
    pytest.importorskip("augraphy")
    jpeg = {"post": [{"name": "Jpeg", "p": 1.0, "params": {"quality_range": [30, 40]}}]}
    options = DegradeOptions(page_share=1.0, effects=jpeg)

    assert degrade.preview(str(pdf_dir), str(tmp_path / "pages"), options, dpi=100) == 1
    log = [
        json.loads(x) for x in (tmp_path / "pages" / "pages.jsonl").read_text("utf-8").splitlines()
    ]
    assert log[0]["degraded"] is True and (tmp_path / "pages" / log[0]["image"]).exists()
