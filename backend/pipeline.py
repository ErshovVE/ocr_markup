import os
import uuid
from glob import glob
from typing import Callable, Optional, Tuple

import numpy as np
import pypdfium2 as pdfium
from PIL import Image

from backend import pdf_extract
from backend.config import IMAGE_EXTENSIONS, PDF_EXTENSIONS
from backend.consensus import vote
from backend.detector import DEFAULT_DETECTOR_ENGINE, Detector
from backend.recognizers import (
    DEFAULT_LATIN_MODEL_SIZE,
    recognize_paddle,
    recognize_paddle_latin,
    recognize_surya,
    recognize_tesseract,
)

MIN_CROP_PIX = 10


def _save_crop(img_crop: np.ndarray, output_dir: str) -> str:
    """Сохраняет кроп в output_dir/crops с уникальным именем, возвращает имя файла"""
    crop_dir = os.path.join(output_dir, "crops")
    os.makedirs(crop_dir, exist_ok=True)
    crop_name = f"crop_{uuid.uuid4().hex}.webp"
    Image.fromarray(img_crop).save(os.path.join(crop_dir, crop_name), "WEBP")
    return crop_name


def _process_boxes(
    image: Image.Image,
    numpy_image: np.ndarray,
    boxes,
    output_dir: str,
    threshold: float,
    preferred_model: Optional[str],
    lang: str,
    latin_model_size: str,
    tesseract_lang: str,
    source_label: str,
    write_line: Callable[[str, str], None],
    on_line_done: Optional[Callable[[str, bool], None]] = None,
) -> None:
    """Прогоняет обнаруженные детектором боксы через консенсус 3 движков.

    Общая логика для растровых изображений и страниц PDF без текстового слоя
    (см. run()/_process_pdf()). write_line(bucket, line) вызывается сразу
    после голосования по каждой строке и пишет её в good.txt/needs_review.txt
    немедленно (см. run()) — если задание упадёт на середине большой папки,
    уже распознанные строки не теряются (в отличие от кропов в crops/,
    которые и так сохраняются сразу, до этого изменения текстовые файлы
    писались только один раз в самом конце). on_line_done(bucket, diverged) —
    источник живого прогресса для трекера в backend/jobs.py
    (детекция+распознавание одной строки Surya может занимать до ~20с,
    поэтому прогресс по документам целиком слишком редкий).
    """
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
            bucket, text, _engine, diverged = vote(results, threshold, preferred_model)

            crop_name = _save_crop(img_crop, output_dir)
            write_line(bucket, f"crops/{crop_name}\t{text}\n")
            if on_line_done:
                on_line_done(bucket, diverged)
        except Exception as e:
            print(f"Ошибка распознавания строки в {source_label}: {e}")
            continue


def _process_pdf(
    file_path: str,
    get_detector: Callable[[], Detector],
    output_dir: str,
    threshold: float,
    preferred_model: Optional[str],
    lang: str,
    latin_model_size: str,
    tesseract_lang: str,
    extract_pdf_text_layer: bool,
    write_line: Callable[[str, str], None],
    on_line_done: Optional[Callable[[str, bool], None]] = None,
) -> None:
    """Обрабатывает один PDF-файл постранично: либо прямым извлечением
    текстового слоя (без OCR), либо обычным OCR-консенсусом растровых страниц.

    Решение "использовать текстовый слой" принимается один раз для всего
    документа (pdf_extract.document_has_text_layer) — если да, страницы без
    текста внутри такого документа просто пропускаются, а не отправляются в
    OCR (осознанное упрощение, см. план/PRD). write_line/on_line_done см.
    _process_boxes; при использовании текстового слоя строки считаются сразу
    good/не diverged (vote() не вызывается — текст берётся из PDF напрямую).
    """
    pdf_doc = pdfium.PdfDocument(file_path)
    try:
        use_text_layer = extract_pdf_text_layer and pdf_extract.document_has_text_layer(pdf_doc)

        for page_index in range(len(pdf_doc)):
            page = pdf_doc[page_index]
            source_label = f"{file_path} (страница {page_index + 1})"
            try:
                numpy_image = pdf_extract.render_page(page)
            except Exception as e:
                print(f"Ошибка рендеринга {source_label}: {e}")
                continue

            if use_text_layer:
                try:
                    if not pdf_extract.page_has_text_layer(page):
                        continue
                    image_height, image_width = numpy_image.shape[:2]
                    boxes_text = pdf_extract.extract_page_text_boxes(
                        page, image_width, image_height
                    )
                except Exception as e:
                    print(f"Ошибка извлечения текстового слоя {source_label}: {e}")
                    continue

                for box, text in boxes_text:
                    try:
                        bx0, by0 = box[0]
                        bx2, by2 = box[2]
                        img_crop = numpy_image[int(by0) : int(by2), int(bx0) : int(bx2)]
                        if img_crop.shape[0] <= MIN_CROP_PIX or img_crop.shape[1] <= MIN_CROP_PIX:
                            continue
                        crop_name = _save_crop(img_crop, output_dir)
                        write_line("good", f"crops/{crop_name}\t{text}\n")
                        if on_line_done:
                            on_line_done("good", False)
                    except Exception as e:
                        print(f"Ошибка сохранения строки в {source_label}: {e}")
                        continue
            else:
                image = Image.fromarray(numpy_image)
                boxes = get_detector().detect(numpy_image)
                _process_boxes(
                    image,
                    numpy_image,
                    boxes,
                    output_dir,
                    threshold,
                    preferred_model,
                    lang,
                    latin_model_size,
                    tesseract_lang,
                    source_label,
                    write_line,
                    on_line_done,
                )
    finally:
        pdf_doc.close()


def run(
    input_dir: str,
    output_dir: str,
    threshold: float,
    preferred_model: Optional[str] = None,
    lang: str = "ru",
    latin_model_size: str = DEFAULT_LATIN_MODEL_SIZE,
    extract_pdf_text_layer: bool = True,
    detector_engine: str = DEFAULT_DETECTOR_ENGINE,
    on_found: Optional[Callable[[int], None]] = None,
    on_file_done: Optional[Callable[[], None]] = None,
    on_line_done: Optional[Callable[[str, bool], None]] = None,
) -> Tuple[int, int]:
    """Обрабатывает папку документов (изображения + PDF): детекция ->
    распознавание x3 -> голосование; для PDF с текстовым слоем — прямое
    извлечение текста+координат без OCR (см. extract_pdf_text_layer).

    Возвращает (кол-во хороших строк, кол-во строк на проверку) и пишет
    good.txt/needs_review.txt в output_dir в формате path\ttext\n.

    good.txt/needs_review.txt перезаписываются на каждый запуск (они
    описывают только результат этого запуска), а файлы в crops/ получают
    уникальное имя (uuid4) на каждый кроп, поэтому повторный запуск с тем же
    output_dir не портит содержимое уже сохранённых/импортированных кропов
    из прошлых запусков. Обе строки пишутся и сбрасываются на диск сразу по
    мере распознавания (а не одним махом в конце) — если задание упадёт на
    середине большой папки, уже готовые строки не теряются.

    Прогресс для трекера в backend/jobs.py — три коллбэка, сам pipeline от
    них не зависит: on_found(total_docs) один раз, как только посчитано
    число найденных документов; on_file_done() — после каждого обработанного
    (или упавшего с ошибкой) файла; on_line_done(bucket, diverged) — сразу
    после голосования по каждой строке (самый частый сигнал — распознавание
    одной строки Surya может занимать до ~20с, поэтому прогресс по файлам
    целиком слишком редкий для отзывчивого UI).
    """
    os.makedirs(output_dir, exist_ok=True)

    detector: Optional[Detector] = None

    def get_detector() -> Detector:
        nonlocal detector
        if detector is None:
            detector = Detector(engine=detector_engine, tesseract_lang=tesseract_lang)
        return detector

    matched_files = []
    for ext in IMAGE_EXTENSIONS:
        matched_files.extend(glob(os.path.join(input_dir, f"*{ext}")))
    pdf_files = []
    for ext in PDF_EXTENSIONS:
        pdf_files.extend(glob(os.path.join(input_dir, f"*{ext}")))

    if on_found:
        on_found(len(matched_files) + len(pdf_files))

    tesseract_lang = "rus" if lang == "ru" else "eng"
    good_count = 0
    review_count = 0

    with (
        open(os.path.join(output_dir, "good.txt"), "w", encoding="utf-8") as good_file,
        open(os.path.join(output_dir, "needs_review.txt"), "w", encoding="utf-8") as review_file,
    ):

        def write_line(bucket: str, line: str) -> None:
            nonlocal good_count, review_count
            target = good_file if bucket == "good" else review_file
            target.write(line)
            target.flush()
            if bucket == "good":
                good_count += 1
            else:
                review_count += 1

        for file_path in matched_files:
            try:
                image = Image.open(file_path).convert("RGB")
                numpy_image = np.array(image)
                boxes = get_detector().detect(numpy_image)
            except Exception as e:
                print(f"Ошибка обработки файла {file_path}: {e}")
                if on_file_done:
                    on_file_done()
                continue

            _process_boxes(
                image,
                numpy_image,
                boxes,
                output_dir,
                threshold,
                preferred_model,
                lang,
                latin_model_size,
                tesseract_lang,
                file_path,
                write_line,
                on_line_done,
            )
            if on_file_done:
                on_file_done()

        for file_path in pdf_files:
            try:
                _process_pdf(
                    file_path,
                    get_detector,
                    output_dir,
                    threshold,
                    preferred_model,
                    lang,
                    latin_model_size,
                    tesseract_lang,
                    extract_pdf_text_layer,
                    write_line,
                    on_line_done,
                )
            except Exception as e:
                print(f"Ошибка обработки файла {file_path}: {e}")
                if on_file_done:
                    on_file_done()
                continue
            if on_file_done:
                on_file_done()

    return good_count, review_count
