"""Режим «готовые кропы» (mode="crops"): чистка меток существующего датасета.

На входе не папка документов, а файл меток датасета (``путь_кропа\\tметка[\\tw\\th]``)
и корень кропов. Детекции и новых кропов нет: каждый кроп с диска идёт в
выбранные движки распознавания (backend/pipeline.py::_recognize_batch), vote()
решает «N из M» по ключу сравнения (backend/text_keys.py), исходная метка по
желанию — ещё один голос. Выход — good.txt / needs_review.txt / debug.jsonl с
ТЕМИ ЖЕ путями кропов, что во входном файле (относительно корня кропов, не
output_dir): good.txt — исправленные метки, needs_review.txt — строки без
согласия (в обучение не идут).
"""

import json
import logging
import os
from dataclasses import dataclass
from typing import Callable, Dict, FrozenSet, Iterator, List, Optional, TextIO, Tuple

import numpy as np
from PIL import Image

from backend.config import DEFAULT_ENGINES, DEFAULT_MIN_AGREE, RECOGNITION_BATCH_SIZE
from backend.consensus import is_diverged, vote
from backend.pipeline import (
    RecognitionOptions,
    _dataset_line,
    _finalize_line,
    _recognize_batch,
    reset_engine_guard,
)
from backend.recognizers import DEFAULT_LATIN_MODEL_SIZE
from backend.text_keys import vote_key

logger = logging.getLogger(__name__)

# Имя голоса исходной метки в results для vote() — зарезервировано, движка с
# таким именем нет (main.py пропускает только config.RECOGNITION_ENGINES).
LABEL_VOTE = "label"
# utf-8-sig: файл меток, сохранённый Блокнотом с BOM, иначе давал бы на первой
# строке путь с невидимым ﻿ и «кроп не найден».
_LABEL_FILE_ENCODING = "utf-8-sig"


@dataclass
class LabelLine:
    """Строка входного файла меток: путь кропа как в файле + исходная метка."""

    path: str
    label: str


@dataclass
class _LineSettings:
    """Всё, что нужно для решения и записи по одной строке (см. _write_line)."""

    threshold: float
    preferred_model: Optional[str]
    min_agree: int
    key: Optional[Callable[[str], str]]
    label_votes: bool
    normalize_labels: bool
    alphabet: Optional[FrozenSet[str]]
    append_crop_size: bool


@dataclass
class _Recognizer:
    """Батч кропов → по строке {движок: (text, score)} выбранными движками
    (backend/pipeline.py::_recognize_batch)."""

    engines: List[str]
    lang: str
    latin_model_size: str
    options: RecognitionOptions
    on_error: Optional[Callable[[str], None]]

    def __call__(
        self, crops: List[np.ndarray], source_label: str
    ) -> List[Dict[str, Tuple[str, float]]]:
        if not crops:
            return []
        tesseract_lang = "rus" if self.lang == "ru" else "eng"
        return _recognize_batch(
            crops,
            self.engines,
            self.lang,
            self.latin_model_size,
            tesseract_lang,
            source_label,
            self.on_error,
            self.options,
        )


def _report(on_error: Optional[Callable[[str], None]], msg: str) -> None:
    logger.warning(msg)
    if on_error:
        on_error(msg)


def _parse_label_line(
    raw: str, label_file: str, number: int, on_error: Optional[Callable[[str], None]]
) -> Optional[LabelLine]:
    """``путь\\tметка[\\tw\\th]`` → LabelLine; без таба/с пустым путём — None +
    on_error. Хвостовые поля (w, h) не нужны: размер берётся у картинки."""
    fields = raw.split("\t")
    if len(fields) < 2 or not fields[0].strip():
        _report(on_error, f"{label_file}:{number}: ожидалось «путь<TAB>метка» — пропуск")
        return None
    return LabelLine(path=fields[0], label=fields[1])


def count_batches(label_file: str) -> int:
    """Число батчей по непустым строкам файла — для on_found до прогона.
    Битые строки тоже считаются: они занимают место в батче (см. iter_batches),
    поэтому число батчей сходится с числом on_file_done()."""
    with open(label_file, encoding=_LABEL_FILE_ENCODING) as f:
        lines = sum(1 for raw in f if raw.strip())
    return -(-lines // RECOGNITION_BATCH_SIZE)


def iter_batches(
    label_file: str, on_error: Optional[Callable[[str], None]] = None
) -> Iterator[List[LabelLine]]:
    """Файл меток потоково, по RECOGNITION_BATCH_SIZE непустых строк за раз —
    файл на миллион строк не держится в памяти целиком. Пустые строки
    пропускаются молча, битые — через on_error (батч тогда короче)."""
    batch: List[LabelLine] = []
    seen = 0
    with open(label_file, encoding=_LABEL_FILE_ENCODING) as f:
        for number, raw in enumerate(f, start=1):
            raw = raw.rstrip("\r\n")
            if not raw.strip():
                continue
            seen += 1
            line = _parse_label_line(raw, label_file, number, on_error)
            if line is not None:
                batch.append(line)
            if seen == RECOGNITION_BATCH_SIZE:
                yield batch
                batch, seen = [], 0
    if seen:
        yield batch


def resolve_crop_path(data_dir: str, crop_path: str) -> Optional[str]:
    """Абсолютный путь кропа внутри data_dir или None, если путь из файла меток
    выходит за data_dir (``../``, чужой абсолютный путь) — граница та же, что у
    OCR_DATA_ROOT в main.py, иначе файл меток обходил бы её."""
    root = os.path.realpath(data_dir)
    resolved = os.path.realpath(os.path.join(root, crop_path))
    try:
        inside = os.path.commonpath([root, resolved]) == root
    except ValueError:  # разные диски на Windows
        inside = False
    return resolved if inside else None


def _load_batch(
    batch: List[LabelLine], data_dir: str, on_error: Optional[Callable[[str], None]]
) -> Tuple[List[LabelLine], List[np.ndarray]]:
    """Кропы батча с диска (RGB numpy). Нечитаемый/отсутствующий кроп — ошибка
    в on_error, строка не пишется ни в good, ни в needs_review."""
    loaded: List[LabelLine] = []
    crops: List[np.ndarray] = []
    for line in batch:
        absolute = resolve_crop_path(data_dir, line.path)
        if absolute is None:
            _report(on_error, f"Кроп вне input_dir, пропуск: {line.path}")
            continue
        try:
            with Image.open(absolute) as image:
                crops.append(np.array(image.convert("RGB")))
        except Exception as e:
            _report(on_error, f"Не удалось прочитать кроп {line.path}: {e}")
            continue
        loaded.append(line)
    return loaded, crops


def _tsv_safe(text: str) -> str:
    """Табы/переводы строк в тексте движка или метке сломали бы TSV датасета."""
    return text.replace("\t", " ").replace("\r", " ").replace("\n", " ")


def _vote_line(
    line: LabelLine, results: Dict[str, Tuple[str, float]], settings: _LineSettings
) -> Tuple[str, str, str, bool]:
    """(bucket, text, engine, diverged) одной строки. Голос метки участвует в
    решении, но не в diverged: в crops приходят как раз расхождения модели с
    меткой, и с ним почти каждая строка считалась бы diverged."""
    voters = dict(results)
    if settings.label_votes:
        voters[LABEL_VOTE] = (line.label, 1.0)
    bucket, text, engine, _ = vote(
        voters, settings.threshold, settings.preferred_model, settings.min_agree, settings.key
    )
    bucket, text = _finalize_line(
        bucket, _tsv_safe(text), settings.normalize_labels, settings.alphabet
    )
    return bucket, text, engine, is_diverged(results, settings.threshold, settings.key)


def _debug_record(
    line: LabelLine,
    results: Dict[str, Tuple[str, float]],
    bucket: str,
    engine: str,
    diverged: bool,
) -> str:
    record = {
        "crop": line.path,
        "bucket": bucket,
        "engine": engine,
        "diverged": diverged,
        "label": line.label,
        "engines": {name: {"text": t, "score": sc} for name, (t, sc) in results.items()},
    }
    return json.dumps(record, ensure_ascii=False) + "\n"


def run(
    label_file: str,
    data_dir: str,
    output_dir: str,
    threshold: float,
    preferred_model: Optional[str] = None,
    engines: List[str] = DEFAULT_ENGINES,
    min_agree: int = DEFAULT_MIN_AGREE,
    options: Optional[RecognitionOptions] = None,
    label_votes: bool = False,
    lang: str = "ru",
    latin_model_size: str = DEFAULT_LATIN_MODEL_SIZE,
    on_found: Optional[Callable[[int], None]] = None,
    on_file_done: Optional[Callable[[], None]] = None,
    on_line_done: Optional[Callable[[str, bool], None]] = None,
    on_error: Optional[Callable[[str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    append_crop_size: bool = False,
    normalize_labels: bool = False,
    alphabet: Optional[FrozenSet[str]] = None,
) -> Tuple[int, int]:
    """Прогоняет кропы из label_file (пути — относительно data_dir) через движки
    и голосование; возвращает (кол-во good, кол-во needs_review).

    label_votes=True — исходная метка добавляется в голосование как ещё один
    голос (LABEL_VOTE, score 1.0): текстовый слой не всегда неправ, и если он
    совпал с одним из движков, метка, скорее всего, верна. options — модели
    custom/vlm_line и ключ сравнения vote_key (backend/pipeline.py::RecognitionOptions).

    Прогресс для трекера backend/jobs.py: «документ» здесь — батч из
    RECOGNITION_BATCH_SIZE строк: on_found(число батчей) один раз,
    on_file_done() после каждого батча, on_line_done(bucket, diverged) — после
    каждой строки, on_error(msg) — битая строка файла меток, нечитаемый кроп,
    ошибка/таймаут движка. should_cancel() проверяется перед каждым батчем и
    строкой. Выходные файлы перезаписываются на каждый запуск и сбрасываются
    на диск построчно, как в pipeline.run(); resume нет.

    debug.jsonl — запись на строку: путь кропа, корзина, движок-победитель,
    diverged, исходная метка ("label") и тексты/score всех движков.
    """
    os.makedirs(output_dir, exist_ok=True)
    reset_engine_guard()
    options = options or RecognitionOptions()
    settings = _LineSettings(
        threshold=threshold,
        preferred_model=preferred_model,
        min_agree=min_agree,
        key=vote_key(options.vote_key),
        label_votes=label_votes,
        normalize_labels=normalize_labels,
        alphabet=alphabet,
        append_crop_size=append_crop_size,
    )
    recognize = _Recognizer(engines, lang, latin_model_size, options, on_error)
    total = count_batches(label_file)
    if on_found:
        on_found(total)

    counts = {"good": 0, "needs_review": 0}
    with (
        open(os.path.join(output_dir, "good.txt"), "w", encoding="utf-8") as good_file,
        open(os.path.join(output_dir, "needs_review.txt"), "w", encoding="utf-8") as review_file,
        open(os.path.join(output_dir, "debug.jsonl"), "w", encoding="utf-8") as debug_file,
    ):
        outputs = {"good": good_file, "needs_review": review_file, "debug": debug_file}
        for index, batch in enumerate(iter_batches(label_file, on_error)):
            if should_cancel and should_cancel():
                break
            loaded, crops = _load_batch(batch, data_dir, on_error)
            rows = recognize(crops, f"{label_file} (батч {index + 1}/{total})")
            for line, crop, results in zip(loaded, crops, rows, strict=True):
                if should_cancel and should_cancel():
                    break
                written = _write_line(outputs, line, results, crop, settings, on_error)
                if written:
                    counts[written[0]] += 1
                    if on_line_done:
                        on_line_done(*written)
            if on_file_done:
                on_file_done()

    return counts["good"], counts["needs_review"]


def _write_line(
    outputs: Dict[str, TextIO],
    line: LabelLine,
    results: Dict[str, Tuple[str, float]],
    crop: np.ndarray,
    settings: _LineSettings,
    on_error: Optional[Callable[[str], None]],
) -> Optional[Tuple[str, bool]]:
    """Голосование + запись строки датасета и debug-записи; возвращает
    (корзина, diverged) или None, если строка упала (ошибка — в on_error,
    job продолжается)."""
    try:
        bucket, text, engine, diverged = _vote_line(line, results, settings)
        target = outputs["good" if bucket == "good" else "needs_review"]
        target.write(_dataset_line(line.path, text, crop, settings.append_crop_size))
        target.flush()
        outputs["debug"].write(_debug_record(line, results, bucket, engine, diverged))
        outputs["debug"].flush()
        return ("good" if bucket == "good" else "needs_review"), diverged
    except Exception as e:
        _report(on_error, f"Ошибка голосования/записи строки {line.path}: {e}")
        return None
