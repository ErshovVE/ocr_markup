import contextlib
import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, FrozenSet, List, Optional, Tuple

import numpy as np
import pypdfium2 as pdfium
from PIL import Image

from backend import degrade as page_degrade
from backend import pdf_extract
from backend.config import (
    CROP_FILENAME_DIGITS,
    CROPS_PER_FOLDER,
    DEFAULT_ENGINES,
    DEFAULT_MIN_AGREE,
    DETECTOR_CALL_TIMEOUT_SECONDS,
    ENGINE_CALL_TIMEOUT_SECONDS,
    IMAGE_EXTENSIONS,
    PDF_EXTENSIONS,
    RECOGNITION_BATCH_SIZE,
    VLM_REQUEST_TIMEOUT_SECONDS,
)
from backend.consensus import vote
from backend.detector import DEFAULT_DETECTOR_ENGINE, Detector
from backend.labels import normalize_label, out_of_alphabet
from backend.recognizers import (
    DEFAULT_LATIN_MODEL_SIZE,
    EMPTY_RESULT,
    recognize_custom_batch,
    recognize_paddle_batch,
    recognize_paddle_latin_batch,
    recognize_surya_batch,
    recognize_tesseract_batch,
    recognize_vlm_line_batch,
)
from backend.text_keys import DEFAULT_VOTE_KEY, vote_key
from backend.vlm_geometry import clamped_bbox

MIN_CROP_PIX = 10

# Потолок против decompression-bomb для картинок из произвольного input_dir
# (глобально на процесс). За 2× порога — Image.DecompressionBombError, его
# ловят per-file try/except и рапортуют через on_error, не роняя job.
Image.MAX_IMAGE_PIXELS = 64_000_000

logger = logging.getLogger(__name__)

# recognize_* каждого движка ходят в один общий module-level предиктор
# (backend/recognizers.py::_Engines) — он не thread-safe. Пер-движковый лок
# гарантирует, что даже когда прошлый вызов завис и его поток брошен (см.
# ниже), следующий вызов того же движка НЕ войдёт в предиктор параллельно:
# он подождёт лок до дедлайна и, не дождавшись, вернёт ("", 0.0).
_ENGINE_LOCKS: Dict[str, threading.Lock] = {
    "paddle": threading.Lock(),
    "surya": threading.Lock(),
    "tesseract": threading.Lock(),
    # custom — свой предиктор PaddleOCR (не thread-safe, как paddle); vlm_line
    # потокобезопасен (HTTP), но лок нужен для streak-гвардии и брошенных потоков.
    "custom": threading.Lock(),
    "vlm_line": threading.Lock(),
    # Детектор строк — та же защита (см. _detect_with_timeout): зависший
    # detect() не вешает job, три зависания подряд снимают его до конца job'а.
    "detector": threading.Lock(),
}
# После скольких таймаутов ПОДРЯД считать движок зависшим и снять его с
# расписания до конца job'а (иначе каждая строка большой папки платит полный
# ENGINE_CALL_TIMEOUT_SECONDS впустую, а брошенные потоки копятся).
_MAX_ENGINE_TIMEOUT_STREAK = 3
_engine_timeout_streak: Dict[str, int] = {}
_engine_disabled: set = set()


@dataclass
class RecognitionOptions:
    """Параметры распознавания сверх классических движков — общие для
    консенсуса по страницам (run) и по готовым кропам (backend/pipeline_crops.py).

    custom_model_dir — экспорт своей модели PaddleOCR (движок "custom");
    line_vlm_engine — VLM для построчного чтения (движок "vlm_line", см.
    config.LINE_VLM_ENGINES); vote_key — ключ сравнения текстов в vote()
    (backend/text_keys.py)."""

    custom_model_dir: Optional[str] = None
    line_vlm_engine: Optional[str] = None
    vote_key: str = DEFAULT_VOTE_KEY


def reset_engine_guard() -> None:
    """Сбрасывает счётчики зависаний движков — вызывается в начале run()."""
    _engine_timeout_streak.clear()
    _engine_disabled.clear()


def _run_engines_with_timeout(
    calls: Dict[str, Tuple[Callable, tuple]],
    timeout: float,
    source_label: str,
    on_error: Optional[Callable[[str], None]] = None,
    empty_result=EMPTY_RESULT,
    engine_timeouts: Optional[Dict[str, float]] = None,
) -> Dict[str, object]:
    """Запускает несколько recognize_*-вызовов параллельно с общим таймаутом на все вместе.

    engine_timeouts — свой бюджет для отдельных движков (например, vlm_line:
    VLM на CPU отвечает минутами); остальные ждут timeout. Отсчёт у всех от
    одного старта, поэтому медленный VLM не растягивает ожидание зависшего
    Paddle/Surya в том же батче.

    calls: {имя_движка: (функция, аргументы)}. Если вызов не уложился в общий
    таймаут, для этого движка возвращается empty_result (для батча строк —
    список пустых результатов той же длины, см. _recognize_batch).

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

    Движок (paddle/surya/tesseract), зависший _MAX_ENGINE_TIMEOUT_STREAK раз
    подряд, до конца job'а больше не запускается (reset_engine_guard() в
    начале run()).
    """
    active = {name: spec for name, spec in calls.items() if name not in _engine_disabled}
    result_box: Dict[str, object] = {}

    def make_target(name: str, fn: Callable, args: tuple):
        def target() -> None:
            lock = _ENGINE_LOCKS.get(name)
            if lock is None:
                result_box[name] = fn(*args)
                return
            with lock:
                result_box[name] = fn(*args)

        return target

    threads = {
        name: threading.Thread(
            target=make_target(name, fn, args), daemon=True, name=f"ocr-engine-{name}"
        )
        for name, (fn, args) in active.items()
    }
    for thread in threads.values():
        thread.start()

    started = time.monotonic()
    engine_timeouts = engine_timeouts or {}
    results: Dict[str, object] = {name: empty_result for name in calls}
    # Сначала движки с коротким бюджетом: join() идут по очереди, и короткий
    # дедлайн не должен ждать, пока истечёт длинный.
    for name, thread in sorted(threads.items(), key=lambda i: engine_timeouts.get(i[0], timeout)):
        engine_timeout = engine_timeouts.get(name, timeout)
        thread.join(max(0.0, started + engine_timeout - time.monotonic()))
        if thread.is_alive():
            msg = f"Таймаут {engine_timeout}с у движка {name}: {source_label}"
            logger.warning(msg)
            if on_error:
                on_error(msg)
            # Гвардия «отключить зависший движок» — только для реальных движков;
            # произвольные имена из юнит-тестов примитива не копят состояние.
            if name in _ENGINE_LOCKS:
                _engine_timeout_streak[name] = _engine_timeout_streak.get(name, 0) + 1
                if _engine_timeout_streak[name] >= _MAX_ENGINE_TIMEOUT_STREAK:
                    _engine_disabled.add(name)
                    disabled_msg = (
                        f"Движок {name} завис {_MAX_ENGINE_TIMEOUT_STREAK} раз подряд — "
                        "отключён до конца задания, перезапустите backend"
                    )
                    logger.error(disabled_msg)
                    if on_error:
                        on_error(disabled_msg)
            results[name] = empty_result
        else:
            if name in _ENGINE_LOCKS:
                _engine_timeout_streak[name] = 0
            results[name] = result_box.get(name, empty_result)
    return results


def _build_engine_calls(
    engines: List[str],
    crops: List[np.ndarray],
    lang: str,
    latin_model_size: str,
    tesseract_lang: str,
    options: Optional[RecognitionOptions] = None,
    on_error: Optional[Callable[[str], None]] = None,
) -> Dict[str, Tuple[Callable, tuple]]:
    """Собирает {имя_движка: (функция, аргументы)} только для выбранных
    движков (см. RunRequest.engines в backend/main.py). Каждый вызов —
    батч: один и тот же список кропов строк на все движки, результат —
    список (text, score) в том же порядке. custom/vlm_line берут модель из
    options (main.py не пропускает их без custom_model_dir/line_vlm_engine)."""
    options = options or RecognitionOptions()
    calls: Dict[str, Tuple[Callable, tuple]] = {}
    if "paddle" in engines:
        if lang == "ru":
            calls["paddle"] = (recognize_paddle_batch, (crops,))
        else:
            calls["paddle"] = (recognize_paddle_latin_batch, (crops, latin_model_size))
    if "surya" in engines:
        calls["surya"] = (recognize_surya_batch, (crops,))
    if "tesseract" in engines:
        calls["tesseract"] = (recognize_tesseract_batch, (crops, tesseract_lang))
    if "custom" in engines:
        calls["custom"] = (recognize_custom_batch, (crops, options.custom_model_dir))
    if "vlm_line" in engines:
        calls["vlm_line"] = (recognize_vlm_line_batch, (crops, options.line_vlm_engine, on_error))
    return calls


def crop_by_polygon(numpy_image: np.ndarray, poly) -> np.ndarray:
    """Кроп строки по bbox полигона, зажатому в границы картинки — общий для
    классического пути, текстового слоя PDF и VLM-пути (см.
    backend/vlm_geometry.py::clamped_bbox: все вершины, а не box[0]/box[2])."""
    height, width = numpy_image.shape[:2]
    x0, y0, x1, y1 = clamped_bbox(poly, width, height)
    return numpy_image[y0:y1, x0:x1]


def _detect_with_timeout(
    detector: Detector,
    numpy_image: np.ndarray,
    source_label: str,
    on_error: Optional[Callable[[str], None]],
) -> list:
    """detect() с таймаутом DETECTOR_CALL_TIMEOUT_SECONDS — раньше зависший
    детектор вешал весь job без единого сигнала в UI. Не уложился → []
    (страница пропускается, ошибка уходит в on_error). Сам детектор (загрузка
    модели, возможно со скачиванием) создаётся вызывающим ДО этого вызова и
    в таймаут не входит."""
    result = _run_engines_with_timeout(
        {"detector": (detector.detect, (numpy_image,))},
        DETECTOR_CALL_TIMEOUT_SECONDS,
        source_label,
        on_error=on_error,
        empty_result=[],
    )
    return result["detector"]


def _is_big_enough(crop: np.ndarray) -> bool:
    return crop.shape[0] > MIN_CROP_PIX and crop.shape[1] > MIN_CROP_PIX


def _recognize_batch(
    crops: List[np.ndarray],
    engines: List[str],
    lang: str,
    latin_model_size: str,
    tesseract_lang: str,
    source_label: str,
    on_error: Optional[Callable[[str], None]],
    options: Optional[RecognitionOptions] = None,
) -> List[Dict[str, Tuple[str, float]]]:
    """Батч кропов → по строке {движок: (text, score)}.

    Движки идут параллельно, каждый — одним вызовом на весь батч. Бюджет
    времени — ENGINE_CALL_TIMEOUT_SECONDS на строку × размер батча (тот же,
    что был у построчного вызова); у vlm_line свой — VLM_REQUEST_TIMEOUT_SECONDS
    на строку (VLM на CPU отвечает минутами), остальные движки его не ждут.
    Не уложившийся движок даёт пустые результаты на все строки батча."""
    calls = _build_engine_calls(
        engines, crops, lang, latin_model_size, tesseract_lang, options, on_error
    )
    empty = [EMPTY_RESULT] * len(crops)
    per_engine = _run_engines_with_timeout(
        calls,
        ENGINE_CALL_TIMEOUT_SECONDS * len(crops),
        f"{source_label} ({len(crops)} строк)",
        on_error=on_error,
        empty_result=empty,
        engine_timeouts={"vlm_line": VLM_REQUEST_TIMEOUT_SECONDS * len(crops)},
    )
    rows: List[Dict[str, Tuple[str, float]]] = [{} for _ in crops]
    for name, results in per_engine.items():
        if not isinstance(results, list) or len(results) != len(crops):
            msg = f"Движок {name} вернул некорректный батч: {source_label}"
            logger.warning(msg)
            if on_error:
                on_error(msg)
            results = empty
        for row, result in zip(rows, results, strict=True):
            row[name] = result
    return rows


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
    """Сохраняет кроп по уже выделенному пути (см. allocate_crop_path в run()).

    WebP без потерь: кроп — обучающий пример, а дефолт Pillow для WEBP —
    lossy quality=80, который мылит мелкие буквы. quality=101 (так lossless
    включается в OpenCV) Pillow не принимает — у него это отдельный флаг
    lossless=True; quality при нём — усилие сжатия, а не качество."""
    os.makedirs(os.path.dirname(absolute_path), exist_ok=True)
    Image.fromarray(img_crop).save(absolute_path, "WEBP", lossless=True, quality=100)


def _dataset_line(crop_relative: str, text: str, crop: np.ndarray, append_crop_size: bool) -> str:
    """Строка good.txt/needs_review.txt: "{кроп}\\t{текст}", при append_crop_size —
    ещё "\\t{w}\\t{h}" (размер кропа в пикселях, как он сохранён на диск).
    Общая для классического и VLM-пути (backend/pipeline_vlm.py)."""
    if append_crop_size:
        height, width = crop.shape[:2]
        return f"{crop_relative}\t{text}\t{width}\t{height}\n"
    return f"{crop_relative}\t{text}\n"


def _finalize_line(
    bucket: str, text: str, normalize_labels: bool, alphabet: Optional[FrozenSet[str]]
) -> Tuple[str, str]:
    """Итоговые (корзина, текст) строки датасета: normalize_labels — типографские
    варианты символов -> символы словаря (backend/labels.py); alphabet — строка
    "good" с символами вне словаря модели уходит в needs_review (метка из чужого
    текстового слоя/OCR с мусором не попадает в обучение без проверки).
    Общая для классического и VLM-пути."""
    if normalize_labels:
        text = normalize_label(text)
    if alphabet is not None and bucket == "good" and out_of_alphabet(text, alphabet):
        bucket = "needs_review"
    return bucket, text


def list_input_files(input_dir: str) -> Tuple[List[str], List[str]]:
    """Входные документы папки (без рекурсии): (картинки, PDF), каждый список
    отсортирован по имени.

    Расширение сравнивается без учёта регистра — glob("*.jpg") в Linux-
    контейнере не видел .JPG/.PNG с камер и сканеров, и задание молча
    находило 0 документов. os.scandir вместо glob — спецсимволы glob
    ([, ], *, ?) в имени папки больше не ломают поиск. Сортировка делает
    сквозную нумерацию кропов воспроизводимой между запусками.
    """
    images: List[str] = []
    pdfs: List[str] = []
    with os.scandir(input_dir) as entries:
        for entry in entries:
            if not entry.is_file():
                continue
            ext = os.path.splitext(entry.name)[1].lower()
            if ext in IMAGE_EXTENSIONS:
                images.append(entry.path)
            elif ext in PDF_EXTENSIONS:
                pdfs.append(entry.path)
    return sorted(images), sorted(pdfs)


def _process_boxes(
    numpy_image: np.ndarray,
    boxes,
    threshold: float,
    preferred_model: Optional[str],
    lang: str,
    latin_model_size: str,
    tesseract_lang: str,
    source_label: str,
    write_line: Callable[[str, str, str, np.ndarray], str],
    allocate_crop_path: Callable[[], Tuple[str, str]],
    on_line_done: Optional[Callable[[str, bool], None]] = None,
    on_error: Optional[Callable[[str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    write_debug: Optional[Callable[[dict], None]] = None,
    engines: List[str] = DEFAULT_ENGINES,
    min_agree: int = DEFAULT_MIN_AGREE,
    detector_engine: str = "paddle",
    options: Optional[RecognitionOptions] = None,
) -> None:
    """Прогоняет обнаруженные детектором боксы через консенсус выбранных движков.

    Батчами по RECOGNITION_BATCH_SIZE строк: каждый движок получает весь
    батч кропов одним вызовом (движки — параллельно друг с другом), затем
    по каждой строке — vote() и немедленная запись. Раньше каждый движок
    вызывался на каждую строку отдельно с batch_size=1 (а Surya ещё и
    получала всю страницу ради одного бокса). Батч ограничен по размеру,
    чтобы прогресс/отмена/таймаут оставались гранулярными на плотных
    страницах. Кроп режется один раз и одинаков для всех движков
    (crop_by_polygon).

    engines/min_agree — выбранная на фронтенде схема ("1 из 1"/"1 из 2"/
    "2 из 2"/"2 из 3", см. frontend/src/ui/generation_view.py): engines —
    какие движки распознавания вообще запускать на строку, min_agree —
    сколько из них должны выдать одинаковый текст для vote() (backend/consensus.py).

    detector_engine — только для эвристики многострочных боксов ниже
    (детектор Surya иногда объединяет 2-3 строки в один бокс; сама
    детекция уже отработала к этому моменту, здесь только гейт на то, каким
    движком она была сделана).

    Общая логика для растровых изображений и страниц PDF без текстового слоя
    (см. run()/_process_pdf()). write_line(bucket, crop_rel, text, crop) пишет строку в
    good.txt/needs_review.txt сразу после голосования (см. run()) — если
    задание упадёт на середине большой папки, готовые строки не теряются.
    on_line_done(bucket, diverged) — живой прогресс для трекера
    (backend/jobs.py); on_error(msg) — ошибка/таймаут, видимые в /status;
    should_cancel() — кооперативная отмена, проверяется перед каждым батчем
    и перед записью каждой строки. write_debug(record) — JSON-запись на
    строку с текстами/score всех движков (vote() оставляет только
    победителя). allocate_crop_path() — следующий путь кропа по сквозной
    нумерации (см. run()/_resume_img_count).
    """
    crops = []
    for box in boxes:
        try:
            crop = crop_by_polygon(numpy_image, box)
        except Exception as e:
            msg = f"Некорректный бокс детектора в {source_label}: {e}"
            logger.warning(msg)
            if on_error:
                on_error(msg)
            continue
        if _is_big_enough(crop):
            crops.append(crop)

    for start in range(0, len(crops), RECOGNITION_BATCH_SIZE):
        if should_cancel and should_cancel():
            return
        batch = crops[start : start + RECOGNITION_BATCH_SIZE]
        rows = _recognize_batch(
            batch, engines, lang, latin_model_size, tesseract_lang, source_label, on_error, options
        )
        for img_crop, results in zip(batch, rows, strict=True):
            if should_cancel and should_cancel():
                return
            _write_voted_line(
                img_crop,
                results,
                threshold,
                preferred_model,
                min_agree,
                detector_engine,
                source_label,
                write_line,
                allocate_crop_path,
                on_line_done,
                on_error,
                write_debug,
                options,
            )


def _write_voted_line(
    img_crop: np.ndarray,
    results: Dict[str, Tuple[str, float]],
    threshold: float,
    preferred_model: Optional[str],
    min_agree: int,
    detector_engine: str,
    source_label: str,
    write_line: Callable[[str, str, str, np.ndarray], str],
    allocate_crop_path: Callable[[], Tuple[str, str]],
    on_line_done: Optional[Callable[[str, bool], None]],
    on_error: Optional[Callable[[str], None]],
    write_debug: Optional[Callable[[dict], None]],
    options: Optional[RecognitionOptions] = None,
) -> None:
    """Голосование по одной строке батча + запись кропа/строки/debug."""
    try:
        if detector_engine == "surya":
            multiline_engines = [name for name, (t, _) in results.items() if "\n" in t]
            if multiline_engines:
                msg = (
                    f"Похоже, детектор Surya объединил несколько строк в один бокс "
                    f"(перевод строки в ответе {', '.join(multiline_engines)}): "
                    f"{source_label} — строка пропущена"
                )
                logger.warning(msg)
                if on_error:
                    on_error(msg)
                return

        key = vote_key(options.vote_key) if options else None
        bucket, text, engine, diverged = vote(
            results, threshold, preferred_model, min_agree, key=key
        )

        crop_relative, crop_absolute = allocate_crop_path()
        _save_crop(img_crop, crop_absolute)
        bucket = write_line(bucket, crop_relative, text, img_crop)
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
                        name: {"text": t, "score": sc} for name, (t, sc) in results.items()
                    },
                }
            )
    except Exception as e:
        msg = f"Ошибка распознавания строки в {source_label}: {e}"
        logger.warning(msg)
        if on_error:
            on_error(msg)


def _process_pdf(
    file_path: str,
    get_detector: Callable[[], Detector],
    threshold: float,
    preferred_model: Optional[str],
    lang: str,
    latin_model_size: str,
    tesseract_lang: str,
    extract_pdf_text_layer: bool,
    write_line: Callable[[str, str, str, np.ndarray], str],
    allocate_crop_path: Callable[[], Tuple[str, str]],
    on_line_done: Optional[Callable[[str, bool], None]] = None,
    on_error: Optional[Callable[[str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    write_debug: Optional[Callable[[dict], None]] = None,
    engines: List[str] = DEFAULT_ENGINES,
    min_agree: int = DEFAULT_MIN_AGREE,
    detector_engine: str = "paddle",
    pdf_ocr_fallback: bool = True,
    degrade: Optional[page_degrade.DegradeOptions] = None,
    write_degrade: Optional[Callable[[dict], None]] = None,
    options: Optional[RecognitionOptions] = None,
) -> None:
    """Обрабатывает один PDF-файл постранично: каждая страница — либо прямым
    извлечением текстового слоя (без OCR), либо обычным OCR-консенсусом
    растровой страницы.

    Решение "использовать текстовый слой" принимается для каждой страницы
    отдельно (pdf_extract.page_text_layer_usable): есть ли текст и достаточно
    ли он чистый. Страница без слоя или с плохим слоем идёт через OCR, а при
    pdf_ocr_fallback=False пропускается (режим «только текстовый слой» — без
    медленного OCR на CPU).
    write_line/on_line_done см. _process_boxes; при использовании текстового
    слоя строки считаются сразу good/не diverged (vote() не вызывается — текст
    берётся из PDF напрямую).
    degrade/write_degrade — порча страниц с текстовым слоем, см. _process_pdf_page.
    """
    pdf_doc = pdfium.PdfDocument(file_path)
    try:
        for page_index in range(len(pdf_doc)):
            if should_cancel and should_cancel():
                break
            page = pdf_doc[page_index]
            source_label = f"{file_path} (страница {page_index + 1})"
            try:
                use_text_layer = extract_pdf_text_layer and _page_uses_text_layer(
                    page, source_label, on_error
                )
                if not use_text_layer and not pdf_ocr_fallback:
                    logger.info(f"{source_label}: пропуск (OCR-fallback выключен)")
                    continue
                _process_pdf_page(
                    page,
                    source_label,
                    use_text_layer,
                    get_detector,
                    threshold,
                    preferred_model,
                    lang,
                    latin_model_size,
                    tesseract_lang,
                    write_line,
                    allocate_crop_path,
                    on_line_done,
                    on_error,
                    should_cancel,
                    write_debug,
                    engines,
                    min_agree,
                    detector_engine,
                    degrade=degrade,
                    degrade_rng=(
                        page_degrade.page_seed(degrade, file_path, page_index)
                        if degrade is not None and degrade.enabled
                        else None
                    ),
                    write_degrade=write_degrade,
                    options=options,
                )
            finally:
                # Явно закрываем per-page нативные буферы pdfium сразу, а не
                # копим их до pdf_doc.close() в конце файла (implicit-close
                # warnings на больших PDF).
                page.close()
    finally:
        pdf_doc.close()


def _degraded_page(
    image: np.ndarray,
    degrade: Optional[page_degrade.DegradeOptions],
    rng,
    source_label: str,
    on_error: Optional[Callable[[str], None]],
) -> Optional[np.ndarray]:
    """Испорченная копия страницы или None (порча выключена, страница не выпала или
    Augraphy упала — тогда страница остаётся чистой, сбой виден в /status)."""
    if degrade is None or not degrade.enabled or rng is None:
        return None
    try:
        return page_degrade.maybe_degrade_page(image, degrade, rng)
    except page_degrade.GeometryChangedError:
        raise  # эффект сдвинул геометрию — ошибка набора эффектов, а не одной страницы
    except Exception as e:  # noqa: BLE001 — внутренние сбои Augraphy/numba
        msg = f"Порча страницы не удалась {source_label}, страница остаётся чистой: {e}"
        logger.warning(msg)
        if on_error:
            on_error(msg)
        return None


def _page_uses_text_layer(
    page, source_label: str, on_error: Optional[Callable[[str], None]]
) -> bool:
    """pdf_extract.page_text_layer_usable с логом решения; ошибка чтения слоя
    — не повод терять страницу: она уходит в OCR."""
    try:
        usable = pdf_extract.page_text_layer_usable(page)
    except Exception as e:
        msg = f"Ошибка чтения текстового слоя {source_label}, страница пойдёт в OCR: {e}"
        logger.warning(msg)
        if on_error:
            on_error(msg)
        return False
    logger.info(f"{source_label}: {'текстовый слой' if usable else 'OCR'}")
    return usable


def _process_pdf_page(
    page,
    source_label: str,
    use_text_layer: bool,
    get_detector: Callable[[], Detector],
    threshold: float,
    preferred_model: Optional[str],
    lang: str,
    latin_model_size: str,
    tesseract_lang: str,
    write_line: Callable[[str, str, str, np.ndarray], str],
    allocate_crop_path: Callable[[], Tuple[str, str]],
    on_line_done: Optional[Callable[[str, bool], None]],
    on_error: Optional[Callable[[str], None]],
    should_cancel: Optional[Callable[[], bool]],
    write_debug: Optional[Callable[[dict], None]],
    engines: List[str],
    min_agree: int,
    detector_engine: str,
    degrade: Optional[page_degrade.DegradeOptions] = None,
    degrade_rng=None,
    write_degrade: Optional[Callable[[dict], None]] = None,
    options: Optional[RecognitionOptions] = None,
) -> None:
    """Обрабатывает одну страницу PDF (см. _process_pdf) — текстовый слой либо
    OCR-консенсус растровой страницы.

    degrade (backend/degrade.py) — только для текстового слоя, где метка не зависит от
    пикселей: доля page_share страниц портится (degrade_rng — генератор этой страницы),
    строка берётся с испорченной страницы, если осталась читаемой, иначе с чистой.
    write_degrade получает запись по каждой строке испорченной страницы (degrade.jsonl).
    OCR-страницы не портятся: там метку дают сами распознаватели."""
    try:
        numpy_image = pdf_extract.render_page(page)
    except Exception as e:
        msg = f"Ошибка рендеринга {source_label}: {e}"
        logger.warning(msg)
        if on_error:
            on_error(msg)
        return

    if use_text_layer:
        noisy_image = _degraded_page(numpy_image, degrade, degrade_rng, source_label, on_error)
        try:
            image_height, image_width = numpy_image.shape[:2]
            boxes_text = pdf_extract.extract_page_text_boxes(page, image_width, image_height)
        except Exception as e:
            msg = f"Ошибка извлечения текстового слоя {source_label}: {e}"
            logger.warning(msg)
            if on_error:
                on_error(msg)
            return

        for box, text in boxes_text:
            try:
                img_crop = crop_by_polygon(numpy_image, box)
                if not _is_big_enough(img_crop):
                    continue
                degraded = None
                if noisy_image is not None:
                    noisy_crop = crop_by_polygon(noisy_image, box)
                    degraded = page_degrade.choose_crop(img_crop, noisy_crop, degrade.min_contrast)
                    if degraded:
                        img_crop = noisy_crop
                crop_relative, crop_absolute = allocate_crop_path()
                _save_crop(img_crop, crop_absolute)
                bucket = write_line("good", crop_relative, text, img_crop)
                if noisy_image is not None and write_degrade:
                    # degraded: true — испорченный кроп, false — нечитаемый после порчи (взят
                    # чистый), null — эффекты строку не задели
                    write_degrade(
                        {"crop": crop_relative, "source": source_label, "degraded": degraded}
                    )
                if on_line_done:
                    on_line_done(bucket, False)
            except Exception as e:
                msg = f"Ошибка сохранения строки в {source_label}: {e}"
                logger.warning(msg)
                if on_error:
                    on_error(msg)
                continue
    else:
        boxes = _detect_with_timeout(get_detector(), numpy_image, source_label, on_error)
        _process_boxes(
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
            engines=engines,
            min_agree=min_agree,
            detector_engine=detector_engine,
            options=options,
        )


def run(
    input_dir: str,
    output_dir: str,
    threshold: float,
    preferred_model: Optional[str] = None,
    lang: str = "ru",
    latin_model_size: str = DEFAULT_LATIN_MODEL_SIZE,
    extract_pdf_text_layer: bool = True,
    detector_engine: str = DEFAULT_DETECTOR_ENGINE,
    engines: List[str] = DEFAULT_ENGINES,
    min_agree: int = DEFAULT_MIN_AGREE,
    on_found: Optional[Callable[[int], None]] = None,
    on_file_done: Optional[Callable[[], None]] = None,
    on_line_done: Optional[Callable[[str, bool], None]] = None,
    on_error: Optional[Callable[[str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    pdf_ocr_fallback: bool = True,
    append_crop_size: bool = False,
    normalize_labels: bool = False,
    alphabet: Optional[FrozenSet[str]] = None,
    degrade: Optional[page_degrade.DegradeOptions] = None,
    options: Optional[RecognitionOptions] = None,
) -> Tuple[int, int]:
    """Обрабатывает папку документов (изображения + PDF): детекция ->
    распознавание выбранными движками -> голосование; для PDF с текстовым
    слоем — прямое извлечение текста+координат без OCR (см. extract_pdf_text_layer).
    pdf_ocr_fallback=False — страницы PDF без годного слоя пропускаются, а не
    распознаются (изображения из input_dir по-прежнему идут через OCR).
    append_crop_size=True — в конец каждой строки датасета через табуляцию
    дописываются ширина и высота кропа в пикселях (см. _dataset_line).
    normalize_labels / alphabet — нормализация метки и отправка строк с
    символами вне словаря в needs_review (см. _finalize_line).
    degrade — порча страниц PDF с текстовым слоем (backend/degrade.py, см.
    _process_pdf_page); при включённой порче в output_dir пишется degrade.jsonl
    (по записи на строку испорченной страницы).
    options — модели движков custom/vlm_line и ключ сравнения vote_key
    (RecognitionOptions).

    engines/min_agree — схема выбора движков распознавания ("1 из 1"/
    "1 из 2"/"2 из 2"/"2 из 3", см. RunRequest в backend/main.py и
    frontend/src/ui/generation_view.py); по умолчанию — все 3 движка,
    совпадение любых 2 ("2 из 3", прежнее захардкоженное поведение).

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
    reset_engine_guard()

    tesseract_lang = "rus" if lang == "ru" else "eng"
    detector: Optional[Detector] = None

    def get_detector() -> Detector:
        nonlocal detector
        if detector is None:
            detector = Detector(engine=detector_engine, tesseract_lang=tesseract_lang)
        return detector

    matched_files, pdf_files = list_input_files(input_dir)

    if on_found:
        on_found(len(matched_files) + len(pdf_files))

    good_count = 0
    review_count = 0
    img_count = _resume_img_count(output_dir)

    with (
        open(os.path.join(output_dir, "good.txt"), "w", encoding="utf-8") as good_file,
        open(os.path.join(output_dir, "needs_review.txt"), "w", encoding="utf-8") as review_file,
        open(os.path.join(output_dir, "debug.jsonl"), "w", encoding="utf-8") as debug_file,
        contextlib.ExitStack() as optional_files,
    ):

        def write_line(bucket: str, crop_relative: str, text: str, crop: np.ndarray) -> str:
            """Пишет строку; возвращает итоговую корзину (alphabet может сменить её)."""
            nonlocal good_count, review_count
            bucket, text = _finalize_line(bucket, text, normalize_labels, alphabet)
            target = good_file if bucket == "good" else review_file
            target.write(_dataset_line(crop_relative, text, crop, append_crop_size))
            target.flush()
            if bucket == "good":
                good_count += 1
            else:
                review_count += 1
            return bucket

        def write_debug(record: dict) -> None:
            debug_file.write(json.dumps(record, ensure_ascii=False) + "\n")
            debug_file.flush()

        degrade_file = None
        if degrade is not None and degrade.enabled:
            degrade_file = optional_files.enter_context(
                open(os.path.join(output_dir, "degrade.jsonl"), "w", encoding="utf-8")
            )

        def write_degrade(record: dict) -> None:
            degrade_file.write(json.dumps(record, ensure_ascii=False) + "\n")
            degrade_file.flush()

        def allocate_crop_path() -> Tuple[str, str]:
            nonlocal img_count
            paths = _crop_paths(img_count, output_dir)
            img_count += 1
            return paths

        for file_path in matched_files:
            if should_cancel and should_cancel():
                break
            try:
                numpy_image = np.array(Image.open(file_path).convert("RGB"))
                boxes = _detect_with_timeout(get_detector(), numpy_image, file_path, on_error)
            except Exception as e:
                msg = f"Ошибка обработки файла {file_path}: {e}"
                logger.warning(msg)
                if on_error:
                    on_error(msg)
                if on_file_done:
                    on_file_done()
                continue

            _process_boxes(
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
                engines=engines,
                min_agree=min_agree,
                detector_engine=detector_engine,
                options=options,
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
                    engines=engines,
                    min_agree=min_agree,
                    detector_engine=detector_engine,
                    pdf_ocr_fallback=pdf_ocr_fallback,
                    degrade=degrade,
                    write_degrade=write_degrade if degrade_file is not None else None,
                    options=options,
                )
            except Exception as e:
                msg = f"Ошибка обработки файла {file_path}: {e}"
                logger.warning(msg)
                if on_error:
                    on_error(msg)
                if on_file_done:
                    on_file_done()
                continue
            if on_file_done:
                on_file_done()

    return good_count, review_count
