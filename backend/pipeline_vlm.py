"""VLM-путь авторазметки: страница целиком → HTTP к VLM → боксы+текст.

Отдельный от backend/pipeline.py модуль (тот жёстко построчный: детектор →
кроп → recognize_* → vote; здесь — постранично: страница → один forward VLM →
парсер → IoU-группировка нескольких моделей). Общее с классическим путём —
только запись файлов и сквозная нумерация кропов: приваты _resume_img_count/
_crop_paths/_save_crop/MIN_CROP_PIX импортируются из backend.pipeline, не
копируются (хрупкая связка, отмечена в docs/architecture.md).

run() повторяет сигнатуру и семантику callback'ов backend.pipeline.run
(on_found/on_file_done/on_line_done/on_error/should_cancel), поэтому
backend/jobs.py выбирает run_fn по mode без ветвления по полям трекера.
Формат строк good.txt/needs_review.txt (``{crop_rel}\\t{text}\\n``) и записей
debug.jsonl — идентичен классическому, только score всегда 1.0 (VLM per-line
confidence не дают).
"""

import json
import os
from glob import glob
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pypdfium2 as pdfium
from PIL import Image

from backend import pdf_extract, vlm_adapters, vlm_client, vlm_consensus, vlm_layout
from backend.config import (
    DEFAULT_IOU_THRESHOLD,
    DEFAULT_VLM_MIN_AGREE,
    IMAGE_EXTENSIONS,
    PDF_EXTENSIONS,
    VLM_ENGINE_META,
)
from backend.pipeline import MIN_CROP_PIX, _crop_paths, _resume_img_count, _save_crop

PageLines = Dict[str, List[Tuple[list, str]]]


def _cancelled(should_cancel: Optional[Callable[[], bool]]) -> bool:
    return bool(should_cancel and should_cancel())


def _crop_by_bbox(numpy_image: np.ndarray, poly) -> np.ndarray:
    """Вырезает кроп по bbox полигона, зажимая координаты в границы страницы.

    Координаты приходят из свободного вывода VLM (спот-регекс, промилле,
    округление) и бывают отрицательными / за краем — без clamp отрицательный
    старт в numpy-срезе трактуется как индекс с конца и даёт кроп не с того
    места страницы."""
    height, width = numpy_image.shape[:2]
    x0, y0, x1, y1 = vlm_consensus.polygon_bbox(poly)
    x0 = max(0, min(int(x0), width))
    x1 = max(0, min(int(x1), width))
    y0 = max(0, min(int(y0), height))
    y1 = max(0, min(int(y1), height))
    return numpy_image[y0:y1, x0:x1]


def _engine_lines(
    engine: str,
    numpy_image: np.ndarray,
    source_label: str,
    on_error: Optional[Callable[[str], None]],
    should_cancel: Optional[Callable[[], bool]],
) -> Optional[List[Tuple[list, str]]]:
    """Один VLM-движок по странице → [(полигон, текст)] или None, если движок
    ничего не отдал (ошибка клиента/парсера — уходит в on_error, движок в
    группировке не участвует)."""
    height, width = numpy_image.shape[:2]
    strategy = VLM_ENGINE_META[engine]["box_strategy"]

    if strategy == "layout":
        try:
            region_boxes = vlm_layout.merged_region_boxes(numpy_image)
        except Exception as e:  # noqa: BLE001 — детектор свои исключения не гасит
            print(f"Ошибка layout-детекции {engine}: {source_label} — {e}")
            region_boxes = []
        lines: List[Tuple[list, str]] = []
        for poly in region_boxes:
            if _cancelled(should_cancel):
                break
            crop = _crop_by_bbox(numpy_image, poly)
            if crop.shape[0] <= MIN_CROP_PIX or crop.shape[1] <= MIN_CROP_PIX:
                continue
            raw = vlm_client.chat(engine, vlm_adapters.PROMPTS[engine], crop)
            text = " ".join(vlm_adapters.parse_glm_ocr(raw))
            if text.strip():
                lines.append((poly, text))
        if not lines:
            if on_error:
                on_error(f"{engine}: пустой ответ — {source_label}")
            return None
        return lines

    raw = vlm_client.chat(engine, vlm_adapters.PROMPTS[engine], numpy_image)
    lines = vlm_adapters.parse(engine, raw, width, height)
    if not lines:
        if on_error:
            on_error(f"{engine}: пустой ответ — {source_label}")
        return None
    return lines


def _process_page(
    numpy_image: np.ndarray,
    source_label: str,
    vlm_engines: List[str],
    vlm_min_agree: int,
    iou_threshold: float,
    write_line: Callable[[str, str], None],
    allocate_crop_path: Callable[[], Tuple[str, str]],
    on_line_done: Optional[Callable[[str, bool], None]],
    on_error: Optional[Callable[[str], None]],
    should_cancel: Optional[Callable[[], bool]],
    write_debug: Optional[Callable[[dict], None]],
) -> None:
    """Прогоняет одну страницу через выбранные VLM и пишет строки результата."""
    page_lines: PageLines = {}
    for engine in vlm_engines:
        if _cancelled(should_cancel):
            return
        try:
            lines = _engine_lines(engine, numpy_image, source_label, on_error, should_cancel)
        except Exception as e:  # noqa: BLE001 — движок не валит страницу
            msg = f"{engine}: ошибка обработки — {source_label}: {e}"
            print(msg)
            if on_error:
                on_error(msg)
            lines = None
        if lines is not None:
            page_lines[engine] = lines

    if not page_lines:
        return

    groups = vlm_consensus.group_by_iou(page_lines, iou_threshold)
    for group in groups:
        if _cancelled(should_cancel):
            return
        try:
            bucket, text, engine, diverged = vlm_consensus.resolve(group, vlm_min_agree)
            crop = _crop_by_bbox(numpy_image, group["poly"])
            if crop.shape[0] <= MIN_CROP_PIX or crop.shape[1] <= MIN_CROP_PIX:
                continue

            crop_relative, crop_absolute = allocate_crop_path()
            _save_crop(crop, crop_absolute)
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
                            eng: {"text": t, "score": 1.0} for eng, t in group["texts"].items()
                        },
                    }
                )
        except Exception as e:  # noqa: BLE001 — как _process_boxes: строка не валит job
            msg = f"Ошибка записи строки в {source_label}: {e}"
            print(msg)
            if on_error:
                on_error(msg)
            continue


def run(
    input_dir: str,
    output_dir: str,
    *,
    vlm_engines: Optional[List[str]] = None,
    vlm_min_agree: int = DEFAULT_VLM_MIN_AGREE,
    iou_threshold: float = DEFAULT_IOU_THRESHOLD,
    on_found: Optional[Callable[[int], None]] = None,
    on_file_done: Optional[Callable[[], None]] = None,
    on_line_done: Optional[Callable[[str, bool], None]] = None,
    on_error: Optional[Callable[[str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> Tuple[int, int]:
    """Обрабатывает папку документов через одну или несколько VLM.

    vlm_engines — подмножество backend.config.VLM_ENGINES; vlm_min_agree —
    сколько движков должны отдать совпадающий по IoU бокс с одинаковым текстом
    для "good"; iou_threshold — порог сопоставления боксов разных движков.

    Возвращает (кол-во хороших строк, кол-во строк на проверку) и пишет
    good.txt/needs_review.txt/debug.jsonl в output_dir (перезаписываются на
    каждый запуск; кропы в crops/ нумеруются сквозняком, продолжая с прошлого
    максимума на диске — см. backend.pipeline._resume_img_count).

    should_cancel() проверяется перед каждым файлом/страницей И между VLM-
    вызовами (один вызов на CPU может идти минуты).
    """
    if not vlm_engines:
        raise ValueError("vlm_engines должен быть непустым подмножеством VLM_ENGINES")

    os.makedirs(output_dir, exist_ok=True)

    matched_files: List[str] = []
    for ext in IMAGE_EXTENSIONS:
        matched_files.extend(glob(os.path.join(input_dir, f"*{ext}")))
    pdf_files: List[str] = []
    for ext in PDF_EXTENSIONS:
        pdf_files.extend(glob(os.path.join(input_dir, f"*{ext}")))

    if on_found:
        on_found(len(matched_files) + len(pdf_files))

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
            if _cancelled(should_cancel):
                break
            try:
                numpy_image = np.array(Image.open(file_path).convert("RGB"))
            except Exception as e:  # noqa: BLE001
                msg = f"Ошибка обработки файла {file_path}: {e}"
                print(msg)
                if on_error:
                    on_error(msg)
                if on_file_done:
                    on_file_done()
                continue

            _process_page(
                numpy_image,
                file_path,
                vlm_engines,
                vlm_min_agree,
                iou_threshold,
                write_line,
                allocate_crop_path,
                on_line_done,
                on_error,
                should_cancel,
                write_debug,
            )
            if on_file_done:
                on_file_done()

        for file_path in pdf_files:
            if _cancelled(should_cancel):
                break
            try:
                _process_pdf(
                    file_path,
                    vlm_engines,
                    vlm_min_agree,
                    iou_threshold,
                    write_line,
                    allocate_crop_path,
                    on_line_done,
                    on_error,
                    should_cancel,
                    write_debug,
                )
            except Exception as e:  # noqa: BLE001
                msg = f"Ошибка обработки файла {file_path}: {e}"
                print(msg)
                if on_error:
                    on_error(msg)
            if on_file_done:
                on_file_done()

    return good_count, review_count


def _process_pdf(
    file_path: str,
    vlm_engines: List[str],
    vlm_min_agree: int,
    iou_threshold: float,
    write_line: Callable[[str, str], None],
    allocate_crop_path: Callable[[], Tuple[str, str]],
    on_line_done: Optional[Callable[[str, bool], None]],
    on_error: Optional[Callable[[str], None]],
    should_cancel: Optional[Callable[[], bool]],
    write_debug: Optional[Callable[[dict], None]],
) -> None:
    """PDF постранично — всегда в растр (текстовый слой в VLM-режиме не трогаем,
    см. docs/architecture.md / backend/README.md)."""
    pdf_doc = pdfium.PdfDocument(file_path)
    try:
        for page_index in range(len(pdf_doc)):
            if _cancelled(should_cancel):
                break
            source_label = f"{file_path} (страница {page_index + 1})"
            try:
                numpy_image = pdf_extract.render_page(pdf_doc[page_index])
            except Exception as e:  # noqa: BLE001
                msg = f"Ошибка рендеринга {source_label}: {e}"
                print(msg)
                if on_error:
                    on_error(msg)
                continue
            _process_page(
                numpy_image,
                source_label,
                vlm_engines,
                vlm_min_agree,
                iou_threshold,
                write_line,
                allocate_crop_path,
                on_line_done,
                on_error,
                should_cancel,
                write_debug,
            )
    finally:
        pdf_doc.close()
