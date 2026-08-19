from PIL import Image

from src.annotations import AnnotationManager, save_as_handwritten


def _make_image(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (4, 4)).save(path)


def _manager(tmp_path):
    return AnnotationManager(str(tmp_path), str(tmp_path / "rec.txt"))


def test_load_from_file_parses_existing_images(tmp_path):
    _make_image(tmp_path / "images" / "a.png")
    _make_image(tmp_path / "images" / "b.png")
    manager = _manager(tmp_path)

    ok, msg = manager.load_from_file(
        "images/a.png\tтекст a\nimages/b.png\tтекст b\n"
    )

    assert ok is True
    assert msg == ""
    assert set(manager.records.keys()) == {"a.png", "b.png"}
    assert manager.records["a.png"].annotation == "текст a"


def test_load_from_file_skips_missing_files(tmp_path):
    manager = _manager(tmp_path)

    ok, msg = manager.load_from_file("images/missing.png\tтекст\n")

    assert ok is False
    assert "Не удалось найти" in msg


def test_load_from_file_rejects_path_outside_base_dir(tmp_path):
    outside_dir = tmp_path.parent / "outside_images"
    _make_image(outside_dir / "evil.png")
    manager = _manager(tmp_path)

    ok, _ = manager.load_from_file("../outside_images/evil.png\ttexto\n")

    assert ok is False
    assert "evil.png" not in manager.records


def test_update_annotation_marks_record_modified(tmp_path):
    _make_image(tmp_path / "images" / "a.png")
    manager = _manager(tmp_path)
    manager.load_from_file("images/a.png\told text\n")

    manager.update_annotation("a.png", "new text")

    assert manager.records["a.png"].annotation == "new text"
    assert manager.records["a.png"].is_marked is True
    assert "a.png" in manager.modified_records


def test_delete_record_removes_file_and_entry(tmp_path):
    image_path = tmp_path / "images" / "a.png"
    _make_image(image_path)
    manager = _manager(tmp_path)
    manager.load_from_file("images/a.png\ttext\n")

    ok = manager.delete_record("a.png", create_backup=False)

    assert ok is True
    assert not image_path.exists()
    assert "a.png" not in manager.records


def test_delete_record_returns_false_for_unknown_image(tmp_path):
    manager = _manager(tmp_path)

    ok = manager.delete_record("unknown.png")

    assert ok is False


def test_save_changes_writes_annotation_file_and_status_cache(tmp_path):
    _make_image(tmp_path / "images" / "a.png")
    _make_image(tmp_path / "images" / "b.png")
    manager = _manager(tmp_path)
    manager.load_from_file("images/a.png\told a\nimages/b.png\told b\n")
    manager.update_annotation("a.png", "new a")

    ok, _ = manager.save_changes(create_backup=False)

    assert ok is True
    saved = manager.annotation_file.read_text(encoding="utf-8")
    assert "images/a.png\tnew a\n" in saved
    assert "images/b.png\told b\n" in saved

    cache_content = manager.cache_path.read_text(encoding="utf-8")
    assert "a.png" in cache_content
    assert manager.modified_records == set()


def test_get_image_list_filters_by_marked_status(tmp_path):
    _make_image(tmp_path / "images" / "a.png")
    _make_image(tmp_path / "images" / "b.png")
    manager = _manager(tmp_path)
    manager.load_from_file("images/a.png\ttext\nimages/b.png\ttext\n")
    manager.update_annotation("a.png", "marked now")

    assert manager.get_image_list("marked") == ["a.png"]
    assert manager.get_image_list("unmarked") == ["b.png"]
    assert set(manager.get_image_list("all")) == {"a.png", "b.png"}


def test_save_as_handwritten_copies_image_and_appends_entry(tmp_path):
    _make_image(tmp_path / "images" / "a.png")
    manager = _manager(tmp_path)
    manager.load_from_file("images/a.png\ttекст\n")

    ok = save_as_handwritten(manager, "a.png", "рукописный текст")

    assert ok is True
    dest = tmp_path / "handwritten_images" / "images" / "a.png"
    assert dest.exists()
    handwritten_txt = (tmp_path / "handwritten.txt").read_text(encoding="utf-8")
    assert "handwritten_images/images/a.png\tрукописный текст\n" in handwritten_txt


def test_save_as_handwritten_does_not_duplicate_existing_entry(tmp_path):
    _make_image(tmp_path / "images" / "a.png")
    manager = _manager(tmp_path)
    manager.load_from_file("images/a.png\ttекст\n")
    save_as_handwritten(manager, "a.png", "рукописный текст")

    ok = save_as_handwritten(manager, "a.png", "рукописный текст")

    assert ok is True
    handwritten_txt = (tmp_path / "handwritten.txt").read_text(encoding="utf-8")
    assert handwritten_txt.count("рукописный текст") == 1
