"""pipeline.run на PDF: постраничное решение «текстовый слой или OCR»."""

import pytest

from backend import pipeline
from backend.tests.test_pdf_extract import _build_pdf

CLEAN = "The standard applies to washers for machine tools"
GARBAGE = "Th3 st4nd@rd app1ies t0 w4sh#rs f0r m4ch1ne"


@pytest.fixture
def pdf_dir(tmp_path):
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    pages = [(CLEAN, 10, 300), (GARBAGE, 10, 300), None]
    (input_dir / "doc.pdf").write_bytes(_build_pdf(pages, page_w=600))
    return input_dir


class _ExplodingDetector:
    def __init__(self, *args, **kwargs):
        raise AssertionError("в режиме «только текстовый слой» OCR запускаться не должен")


def test_pdf_ocr_fallback_off_skips_pages_without_usable_layer(pdf_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "Detector", _ExplodingDetector)
    out = tmp_path / "out"

    good, review = pipeline.run(str(pdf_dir), str(out), 0.5, pdf_ocr_fallback=False)

    assert (good, review) == (1, 0)
    lines = (out / "good.txt").read_text(encoding="utf-8").splitlines()
    assert [line.split("	", 1)[1] for line in lines] == [CLEAN]


def test_pdf_ocr_fallback_on_sends_bad_pages_to_ocr(pdf_dir, tmp_path, monkeypatch):
    ocr_pages = []

    class _RecordingDetector:
        def __init__(self, *args, **kwargs):
            pass

        def detect(self, image):
            ocr_pages.append(image.shape)
            return []

    monkeypatch.setattr(pipeline, "Detector", _RecordingDetector)

    good, _ = pipeline.run(str(pdf_dir), str(tmp_path / "out"), 0.5)

    assert good == 1  # чистая страница — из слоя
    assert len(ocr_pages) == 2  # мусорный слой и пустая страница — в OCR
