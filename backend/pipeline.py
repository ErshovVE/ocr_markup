import os
import uuid
from glob import glob
from typing import Optional, Tuple

import numpy as np
from PIL import Image

from backend.config import IMAGE_EXTENSIONS
from backend.consensus import vote
from backend.detector import Detector
from backend.recognizers import (
    DEFAULT_LATIN_MODEL_SIZE,
    recognize_paddle,
    recognize_paddle_latin,
    recognize_surya,
    recognize_tesseract,
)

MIN_CROP_PIX = 10


def run(
    input_dir: str,
    output_dir: str,
    threshold: float,
    preferred_model: Optional[str] = None,
    lang: str = "ru",
    latin_model_size: str = DEFAULT_LATIN_MODEL_SIZE,
) -> Tuple[int, int]:
    """Обрабатывает папку документов: детекция -> распознавание x3 -> голосование.

    Возвращает (кол-во хороших строк, кол-во строк на проверку) и пишет
    good.txt/needs_review.txt в output_dir в формате path\ttext\n.

    good.txt/needs_review.txt перезаписываются на каждый запуск (они
    описывают только результат этого запуска), а файлы в crops/ получают
    уникальное имя (uuid4) на каждый кроп, поэтому повторный запуск с тем же
    output_dir не портит содержимое уже сохранённых/импортированных кропов
    из прошлых запусков.
    """
    os.makedirs(output_dir, exist_ok=True)
    detector = Detector()

    matched_files = []
    for ext in IMAGE_EXTENSIONS:
        matched_files.extend(glob(os.path.join(input_dir, f"*{ext}")))

    good_lines = []
    needs_review_lines = []
    tesseract_lang = "rus" if lang == "ru" else "eng"

    for file_path in matched_files:
        try:
            image = Image.open(file_path).convert("RGB")
            numpy_image = np.array(image)
            boxes = detector.detect(numpy_image)
        except Exception as e:
            print(f"Ошибка обработки файла {file_path}: {e}")
            continue

        for box in boxes:
            try:
                x0, y0 = box[0]
                x2, y2 = box[2]
                img_crop = numpy_image[int(y0) : int(y2), int(x0) : int(x2)]

                if img_crop.shape[0] <= MIN_CROP_PIX or img_crop.shape[1] <= MIN_CROP_PIX:
                    continue

                paddle_result = (
                    recognize_paddle(img_crop)
                    if lang == "ru"
                    else recognize_paddle_latin(img_crop, latin_model_size)
                )
                results = {
                    "paddle": paddle_result,
                    "surya": recognize_surya(image, box),
                    "tesseract": recognize_tesseract(img_crop, tesseract_lang),
                }
                bucket, text, _engine = vote(results, threshold, preferred_model)

                crop_dir = os.path.join(output_dir, "crops")
                os.makedirs(crop_dir, exist_ok=True)
                crop_name = f"crop_{uuid.uuid4().hex}.webp"
                crop_path = os.path.join(crop_dir, crop_name)
                Image.fromarray(img_crop).save(crop_path, "WEBP")

                line = f"crops/{crop_name}\t{text}\n"
                if bucket == "good":
                    good_lines.append(line)
                else:
                    needs_review_lines.append(line)
            except Exception as e:
                print(f"Ошибка распознавания строки в {file_path}: {e}")
                continue

    with open(os.path.join(output_dir, "good.txt"), "w", encoding="utf-8") as f:
        f.write("".join(good_lines))
    with open(os.path.join(output_dir, "needs_review.txt"), "w", encoding="utf-8") as f:
        f.write("".join(needs_review_lines))

    return len(good_lines), len(needs_review_lines)
