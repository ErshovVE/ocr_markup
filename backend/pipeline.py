import json
import os
import re
import threading
import time
from glob import glob
from typing import Callable, Dict, Optional, Tuple

import numpy as np
import pypdfium2 as pdfium
from PIL import Image

from backend import pdf_extract
from backend.config import (
    CROP_FILENAME_DIGITS,
    CROPS_PER_FOLDER,
    ENGINE_CALL_TIMEOUT_SECONDS,
    IMAGE_EXTENSIONS,
    PDF_EXTENSIONS,
)
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


def _run_engines_with_timeout(
    calls: Dict[str, Tuple[Callable, tuple]],
    timeout: float,
    source_label: str,
    on_error: Optional[Callable[[str], None]] = None,
) -> Dict[str, Tuple[str, float]]:
    """Запускает несколько recognize_*-вызовов параллельно с общим таймаутом на все вместе.

    calls: {имя_движка: (функция, аргументы)}. Если вызов не уложился в общий
    таймаут, для этого движка возвращается ("", 0.0).

    Намеренно НЕ использует общий ThreadPoolExecutor — с фиксированным пулом
    один по-настоящему зависший (не исключение — recognize_* уже ловят свои
    исключения сами, см. backend/recognizers.py) вызов навсегда отнимает
    воркера: поток нельзя ни убить, ни вернуть в пул, поэтому каждый
    следующий вызов того же движка вставал бы в очередь за зависшим и тоже
    гарантированно таймаутился бы, даже если сам он выполнился бы мгновенно.
    Одноразовый поток на вызов устраняет это: зависший вызов "теряет" только
    свой собственный поток, не забирая мощность у будущих строк/job'ов.
    Дедлайн общий на все calls (а не «до timeout» на каждый по очереди), иначе
    при нескольких одновременно медленных движках суммарное ожидание строки
    росло бы до len(calls) * timeout вместо timeout.
    """
    result_box: Dict[str, Tuple[str, float]] = {}

    def make_target(name: str, fn: Callable, args: tuple):
        def target() -> None:
            result_box[name] = fn(*args)

        return target

    threads = {
        name: threading.Thread(
            target=make_target(name, fn, args), daemon=True, name=f"ocr-engine-{name}"
        )
        for name, (fn, args) in calls.items()
    }
    for thread in threads.values():
        thread.start()

    deadline = time.monotonic() + timeout
    results: Dict[str, Tuple[str, float]] = {}
    for name, thread in threads.items():
        remaining = max(0.0, deadline - time.monotonic())
        thread.join(remaining)
        if thread.is_alive():
            msg = f"Таймаут {timeout}с у движка {name}: {source_label}"
            print(msg)
            if on_error:
                on_error(msg)
            results[name] = ("", 0.0)
        else:
            results[name] = result_box.get(name, ("", 0.0))
    return results


_CROP_FILENAME_RE = re.compile(r"^image_(\d+)\.webp$")


def _resume_img_count(output_dir: str) -> int:
    """Продолжает сквозную нумерацию кропов с прошлых запусков на этот
    output_dir вместо старта с 1 на каждый запуск.

    crops/ не очищается между запусками (см. докстринг run()), а имена по
    этой схеме (в отличие от прежнего uuid4) не гарантированно уникальны
    сами по себе — без резюмирования повторный запуск затёр бы уже
    сохранённые/импортированные кропы прошлых запусков под теми же именами.
    """
    crops_dir = os.path.join(output_dir, "crops")
    max_count = 0
    if os.path.isdir(crops_dir):
        with os.scandir(crops_dir) as folders:
            for folder_entry in folders:
                if not folder_entry.is_dir():
                    continue
                with os.scandir(folder_entry.path) as files:
                    for file_entry in files:
                        match = _CROP_FILENAME_RE.match(file_entry.name)
                        if match:
                            max_count = max(max_count, int(match.group(1)))
    return max_count + 1


def _crop_paths(img_count: int, output_dir: str) -> Tuple[str, str]:
    """Путь кропа по схеме predict.py::save_image — CROPS_PER_FOLDER файлов
    на подпапку (номер подпапки = img_count // CROPS_PER_FOLDER) вместо
    непрозрачного uuid4. Возвращает (относительный путь для
    good.txt/needs_review.txt/debug.jsonl, абсолютный путь для сохранения
    файла на диске)."""
    folder = str(img_count // CROPS_PER_FOLDER)
    filename = f"image_{img_count:0{CROP_FILENAME_DIGITS}d}.webp"
    relative = f"crops/{folder}/{filename}"
    absolute = os.path.join(output_dir, "crops", folder, filename)
    return relative, absolute


def _save_crop(img_crop: np.ndarray, absolute_path: str) -> None:
    """Сохраняет кроп по уже выделенному пути (см. allocate_crop_path в run())"""
    os.makedirs(os.path.dirname(absolute_path), exist_ok=True)
    Image.fromarray(img_crop).save(absolute_path, "WEBP")


def _process_boxes(
    image: Image.Image,
    numpy_image: np.ndarray,
    boxes,
    threshold: float,
    preferred_model: Optional[str],
    lang: str,
    latin_model_size: str,
    tesseract_lang: str,
    source_label: str,
    write_line: Callable[[str, str], None],
    allocate_crop_path: Callable[[], Tuple[str, str]],
    on_line_done: Optional[Callable[[str, bool], None]] = None,
    on_error: Optional[Callable[[str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    write_debug: Optional[Callable[[dict], None]] = None,
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
    поэтому прогресс по документам целиком слишком редкий). on_error(msg) —
    сигнал об ошибке/таймауте строки для трекера (в отличие от print(),
    который виден только в консоли backend). should_cancel() — кооперативная
    отмена: проверяется перед каждым боксом, чтобы job не докручивал
    оставшиеся строки после запроса на отмену (см. backend/jobs.py).
    write_debug(record) — если задан, пишет по одной JSON-записи на строку
    с текстами/score всех 3 движков (см. run()) — без этого показать
    разметчику "что видел каждый движок" физически нечем, т.к. vote()
    оставляет только текст-победитель. allocate_crop_path() — выделяет
    следующий (относительный, абсолютный) путь кропа по сквозной нумерации
    (см. run()/_resume_img_count), чтобы разные строки/файлы одного job'а
    не выбирали один и тот же номер.
    """
    for box in boxes:
        if should_cancel and should_cancel():
            break
        try:
            x0, y0 = box[0]
            x2, y2 = box[2]
            img_crop = numpy_image[int(y0) : int(y2), int(x0) : int(x2)]

            if img_crop.shape[0] <= MIN_CROP_PIX or img_crop.shape[1] <= MIN_CROP_PIX:
                continue

            paddle_fn = recognize_paddle if lang == "ru" else recognize_paddle_latin
            paddle_args = (img_crop,) if lang == "ru" else (img_crop, latin_model_size)
            results = _run_engines_with_timeout(
                {
                    "paddle": (paddle_fn, paddle_args),
                    "surya": (recognize_surya, (image, box)),
                    "tesseract": (recognize_tesseract, (img_crop, tesseract_lang)),
                },
                ENGINE_CALL_TIMEOUT_SECONDS,
                source_label,
                on_error=on_error,
            )
            bucket, text, engine, diverged = vote(results, threshold, preferred_model)

            crop_relative, crop_absolute = allocate_crop_path()
            _save_crop(img_crop, crop_absolute)
            write_line(bucket, f"{crop_relative}\t{text}\n")
            if on_line_done:
                on_line_done(bucket, diverged)
            if write_debug:
                write_debug(
                    {
                        "crop": crop_relative,
                        "bucket": bucket,
                        "engine": engine,
                        "diverged": diverged,
                        "engines": {
                            name: {"text": t, "score": s} for name, (t, s) in results.items()
                        },
                    }
                )
        except Exception as e:
            msg = f"Ошибка распознавания строки в {source_label}: {e}"
            print(msg)
            if on_error:
                on_error(msg)
            continue


def _process_pdf(
    file_path: str,
    get_detector: Callable[[], Detector],
    threshold: float,
    preferred_model: Optional[str],
    lang: str,
    latin_model_size: str,
    tesseract_lang: str,
    extract_pdf_text_layer: bool,
    write_line: Callable[[str, str], None],
    allocate_crop_path: Callable[[], Tuple[str, str]],
    on_line_done: Optional[Callable[[str, bool], None]] = None,
    on_error: Optional[Callable[[str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    write_debug: Optional[Callable[[dict], None]] = None,
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
            if should_cancel and should_cancel():
                break
            page = pdf_doc[page_index]
            source_label = f"{file_path} (страница {page_index + 1})"
            try:
                numpy_image = pdf_extract.render_page(page)
            except Exception as e:
                msg = f"Ошибка рендеринга {source_label}: {e}"
                print(msg)
                if on_error:
                    on_error(msg)
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
                    msg = f"Ошибка извлечения текстового слоя {source_label}: {e}"
                    print(msg)
                    if on_error:
                        on_error(msg)
                    continue

                for box, text in boxes_text:
                    try:
                        bx0, by0 = box[0]
                        bx2, by2 = box[2]
                        img_crop = numpy_image[int(by0) : int(by2), int(bx0) : int(bx2)]
                        if img_crop.shape[0] <= MIN_CROP_PIX or img_crop.shape[1] <= MIN_CROP_PIX:
                            continue
                        crop_relative, crop_absolute = allocate_crop_path()
                        _save_crop(img_crop, crop_absolute)
                        write_line("good", f"{crop_relative}\t{text}\n")
                        if on_line_done:
                            on_line_done("good", False)
                    except Exception as e:
                        msg = f"Ошибка сохранения строки в {source_label}: {e}"
                        print(msg)
                        if on_error:
                            on_error(msg)
                        continue
            else:
                image = Image.fromarray(numpy_image)
                boxes = get_detector().detect(numpy_image)
                _process_boxes(
                    image,
                    numpy_image,
                    boxes,
                    threshold,
                    preferred_model,
                    lang,
                    latin_model_size,
                    tesseract_lang,
                    source_label,
                    write_line,
                    allocate_crop_path,
                    on_line_done,
                    on_error=on_error,
                    should_cancel=should_cancel,
                    write_debug=write_debug,
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
    on_error: Optional[Callable[[str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> Tuple[int, int]:
    """Обрабатывает папку документов (изображения + PDF): детекция ->
    распознавание x3 -> голосование; для PDF с текстовым слоем — прямое
    извлечение текста+координат без OCR (см. extract_pdf_text_layer).

    Возвращает (кол-во хороших строк, кол-во строк на проверку) и пишет
    good.txt/needs_review.txt/debug.jsonl в output_dir.

    good.txt/needs_review.txt перезаписываются на каждый запуск (они
    описывают только результат этого запуска), а кропы в crops/ именуются
    по схеме predict.py::save_image — crops/{N // CROPS_PER_FOLDER}/
    image_{N:0{CROP_FILENAME_DIGITS}d}.webp, где N — сквозной номер кропа
    (см. _resume_img_count/_crop_paths). Нумерация при повторном запуске
    продолжается с прошлого максимума на диске, а не с 1, поэтому
    output_dir не портит содержимое уже сохранённых/импортированных кропов
    из прошлых запусков. Обе строки пишутся и сбрасываются на диск сразу по
    мере распознавания (а не одним махом в конце) — если задание упадёт на
    середине большой папки, уже готовые строки не теряются. debug.jsonl —
    по одной JSON-записи на строку с текстами/score всех 3 движков (см.
    _process_boxes) — единственный источник данных для показа разметчику,
    что видел каждый движок, т.к. good.txt/needs_review.txt хранят только
    текст-победитель.

    Прогресс для трекера в backend/jobs.py — пять коллбэков, сам pipeline от
    них не зависит: on_found(total_docs) один раз, как только посчитано
    число найденных документов; on_file_done() — после каждого обработанного
    (или упавшего с ошибкой) файла; on_line_done(bucket, diverged) — сразу
    после голосования по каждой строке (самый частый сигнал — распознавание
    одной строки Surya может занимать до ~20с, поэтому прогресс по файлам
    целиком слишком редкий для отзывчивого UI); on_error(msg) — ошибка/таймаут
    файла или строки, видимая в /status (в отличие от print(), который виден
    только в консоли backend); should_cancel() — кооперативная отмена,
    проверяется перед каждым файлом/страницей/строкой (см. backend/jobs.py,
    POST /jobs/{id}/cancel) — поток нельзя убить напрямую, поэтому job сам
    останавливается на ближайшей проверке, не теряя уже записанное.
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
    img_count = _resume_img_count(output_dir)

    with (
        open(os.path.join(output_dir, "good.txt"), "w", encoding="utf-8") as good_file,
        open(os.path.join(output_dir, "needs_review.txt"), "w", encoding="utf-8") as review_file,
        open(os.path.join(output_dir, "debug.jsonl"), "w", encoding="utf-8") as debug_file,
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

        def write_debug(record: dict) -> None:
            debug_file.write(json.dumps(record, ensure_ascii=False) + "\n")
            debug_file.flush()

        def allocate_crop_path() -> Tuple[str, str]:
            nonlocal img_count
            paths = _crop_paths(img_count, output_dir)
            img_count += 1
            return paths

        for file_path in matched_files:
            if should_cancel and should_cancel():
                break
            try:
                image = Image.open(file_path).convert("RGB")
                numpy_image = np.array(image)
                boxes = get_detector().detect(numpy_image)
            except Exception as e:
                msg = f"Ошибка обработки файла {file_path}: {e}"
                print(msg)
                if on_error:
                    on_error(msg)
                if on_file_done:
                    on_file_done()
                continue

            _process_boxes(
                image,
                numpy_image,
                boxes,
                threshold,
                preferred_model,
                lang,
                latin_model_size,
                tesseract_lang,
                file_path,
                write_line,
                allocate_crop_path,
                on_line_done,
                on_error=on_error,
                should_cancel=should_cancel,
                write_debug=write_debug,
            )
            if on_file_done:
                on_file_done()

        for file_path in pdf_files:
            if should_cancel and should_cancel():
                break
            try:
                _process_pdf(
                    file_path,
                    get_detector,
                    threshold,
                    preferred_model,
                    lang,
                    latin_model_size,
                    tesseract_lang,
                    extract_pdf_text_layer,
                    write_line,
                    allocate_crop_path,
                    on_line_done,
                    on_error=on_error,
                    should_cancel=should_cancel,
                    write_debug=write_debug,
                )
            except Exception as e:
                msg = f"Ошибка обработки файла {file_path}: {e}"
                print(msg)
                if on_error:
                    on_error(msg)
                if on_file_done:
                    on_file_done()
                continue
            if on_file_done:
                on_file_done()

    return good_count, review_count
