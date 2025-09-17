import cv2 as cv
import os
import numpy as np
from PIL import Image
from glob import glob
import os
from PIL import Image
from surya.foundation import FoundationPredictor
from surya.recognition import RecognitionPredictor
from surya.detection import DetectionPredictor
from tqdm import tqdm
import numpy as np
import random
from datetime import datetime
from ocr_library.document_processing import FileIterator
from ocr_library.nn.pipelines.text_recognize_classify_pipeline import TextRecClsPipeline
from ocr_library.nn.models import RotateImage
from ocr_library.utils.image_proc import correct_skew, flip_image
from ocr_library.document_processing.utils import (
    remove_control_characters,
    map_pdf_x_to_pix,
    map_pdf_y_to_pix,
)


def extract_text_pdf(pdf_page, pages_or_dict):
    scale = pages_or_dict.iterator.get_scale_consider_max_len_side(
        pdf_page, pages_or_dict.dpi, pages_or_dict.max_len_side
    )
    frame = pdf_page.render(scale=scale, grayscale=pages_or_dict.grayscale).to_pil()

    frame = pages_or_dict._convert_color_mode(frame)
    frame = np.array(frame)
    if pages_or_dict.max_len_side is not None:
        max_width_height = max(frame.shape[:2])
        if max_width_height > pages_or_dict.max_len_side:
            coef = pages_or_dict.max_len_side / max_width_height
            frame = cv.resize(
                frame, None, fx=coef, fy=coef, interpolation=cv.INTER_AREA
            )
    numpy_image = frame

    layout_width, layout_height = pdf_page.get_size()
    image_height, image_width = numpy_image.shape[:2]
    textpage = pdf_page.get_textpage()
    result = []

    for obj in pdf_page.get_objects(filter=[1]):  # filter = [1, 4]
        pdf_box = obj.get_pos()  # bbox объекта
        chars = []
        for i in range(textpage.count_chars()):
            cx0, cy0, cx1, cy1 = textpage.get_charbox(i)
            if (
                cx0 >= pdf_box[0]
                and cx1 <= pdf_box[2]
                and cy0 >= pdf_box[1]
                and cy1 <= pdf_box[3]
            ):
                ch = textpage.get_text_range(i, 1)
                chars.append((ch, (cx0, cy0, cx1, cy1)))

        if not chars:
            continue

        text = "".join(ch for ch, _ in chars)
        stripped = text.rstrip()
        if stripped.strip() == "":
            continue

        stripped = remove_control_characters(stripped)
        if stripped.replace(" ", "") == "":
            continue

        # оставляем только символы без хвостовых пробелов
        kept = chars[: len(stripped)]

        left = min(c[1][0] for c in kept)
        bottom = min(c[1][1] for c in kept)
        right = max(c[1][2] for c in kept)
        top = max(c[1][3] for c in kept)

        x_0 = int(map_pdf_x_to_pix(left, layout_width, image_width))
        y_0 = int(map_pdf_y_to_pix(top, layout_height, image_height))
        x_1 = int(map_pdf_x_to_pix(right, layout_width, image_width))
        y_1 = int(map_pdf_y_to_pix(bottom, layout_height, image_height))

        if x_1 - x_0 < 3 or y_1 - y_0 < 3:
            continue

        paddle_box = [
            [x_0, y_0],
            [x_1, y_0],
            [x_1, y_1],
            [x_0, y_1],
        ]

        result.append([paddle_box, [stripped, 1.0]])

    return result, numpy_image


def save_image(img_crop, img_count, images_one_folder, image_folder, num_digits):
    img_crop_folder = str(img_count // images_one_folder)
    os.makedirs(f"{image_folder}/{img_crop_folder}", exist_ok=True)
    image_save_path = (
        f"{image_folder}/{img_crop_folder}/image_{img_count:0{num_digits}d}.webp"
    )
    Image.fromarray(img_crop).save(image_save_path, "WEBP")
    img_count += 1
    return img_count, image_save_path


def save_txt(
    image_folder, good_preds, bad_highscore_preds, bad_underscore_preds, threshold
):
    curr_time = str(datetime.now().strftime("%Y-%m-%d %H-%M-%S"))
    with open(
        f"{image_folder}/good_result_{int(threshold * 100)}_{curr_time}.txt",
        "w",
        encoding="utf-8",
    ) as txt:
        txt.write("".join(good_preds))
    with open(
        f"{image_folder}/bad_highscore_result_{int(threshold * 100)}_{curr_time}.txt",
        "w",
        encoding="utf-8",
    ) as txt:
        txt.write("".join(bad_highscore_preds))
    with open(
        f"{image_folder}/bad_underscore_result_{int(threshold * 100)}_{curr_time}.txt",
        "w",
        encoding="utf-8",
    ) as txt:
        txt.write("".join(bad_underscore_preds))


SCAN = ["pdf"]
IMAGE = ["jpg", "jpeg", "png", "tif", "tiff", "gif", "giff", "bmp", "webp"]
DOC = ["docx", "doc", "rtf", "odt", "pptx", "ppt", "odp", "xlsx", "xls", "ods"]
allowed_extensions = SCAN + IMAGE + DOC
filter_score = 0.95
images_one_folder = 10000
random_padding = 7
min_image_pix = 10


ocr = TextRecClsPipeline(
    infer_option="openvino",
    rec_model_path=r"C:\Users\pirat\OneDrive\Documents\Github\ml\models\ocr_rec\1\model.onnx",
    character_dict_path=r"C:\Users\pirat\OneDrive\Documents\Github\ml\models\ocr_rec_postproc\1\ru_dict_ext100124.txt",
)
rotate_orient_model = RotateImage(
    path_to_model=r"C:\Users\pirat\OneDrive\Documents\Github\ml\models\rotate_image\1\model.onnx",
    infer_option="openvino",
)
foundation_predictor = FoundationPredictor()
recognition_predictor = RecognitionPredictor(foundation_predictor)
detection_predictor = DetectionPredictor()

folder_path = "/home/VEvErshov/ocr_markup/razmetka/docs"

matched_files = []
for ext in allowed_extensions:
    pattern = os.path.join(folder_path, f"*{ext}")
    matched_files.extend(glob(pattern))

good_preds = []
bad_highscore_preds = []
bad_underscore_preds = []
pdf_preds = []
image_folder = f"{folder_path}/images"
os.makedirs(image_folder, exist_ok=True)
img_count = 1
num_digits = len(str(images_one_folder))
for file_idx, file_path in enumerate(matched_files):
    pdf_or_images = FileIterator(
        file_path, grayscale=False, dpi=200, pdf_parsing=True, max_pages=None
    )
    for page_idx, page in enumerate(pdf_or_images):
        try:
            if pdf_or_images.iterator.pdf_available:
                has_pdf = True
            else:
                has_pdf = False
        except:
            has_pdf = False

        if has_pdf:
            text_boxes, image = extract_text_pdf(page, pdf_or_images)
            for crop_idx, (box, text_conf) in enumerate(text_boxes):
                # img_crop = image.crop((box[0][0], box[0][1],box[2][0], box[2][1]))
                img_crop = image[
                    max(box[0][1] - random.randint(0, random_padding), 0) : min(
                        box[2][1] + random.randint(0, random_padding), image.shape[0]
                    ),
                    max(box[0][0] - random.randint(0, random_padding), 0) : min(
                        box[2][0] + random.randint(0, random_padding), image.shape[1]
                    ),
                ]
                if (
                    img_crop.shape[0] <= min_image_pix
                    or img_crop.shape[1] <= min_image_pix
                ):
                    continue
                img_count, image_save_path = save_image(
                    img_crop, img_count, images_one_folder, image_folder, num_digits
                )
                pdf_preds.append(f"{image_save_path}\t{text_conf[0]}\n")

        else:
            img = page
            flat_preds = rotate_orient_model(img)
            image = flip_image(img, flat_preds)[0]
            image, skew_angle = correct_skew(image)
            image = Image.fromarray(image)
            surya_bboxes = [
                box.polygon for box in detection_predictor([image])[0].bboxes
            ]

            for crop_idx, box in enumerate(surya_bboxes):
                try:
                    surya_predictions = recognition_predictor(
                        [image],
                        None,
                        bboxes=[[[box[0][0], box[0][1], box[2][0], box[2][1]]]],
                    )
                    surya_text = surya_predictions[0].text_lines[0].text
                    surya_score = surya_predictions[0].text_lines[0].confidence

                    img_crop = image[box[0][1] : box[2][1], box[0][0] : box[2][0]]
                    paddle_predictions = ocr(np.array([img_crop]))
                    paddle_text = paddle_predictions[0][0][0]
                    paddle_score = paddle_predictions[0][0][1]

                    if (
                        img_crop.shape[0] <= min_image_pix
                        or img_crop.shape[1] <= min_image_pix
                    ):
                        continue
                    img_count, image_save_path = save_image(
                        img_crop, img_count, images_one_folder, image_folder, num_digits
                    )

                    if surya_text == paddle_text and paddle_text != "":
                        good_preds.append(f"{image_save_path}\t{paddle_text}\n")
                    else:
                        if paddle_score >= filter_score:
                            bad_highscore_preds.append(
                                f"{image_save_path}\t{paddle_text}\n"
                            )
                        elif surya_score >= filter_score:
                            bad_highscore_preds.append(
                                f"{image_save_path}\t{surya_text}\n"
                            )
                        else:
                            bad_underscore_preds.append(
                                f"{image_save_path}\t{paddle_text}\n"
                            )
                except Exception as err:
                    print(f"Ошибка {err} на {file_path}")
    print(f"Обработка {file_path} завершена!")
save_txt(
    image_folder, good_preds, bad_highscore_preds, bad_underscore_preds, filter_score
)
