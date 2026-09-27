import numpy as np
from PIL import Image

from src.image_ops import rotate_image


def test_rotating_webp_four_times_is_pixel_exact(tmp_path):
    path = tmp_path / "crop.webp"
    pixels = np.random.default_rng(0).integers(0, 256, (20, 60, 3), dtype=np.uint8)
    Image.fromarray(pixels).save(path, "WEBP", lossless=True)

    for _ in range(4):
        assert rotate_image(str(path), "right") is True

    assert (np.array(Image.open(path).convert("RGB")) == pixels).all()
