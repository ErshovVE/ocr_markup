from src.models import ImageRecord


def test_image_record_defaults():
    record = ImageRecord(
        relative_path="img/1.png",
        absolute_path="/abs/img/1.png",
        annotation="привет",
    )

    assert record.is_marked is False


def test_image_record_explicit_is_marked():
    record = ImageRecord(
        relative_path="img/1.png",
        absolute_path="/abs/img/1.png",
        annotation="привет",
        is_marked=True,
    )

    assert record.is_marked is True
