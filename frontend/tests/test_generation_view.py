from PIL import Image

from src.ui.generation_view import _build_manager_from_output


def _make_crop(output_dir, name):
    path = output_dir / "crops" / "0" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (4, 4)).save(path)


def _write(path, text):
    path.write_text(text, encoding="utf-8")


def test_first_handoff_imports_backend_output_and_marks_good_lines(tmp_path):
    _make_crop(tmp_path, "image_00001.webp")
    _make_crop(tmp_path, "image_00002.webp")
    _write(tmp_path / "good.txt", "crops/0/image_00001.webp\tмодель\n")
    _write(tmp_path / "needs_review.txt", "crops/0/image_00002.webp\tспорно\n")

    manager = _build_manager_from_output(str(tmp_path))

    assert manager.records["image_00001.webp"].annotation == "модель"
    assert manager.records["image_00001.webp"].is_marked is True
    assert manager.records["image_00002.webp"].is_marked is False


def test_repeated_handoff_keeps_edits_from_review_txt(tmp_path):
    _make_crop(tmp_path, "image_00001.webp")
    _write(tmp_path / "good.txt", "crops/0/image_00001.webp\tмодель\n")
    _write(tmp_path / "review.txt", "crops/0/image_00001.webp\tправка разметчика\n")

    manager = _build_manager_from_output(str(tmp_path))

    assert manager.records["image_00001.webp"].annotation == "правка разметчика"


def test_repeated_handoff_adds_crops_missing_from_review_txt(tmp_path):
    """Новый запуск в ту же папку: старые правки остаются, новые кропы добавляются."""
    _make_crop(tmp_path, "image_00001.webp")
    _make_crop(tmp_path, "image_00002.webp")
    _write(tmp_path / "review.txt", "crops/0/image_00001.webp\tправка\n")
    _write(tmp_path / "good.txt", "crops/0/image_00002.webp\tновая строка\n")

    manager = _build_manager_from_output(str(tmp_path))

    assert manager.records["image_00001.webp"].annotation == "правка"
    assert manager.records["image_00002.webp"].annotation == "новая строка"
    assert manager.records["image_00002.webp"].is_marked is True
