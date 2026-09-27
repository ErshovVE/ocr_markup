import os

import numpy as np
from PIL import Image

from backend.pipeline import _crop_paths, _resume_img_count, _save_crop, list_input_files


def test_crop_paths_first_folder():
    relative, absolute = _crop_paths(1, "/out")
    assert relative == "crops/0/image_00001.webp"
    assert absolute == os.path.join("/out", "crops", "0", "image_00001.webp")


def test_crop_paths_last_of_first_folder():
    relative, _ = _crop_paths(9999, "/out")
    assert relative == "crops/0/image_09999.webp"


def test_crop_paths_rolls_over_to_next_folder_at_10000():
    relative, _ = _crop_paths(10000, "/out")
    assert relative == "crops/1/image_10000.webp"


def test_resume_img_count_starts_at_one_when_no_crops_dir(tmp_path):
    assert _resume_img_count(str(tmp_path)) == 1


def test_resume_img_count_starts_at_one_when_crops_dir_empty(tmp_path):
    (tmp_path / "crops").mkdir()
    assert _resume_img_count(str(tmp_path)) == 1


def test_resume_img_count_continues_from_max_across_folders(tmp_path):
    (tmp_path / "crops" / "0").mkdir(parents=True)
    (tmp_path / "crops" / "0" / "image_00001.webp").write_bytes(b"x")
    (tmp_path / "crops" / "0" / "image_09999.webp").write_bytes(b"x")
    (tmp_path / "crops" / "1").mkdir()
    (tmp_path / "crops" / "1" / "image_10042.webp").write_bytes(b"x")

    assert _resume_img_count(str(tmp_path)) == 10043


def test_resume_img_count_ignores_files_from_the_old_uuid_scheme(tmp_path):
    """Папки, размеченные до перехода на сквозную нумерацию, могут содержать
    старые crop_<uuid>.webp — они не должны ломать резюмирование или
    учитываться в максимуме."""
    crops_dir = tmp_path / "crops"
    crops_dir.mkdir()
    (crops_dir / "crop_deadbeefcafe.webp").write_bytes(b"x")

    assert _resume_img_count(str(tmp_path)) == 1


def test_save_crop_creates_parent_dirs_and_writes_file(tmp_path):
    absolute = str(tmp_path / "crops" / "0" / "image_00001.webp")
    crop = np.zeros((4, 4, 3), dtype=np.uint8)

    _save_crop(crop, absolute)

    assert os.path.exists(absolute)
    assert Image.open(absolute).size == (4, 4)


def test_save_crop_is_pixel_exact_lossless_webp(tmp_path):
    absolute = str(tmp_path / "crops" / "0" / "image_00001.webp")
    crop = np.random.default_rng(0).integers(0, 256, (20, 60, 3), dtype=np.uint8)

    _save_crop(crop, absolute)

    assert (np.array(Image.open(absolute).convert("RGB")) == crop).all()


def test_list_input_files_matches_extensions_case_insensitively_and_sorts(tmp_path):
    for name in ("b.JPG", "a.png", "c.TIF", "d.Pdf", "notes.txt"):
        (tmp_path / name).write_bytes(b"x")
    (tmp_path / "sub.png").mkdir()

    images, pdfs = list_input_files(str(tmp_path))

    assert [os.path.basename(p) for p in images] == ["a.png", "b.JPG", "c.TIF"]
    assert [os.path.basename(p) for p in pdfs] == ["d.Pdf"]


def test_list_input_files_handles_glob_metacharacters_in_dir_name(tmp_path):
    folder = tmp_path / "scan [2026]"
    folder.mkdir()
    (folder / "a.png").write_bytes(b"x")

    images, _ = list_input_files(str(folder))

    assert [os.path.basename(p) for p in images] == ["a.png"]
