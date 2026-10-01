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
Формат строк good.txt/needs_review.txt (``{crop_rel}\\t{text}\\n``, опционально
с ``\\t{w}\\t{h}`` — общий backend.pipeline._dataset_line) и записей
debug.jsonl — идентичен классическому, только score всегда 1.0 (VLM per-line
confidence не дают).

Две системы координат страницы (см. _process_page): модели видят копию,
уменьшенную до <= VLM_MAX_IMAGE_SIDE (vlm_client.downscale_page), и боксы
парсеров/IoU-группировка живут в её пикселях; кропы же режутся из
ОРИГИНАЛА — бокс переводится обратно в полное разрешение, чтобы обучающие
кропы не теряли чёткость на крупных сканах/фото.

Порядок обхода — «модель за моделью» (см. run()): все модели обслуживает один
llama-server, который держит в памяти не больше одной модели (--models-max 1,
CPU без GPU). Постраничный опрос всех моделей подряд перезагружал бы модели на
каждой странице; вместо этого вся папка проходится первой моделью, потом
второй и т.д. — смен моделей ровно len(vlm_engines). Результаты ранних моделей
копятся в памяти (только боксы+текст), последняя модель пишет строки сразу.
"""

import json
import logging
import os
from typing import Callable, Dict, Iterator, List, Optional, Tuple

import numpy as np
import pypdfium2 as pdfium
from PIL import Image

from backend import pdf_extract, vlm_adapters, vlm_client, vlm_consensus, vlm_layout
from backend.config import (
    DEFAULT_IOU_THRESHOLD,
    DEFAULT_VLM_MIN_AGREE,
    VLM_ENGINE_META,
    VLM_MAX_IMAGE_SIDE,
)
from backend.pipeline import (
    _crop_paths,
    _dataset_line,
    _is_big_enough,
    _resume_img_count,
    _save_crop,
    crop_by_polygon,
    list_input_files,
)
from backend.vlm_geometry import scale_polygon

logger = logging.getLogger(__name__)

PageLines = Dict[str, List[Tuple[list, str]]]
# (путь файла, индекс страницы) — ключ накопленных строк между проходами моделей.
PageKey = Tuple[str, int]


def _cancelled(should_cancel: Optional[Callable[[], bool]]) -> bool:
    return bool(should_cancel and should_cancel())


class _PageSpace:
    """Оригинал страницы + уменьшенная копия для моделей и масштаб между ними."""

    def __init__(self, original: np.ndarray):
        self.original = original
        self.page = vlm_client.downscale_page(original)
        self.sx = original.shape[1] / self.page.shape[1]
        self.sy = original.shape[0] / self.page.shape[0]

    def to_original(self, poly) -> list:
        return scale_polygon(poly, self.sx, self.sy)

    def to_page(self, poly) -> list:
        return scale_polygon(poly, 1 / self.sx, 1 / self.sy)

    def crop(self, page_poly) -> np.ndarray:
        """Кроп в полном разрешении по боксу в координатах уменьшенной страницы."""
        return crop_by_polygon(self.original, self.to_original(page_poly))


def _engine_lines(
    engine: str,
    space: _PageSpace,
    source_label: str,
    on_error: Optional[Callable[[str], None]],
    should_cancel: Optional[Callable[[], bool]],
) -> Optional[List[Tuple[list, str]]]:
    """Один VLM-движок по странице → [(полигон в координатах space.page, текст)]
    или None, если движок ничего не отдал (ошибка клиента/парсера — уходит в
    on_error, движок в группировке не участвует)."""
    strategy = VLM_ENGINE_META[engine]["box_strategy"]

    if strategy == "layout":
        # Детектор строк — по оригиналу (мелкий текст крупного скана на
        # уменьшенной копии теряется), регион в модель — кропом из оригинала.
        try:
            region_boxes = vlm_layout.region_boxes(space.original)
        except Exception as e:  # noqa: BLE001 — детектор свои исключения не гасит
            logger.warning("Ошибка layout-детекции %s: %s — %s", engine, source_label, e)
            region_boxes = []
        lines: List[Tuple[list, str]] = []
        reasons: List[str] = []
        for poly in region_boxes:
            if _cancelled(should_cancel):
                break
            crop = crop_by_polygon(space.original, poly)
            if not _is_big_enough(crop):
                continue
            raw, reason = vlm_client.chat_with_reason(engine, vlm_adapters.PROMPTS[engine], crop)
            if reason:
                reasons.append(reason)
            text = " ".join(vlm_adapters.parse_region_text(raw))
            if text.strip():
                lines.append((space.to_page(poly), text))
        if not lines:
            if on_error:
                on_error(f"{engine}: {_empty_reason(reasons)} — {source_label}")
            return None
        return lines

    height, width = space.page.shape[:2]
    image = _native_model_input(engine, space.page)
    raw, reason = vlm_client.chat_with_reason(engine, vlm_adapters.PROMPTS[engine], image)
    lines = vlm_adapters.parse(engine, raw, width, height)
    if not lines:
        if on_error:
            on_error(f"{engine}: {_empty_reason([reason] if reason else [])} — {source_label}")
        return None
    return lines


def _empty_reason(reasons: List[str]) -> str:
    """Почему движок не дал строк: причина ошибки клиента, иначе модель
    ответила, но парсер не нашёл в ответе ни одной строки с боксом."""
    if reasons:
        return f"ошибка запроса ({', '.join(sorted(set(reasons)))})"
    return "нет строк в ответе модели"


def _native_model_input(engine: str, page: np.ndarray) -> np.ndarray:
    """Картинка для native-движка. Официальная предобработка Spotting у
    PaddleOCR-VL (VLM_ENGINE_META["upscale_below"]): если обе стороны меньше
    порога — увеличить ×2 (LANCZOS). Координаты ответа нормированы к [0, 1000],
    поэтому масштаб картинки на их перевод в пиксели страницы не влияет.

    Увеличение сразу ограничено VLM_MAX_IMAGE_SIDE — одним ресайзом LANCZOS,
    иначе vlm_client._encode_image второй раз ужал бы картинку другим фильтром.
    Официально после ×2 картинку всё равно уменьшает процессор модели до
    image_max_pixels (1605632), так что итоговый размер на входе модели тот же."""
    threshold = VLM_ENGINE_META[engine].get("upscale_below")
    height, width = page.shape[:2]
    if not threshold or width >= threshold or height >= threshold:
        return page
    scale = min(2.0, VLM_MAX_IMAGE_SIDE / max(width, height))
    if scale <= 1.0:
        return page
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    return np.array(Image.fromarray(page).resize(size, Image.Resampling.LANCZOS))


def _safe_engine_lines(
    engine: str,
    space: _PageSpace,
    source_label: str,
    on_error: Optional[Callable[[str], None]],
    should_cancel: Optional[Callable[[], bool]],
) -> Optional[List[Tuple[list, str]]]:
    """_engine_lines, где исключение движка не валит страницу."""
    if _cancelled(should_cancel):
        return None
    try:
        return _engine_lines(engine, space, source_label, on_error, should_cancel)
    except Exception as e:  # noqa: BLE001 — движок не валит страницу
        msg = f"{engine}: ошибка обработки — {source_label}: {e}"
        logger.warning(msg)
        if on_error:
            on_error(msg)
        return None


def _dedup_groups(groups: List[Dict], vlm_min_agree: int) -> List[Dict]:
    """Убирает дубликаты строк внутри страницы: при vlm_min_agree=1 (дефолт)
    и нескольких движках несопоставленный по IoU бокс становится своей
    группой, и одна и та же физическая строка уходит в good.txt 2-3 раза с
    почти одинаковыми кропами. Схлопываем группы с идентичным (после
    postprocess) текстом-победителем и пересекающимися боксами."""
    kept: List[Dict] = []
    seen: List[Tuple[Tuple[int, int, int, int], str]] = []
    for group in groups:
        _, text, _, _ = vlm_consensus.resolve(group, vlm_min_agree)
        bbox = vlm_consensus.polygon_bbox(group["poly"])
        if text and any(
            text == prev_text and vlm_consensus.iou(group["poly"], _bbox_poly(prev_bbox)) > 0
            for prev_bbox, prev_text in seen
        ):
            continue
        kept.append(group)
        if text:
            seen.append((bbox, text))
    return kept


def _bbox_poly(bbox: Tuple[int, int, int, int]) -> list:
    x0, y0, x1, y1 = bbox
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def _write_page(
    space: _PageSpace,
    source_label: str,
    page_lines: PageLines,
    vlm_min_agree: int,
    iou_threshold: float,
    write_line: Callable[[str, str, str, np.ndarray], None],
    allocate_crop_path: Callable[[], Tuple[str, str]],
    on_line_done: Optional[Callable[[str, bool], None]],
    on_error: Optional[Callable[[str], None]],
    write_debug: Optional[Callable[[dict], None]],
) -> None:
    """Сводит строки всех моделей одной страницы (IoU-группировка + голосование)
    и пишет результат. Боксы — в координатах уменьшенной копии, кроп — из
    оригинала в полном разрешении (см. _PageSpace). Отмену не проверяет:
    модели уже отработали, запись страницы дешёвая — дописываем её целиком."""
    if not page_lines:
        return
    groups = vlm_consensus.group_by_iou(page_lines, iou_threshold)
    groups = _dedup_groups(groups, vlm_min_agree)
    for group in groups:
        try:
            bucket, text, engine, diverged = vlm_consensus.resolve(group, vlm_min_agree)
            crop = space.crop(group["poly"])
            if not _is_big_enough(crop):
                continue

            crop_relative, crop_absolute = allocate_crop_path()
            _save_crop(crop, crop_absolute)
            write_line(bucket, crop_relative, text, crop)
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
            logger.warning(msg)
            if on_error:
                on_error(msg)
            continue


def _report(on_error: Optional[Callable[[str], None]], msg: str) -> None:
    logger.warning(msg)
    if on_error:
        on_error(msg)


def _iter_pages(
    file_path: str, on_error: Optional[Callable[[str], None]]
) -> Iterator[Tuple[int, str, np.ndarray]]:
    """(индекс страницы, подпись для сообщений, картинка RGB) страниц файла.

    PDF — всегда в растр (текстовый слой в VLM-режиме не используется, см.
    backend/README.md). Нечитаемый файл/страница пропускается с сообщением в
    on_error; ранние проходы моделей зовут с on_error=None, чтобы одна и та же
    ошибка чтения не дублировалась на каждую модель (её сообщит последний проход)."""
    if not file_path.lower().endswith(".pdf"):
        try:
            image = np.array(Image.open(file_path).convert("RGB"))
        except Exception as e:  # noqa: BLE001
            _report(on_error, f"Ошибка обработки файла {file_path}: {e}")
            return
        yield 0, file_path, image
        return

    try:
        pdf_doc = pdfium.PdfDocument(file_path)
    except Exception as e:  # noqa: BLE001
        _report(on_error, f"Ошибка обработки файла {file_path}: {e}")
        return
    try:
        for page_index in range(len(pdf_doc)):
            source_label = f"{file_path} (страница {page_index + 1})"
            page = pdf_doc[page_index]
            try:
                image = pdf_extract.render_page(page)
            except Exception as e:  # noqa: BLE001
                _report(on_error, f"Ошибка рендеринга {source_label}: {e}")
                continue
            finally:
                page.close()
            yield page_index, source_label, image
    finally:
        pdf_doc.close()


def _collect_engine_pass(
    engine: str,
    files: List[str],
    collected: Dict[PageKey, PageLines],
    on_error: Optional[Callable[[str], None]],
    should_cancel: Optional[Callable[[], bool]],
) -> None:
    """Проход одной (не последней) модели по всем страницам: строки копятся в
    collected[(файл, страница)][engine] до финального прохода."""
    for file_path in files:
        if _cancelled(should_cancel):
            return
        for page_index, source_label, image in _iter_pages(file_path, None):
            if _cancelled(should_cancel):
                return
            lines = _safe_engine_lines(
                engine, _PageSpace(image), source_label, on_error, should_cancel
            )
            if lines:
                collected.setdefault((file_path, page_index), {})[engine] = lines


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
    append_crop_size: bool = False,
) -> Tuple[int, int]:
    """Обрабатывает папку документов через одну или несколько VLM.

    vlm_engines — подмножество backend.config.VLM_ENGINES; vlm_min_agree —
    сколько движков должны отдать совпадающий по IoU бокс с одинаковым текстом
    для "good"; iou_threshold — порог сопоставления боксов разных движков.
    append_crop_size — дописывать в строку датасета ширину/высоту кропа
    (см. backend.pipeline._dataset_line).

    Обход «модель за моделью» (см. докстринг модуля): все модели, кроме
    последней, проходят папку и копят строки; последняя проходит её, сводит
    строки страницы и сразу пишет результат. С одной моделью — это обычный
    постраничный проход с немедленной записью. Прогресс по документам
    (on_file_done) и строки (on_line_done) идут в последнем проходе.

    Возвращает (кол-во хороших строк, кол-во строк на проверку) и пишет
    good.txt/needs_review.txt/debug.jsonl в output_dir (перезаписываются на
    каждый запуск; кропы в crops/ нумеруются сквозняком, продолжая с прошлого
    максимума на диске — см. backend.pipeline._resume_img_count).

    should_cancel() проверяется перед каждым файлом/страницей И между VLM-
    вызовами (один вызов на CPU может идти минуты). После отмены строки, уже
    полученные ранними моделями, всё равно записываются (без новых вызовов).
    """
    if not vlm_engines:
        raise ValueError("vlm_engines должен быть непустым подмножеством VLM_ENGINES")

    os.makedirs(output_dir, exist_ok=True)

    matched_files, pdf_files = list_input_files(input_dir)
    files = matched_files + pdf_files

    if on_found:
        on_found(len(files))

    good_count = 0
    review_count = 0
    img_count = _resume_img_count(output_dir)

    with (
        open(os.path.join(output_dir, "good.txt"), "w", encoding="utf-8") as good_file,
        open(os.path.join(output_dir, "needs_review.txt"), "w", encoding="utf-8") as review_file,
        open(os.path.join(output_dir, "debug.jsonl"), "w", encoding="utf-8") as debug_file,
    ):

        def write_line(bucket: str, crop_relative: str, text: str, crop: np.ndarray) -> None:
            nonlocal good_count, review_count
            target = good_file if bucket == "good" else review_file
            target.write(_dataset_line(crop_relative, text, crop, append_crop_size))
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

        collected: Dict[PageKey, PageLines] = {}
        for engine in vlm_engines[:-1]:
            _collect_engine_pass(engine, files, collected, on_error, should_cancel)

        # Финальный проход. После отмены модели больше не вызываются, но строки,
        # уже накопленные ранними моделями (часы работы на CPU), дописываются:
        # голосование честно отправит в needs_review то, чему не хватило согласия.
        final_engine = vlm_engines[-1]
        for file_path in files:
            pending_pages = {page for path, page in collected if path == file_path}
            if _cancelled(should_cancel) and not pending_pages:
                continue
            for page_index, source_label, image in _iter_pages(file_path, on_error):
                stopping = _cancelled(should_cancel)
                if stopping and page_index not in pending_pages:
                    continue
                space = _PageSpace(image)
                page_lines = collected.pop((file_path, page_index), {})
                if not stopping:
                    lines = _safe_engine_lines(
                        final_engine, space, source_label, on_error, should_cancel
                    )
                    if lines:
                        page_lines[final_engine] = lines
                # Порядок движков = порядок vlm_engines (приоритет опорного бокса
                # в group_by_iou), а не порядок, в котором они отработали.
                ordered = {e: page_lines[e] for e in vlm_engines if e in page_lines}
                _write_page(
                    space,
                    source_label,
                    ordered,
                    vlm_min_agree,
                    iou_threshold,
                    write_line,
                    allocate_crop_path,
                    on_line_done,
                    on_error,
                    write_debug,
                )
            if on_file_done:
                on_file_done()

    return good_count, review_count
