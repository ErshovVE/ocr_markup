import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Literal, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, model_validator

from backend import jobs, models_status, vlm_client
from backend.config import (
    DEFAULT_ENGINES,
    DEFAULT_IOU_THRESHOLD,
    DEFAULT_MIN_AGREE,
    DEFAULT_SCORE_THRESHOLD,
    DEFAULT_VLM_MIN_AGREE,
    LINE_VLM_ENGINES,
    RECOGNITION_ENGINES,
    VLM_ENGINES,
)
from backend.degrade import DEFAULT_MIN_CONTRAST, DegradeOptions, effects_errors
from backend.detector import DEFAULT_DETECTOR_ENGINE, DETECTOR_ENGINES
from backend.jobs import cancel_job, get_active_job_id, get_job, get_status_snapshot, start_job
from backend.labels import load_alphabet
from backend.pipeline import RecognitionOptions
from backend.recognizers import DEFAULT_LATIN_MODEL_SIZE, LATIN_MODEL_SIZES
from backend.text_keys import DEFAULT_VOTE_KEY, VOTE_KEYS

# Литералы в RunRequest дублируют эти кортежи ради OpenAPI-схемы — ловим дрейф.
assert set(LATIN_MODEL_SIZES) == {"tiny", "small", "medium"}
assert set(DETECTOR_ENGINES) == {"paddle", "surya", "tesseract"}
assert set(VOTE_KEYS) == {"exact", "normalized", "no_spaces"}

# Файл, по которому экспорт своей модели PaddleOCR (tools/export_model.py)
# узнаётся в custom_model_dir: из него PaddleX берёт архитектуру и словарь.
_CUSTOM_MODEL_MANIFEST = "inference.yml"

# Ключ детектора в models_status.get_status() для каждого detector_engine.
# "tesseract" не включён отдельно — он уже проверяется как движок
# распознавания (общий бинарник на детекцию и распознавание, см.
# backend/README.md), дублировать предупреждение незачем.
_DETECTOR_STATUS_KEYS = {"paddle": "paddle_detector", "surya": "surya_detector"}

# Опциональный allow-list каталогов. Если OCR_DATA_ROOT задан, input_dir/
# output_dir обязаны резолвиться внутри него (в Docker это /data). Не задан —
# поведение спайка без ограничений (ADR-0002). Это code-level страховка на
# случай, если порт всё же окажется доступен извне.
_DATA_ROOT = os.environ.get("OCR_DATA_ROOT")


def _reject_outside_data_root(path: str, label: str) -> None:
    if not _DATA_ROOT:
        return
    root = os.path.realpath(_DATA_ROOT)
    resolved = os.path.realpath(path)
    try:
        inside = os.path.commonpath([root, resolved]) == root
    except ValueError:
        # разные диски на Windows / несопоставимые пути
        inside = False
    if not inside:
        raise HTTPException(400, f"{label} вне разрешённого каталога OCR_DATA_ROOT")


def _readiness_warnings(req: "RunRequest") -> List[str]:
    """Предупреждения о неготовых моделях перед стартом job'а — раньше /run
    просто стартовал вслепую, и первая же строка могла "молча" зависнуть на
    скачивании гигабайтных весов без единого объяснения в UI.

    Считается ДО start_job (см. run()): медленная проверка задерживает старт
    job'а, а не отрывается от HTTP-ответа. VLM-пинги в get_status конкурентны
    и кэшируются (backend/models_status.py), поэтому это дёшево."""
    uses_line_vlm = req.mode != "vlm" and "vlm_line" in req.engines
    status = models_status.get_status(include_vlm=req.mode == "vlm" or uses_line_vlm)
    warnings: List[str] = []

    def check(key: str, label: str) -> None:
        state = status.get(key)
        if state is None:
            return
        if state.status == "error":
            warnings.append(f"{label}: ошибка — {state.detail or 'см. /models/status'}")
        elif state.status in ("not_checked", "checking"):
            warnings.append(
                f"{label}: не готов ({state.status}) — первый запуск может начаться "
                "с загрузки модели"
            )

    if req.mode == "vlm":
        for engine_id in req.vlm_engines:
            check(f"vlm_{engine_id}", f"VLM {engine_id}")
        return warnings

    if "paddle" in req.engines and req.lang == "ru":
        check("paddle", "PaddleOCR (распознавание)")
    if "surya" in req.engines:
        check("surya", "SuryaOCR (распознавание)")
    if "tesseract" in req.engines:
        check("tesseract", "Tesseract")
    if uses_line_vlm:
        check(f"vlm_{req.line_vlm_engine}", f"VLM {req.line_vlm_engine} (построчно)")
    det_key = _DETECTOR_STATUS_KEYS.get(req.detector_engine)
    if det_key and req.mode != "crops":  # в crops детекции нет
        check(det_key, "Детектор строк")
    return warnings


@asynccontextmanager
async def _lifespan(_app: "FastAPI"):
    yield
    vlm_client.close()  # закрыть module-level httpx.Client VLM-режима


# Локальный однопользовательский сервис без аутентификации (см. ADR-0002 и
# backend/README.md). Опциональный OCR_DATA_ROOT (выше) — единственная
# code-level граница; по умолчанию входные пути не ограничены намеренно.
app = FastAPI(title="OCR Consensus Backend", lifespan=_lifespan)


class RunRequest(BaseModel):
    input_dir: str
    output_dir: str
    score_threshold: float = Field(DEFAULT_SCORE_THRESHOLD, ge=0.0, le=1.0)
    preferred_model: Optional[str] = None
    # "ru" (по умолчанию) — распознавание кириллицы (cyrillic_PP-OCRv5_mobile_rec).
    # "latin" — вместо него используется PaddleOCR PP-OCRv6 для латиницы/не-русского
    # текста; tesseract при этом тоже переключается на lang="eng".
    lang: Literal["ru", "latin"] = "ru"
    latin_model_size: Literal["tiny", "small", "medium"] = DEFAULT_LATIN_MODEL_SIZE
    # Если во входной папке есть PDF с извлекаемым текстовым слоем —
    # вытащить текст+координаты напрямую (без OCR) и сразу пометить как good.
    extract_pdf_text_layer: bool = True
    # False — страницы PDF без годного текстового слоя пропускаются вместо
    # OCR-консенсуса (режим «только текстовый слой»: без медленного OCR на CPU).
    pdf_ocr_fallback: bool = True
    # True — в конец каждой строки good.txt/needs_review.txt через табуляцию
    # дописываются ширина и высота кропа в пикселях (оба режима).
    append_crop_size: bool = False
    # True — в метке типографские варианты символов заменяются на символы
    # словаря (– -> —, „ ” “ -> ", ‘ ’ -> '), картинка не меняется (backend/labels.py).
    normalize_labels: bool = False
    # Словарь модели (по символу на строку): строки good с символами вне него
    # уходят в needs_review. None — без проверки.
    alphabet_file: Optional[str] = None
    # Движок детекции строк текста — независим от preferred_model.
    detector_engine: Literal["paddle", "surya", "tesseract"] = DEFAULT_DETECTOR_ENGINE
    # Какие движки распознавания прогонять на строку; min_agree — сколько из
    # них должны сойтись в тексте, чтобы принять без разбора (см.
    # backend/consensus.py::vote, frontend схема "N из M").
    engines: List[str] = Field(default_factory=lambda: list(DEFAULT_ENGINES))
    min_agree: int = Field(DEFAULT_MIN_AGREE, ge=1)
    # mode="consensus" (по умолчанию) — построчный консенсус; mode="vlm" —
    # полностраничный VLM-парсинг (backend/pipeline_vlm.py). При mode="vlm"
    # engines/min_agree/detector_engine/lang игнорируются. mode="crops" —
    # чистка меток готовых кропов (backend/pipeline_crops.py): input_dir —
    # корень кропов, label_file — файл меток «путь<TAB>метка[<TAB>w<TAB>h]».
    mode: Literal["consensus", "vlm", "crops"] = "consensus"
    vlm_engines: List[str] = Field(default_factory=list)
    vlm_min_agree: int = Field(DEFAULT_VLM_MIN_AGREE, ge=1)
    iou_threshold: float = Field(DEFAULT_IOU_THRESHOLD, gt=0.0, le=1.0)
    # Порча страниц PDF с текстовым слоем (backend/degrade.py): доля испорченных страниц
    # (0 — выключено), сид, порог читаемости строки, набор эффектов {ink, paper, post}
    # (None — набор по умолчанию). Только mode="consensus" и extract_pdf_text_layer=true:
    # на OCR-страницах метку дают распознаватели, порча перед ними только испортит разметку.
    degrade_page_share: float = Field(0.0, ge=0.0, le=1.0)
    degrade_seed: int = 0
    degrade_min_contrast: float = Field(DEFAULT_MIN_CONTRAST, ge=0.0)
    degrade_effects: Optional[Dict[str, List[Dict[str, Any]]]] = None
    # mode="crops": файл меток датасета (пути кропов — относительно input_dir).
    label_file: Optional[str] = None
    # mode="crops": исходная метка — ещё один голос в vote() (min_agree до len(engines)+1).
    label_votes: bool = False
    # Движок "custom": каталог экспорта своей модели PaddleOCR (с inference.yml).
    custom_model_dir: Optional[str] = None
    # Движок "vlm_line": какой VLM читает строку-кроп (config.LINE_VLM_ENGINES).
    line_vlm_engine: Optional[str] = None
    # Ключ сравнения текстов движков в vote() (backend/text_keys.py):
    # exact — посимвольно, normalized — без типографики/лишних пробелов/ё,
    # no_spaces — ещё и без пробелов. consensus и crops.
    vote_key: Literal["exact", "normalized", "no_spaces"] = DEFAULT_VOTE_KEY

    def recognition_options(self) -> RecognitionOptions:
        return RecognitionOptions(
            custom_model_dir=self.custom_model_dir,
            line_vlm_engine=self.line_vlm_engine,
            vote_key=self.vote_key,
        )

    def degrade_options(self) -> Optional[DegradeOptions]:
        if self.degrade_page_share <= 0:
            return None
        options = DegradeOptions(
            page_share=self.degrade_page_share,
            seed=self.degrade_seed,
            min_contrast=self.degrade_min_contrast,
        )
        if self.degrade_effects is not None:
            options.effects = self.degrade_effects
        return options

    @model_validator(mode="after")
    def _check_cross_fields(self) -> "RunRequest":
        if not self.pdf_ocr_fallback and not self.extract_pdf_text_layer:
            raise ValueError(
                "pdf_ocr_fallback=false без extract_pdf_text_layer пропустил бы все страницы PDF"
            )
        if self.degrade_page_share > 0:
            if self.mode != "consensus" or not self.extract_pdf_text_layer:
                raise ValueError(
                    "degrade_page_share > 0 работает только с текстовым слоем PDF "
                    "(mode=consensus, extract_pdf_text_layer=true)"
                )
            errors = effects_errors(self.degrade_options().effects)
            if errors:
                raise ValueError("degrade_effects: " + "; ".join(errors))
        if self.mode == "vlm":
            bad = [e for e in self.vlm_engines if e not in VLM_ENGINES]
            if not self.vlm_engines or bad:
                raise ValueError(
                    f"vlm_engines должен быть непустым подмножеством {VLM_ENGINES}: "
                    f"{self.vlm_engines}"
                )
            if not (1 <= self.vlm_min_agree <= len(self.vlm_engines)):
                raise ValueError(
                    f"vlm_min_agree должен быть от 1 до len(vlm_engines)="
                    f"{len(self.vlm_engines)}: {self.vlm_min_agree}"
                )
        else:
            bad = [e for e in self.engines if e not in RECOGNITION_ENGINES]
            if not self.engines or bad:
                raise ValueError(
                    f"engines должен быть непустым подмножеством {RECOGNITION_ENGINES}: "
                    f"{self.engines}"
                )
            voters = len(self.engines) + (1 if self.label_votes else 0)
            if not (1 <= self.min_agree <= voters):
                raise ValueError(
                    f"min_agree должен быть от 1 до числа голосов {voters} "
                    f"(engines{' + метка' if self.label_votes else ''}): {self.min_agree}"
                )
            if self.preferred_model is not None and self.preferred_model not in self.engines:
                raise ValueError(
                    f"preferred_model должен быть одним из engines {self.engines}: "
                    f"{self.preferred_model}"
                )
            self._check_extra_engines()
        if self.mode == "crops" and not self.label_file:
            raise ValueError("mode=crops требует label_file")
        if self.label_votes and self.mode != "crops":
            raise ValueError("label_votes работает только с mode=crops")
        return self

    def _check_extra_engines(self) -> None:
        if "custom" in self.engines and not self.custom_model_dir:
            raise ValueError("движок custom требует custom_model_dir")
        if "vlm_line" in self.engines and self.line_vlm_engine not in LINE_VLM_ENGINES:
            raise ValueError(
                f"движок vlm_line требует line_vlm_engine из {LINE_VLM_ENGINES}: "
                f"{self.line_vlm_engine}"
            )


class PrepareRequest(BaseModel):
    model: str


class RunResponse(BaseModel):
    job_id: str
    warnings: List[str]


class JobStatusResponse(BaseModel):
    status: str
    error: Optional[str] = None
    docs_found: int = 0
    docs_processed: int = 0
    good_count: int = 0
    review_count: int = 0
    diverged_count: int = 0
    error_count: int = 0
    errors: List[str] = Field(default_factory=list)


class CancelResponse(BaseModel):
    status: str


class ActiveJobResponse(BaseModel):
    job_id: Optional[str]


class ModelStatusEntry(BaseModel):
    status: str
    detail: Optional[str] = None


def _check_crops_paths(req: RunRequest) -> None:
    """Пути режима crops и движка custom: внутри OCR_DATA_ROOT и существуют."""
    if req.mode == "crops":
        _reject_outside_data_root(req.label_file, "label_file")
        if not os.path.isfile(req.label_file):
            raise HTTPException(400, f"label_file не найден: {req.label_file}")
    if req.mode != "vlm" and "custom" in req.engines:
        _reject_outside_data_root(req.custom_model_dir, "custom_model_dir")
        manifest = os.path.join(req.custom_model_dir, _CUSTOM_MODEL_MANIFEST)
        if not os.path.isfile(manifest):
            raise HTTPException(
                400,
                f"custom_model_dir без {_CUSTOM_MODEL_MANIFEST} (нужен экспорт "
                f"tools/export_model.py): {req.custom_model_dir}",
            )


@app.post("/run", response_model=RunResponse, responses={400: {}, 409: {}})
def run(req: RunRequest):
    _reject_outside_data_root(req.input_dir, "input_dir")
    _reject_outside_data_root(req.output_dir, "output_dir")
    if not os.path.isdir(req.input_dir):
        raise HTTPException(400, f"input_dir не найдена: {req.input_dir}")
    alphabet = None
    if req.alphabet_file:
        _reject_outside_data_root(req.alphabet_file, "alphabet_file")
        if not os.path.isfile(req.alphabet_file):
            raise HTTPException(400, f"alphabet_file не найден: {req.alphabet_file}")
        try:
            alphabet = load_alphabet(req.alphabet_file)
        except (OSError, UnicodeDecodeError, ValueError) as e:
            raise HTTPException(400, f"alphabet_file не читается: {e}") from e
    _check_crops_paths(req)
    try:
        os.makedirs(req.output_dir, exist_ok=True)
    except OSError as e:
        raise HTTPException(400, f"output_dir недоступна для записи: {e}") from e

    # Предупреждения о неготовых моделях — ДО старта job'а, чтобы клиент,
    # получивший ответ, не видел ложную ошибку для уже запущенного задания.
    warnings = _readiness_warnings(req)

    try:
        job_id = start_job(
            req.input_dir,
            req.output_dir,
            req.score_threshold,
            req.preferred_model,
            req.lang,
            req.latin_model_size,
            req.extract_pdf_text_layer,
            req.detector_engine,
            req.engines,
            req.min_agree,
            req.mode,
            req.vlm_engines,
            req.vlm_min_agree,
            req.iou_threshold,
            pdf_ocr_fallback=req.pdf_ocr_fallback,
            append_crop_size=req.append_crop_size,
            normalize_labels=req.normalize_labels,
            alphabet=alphabet,
            degrade=req.degrade_options(),
            label_file=req.label_file,
            label_votes=req.label_votes,
            options=req.recognition_options(),
        )
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    return {"job_id": job_id, "warnings": warnings}


@app.get("/jobs/active", response_model=ActiveJobResponse)
def active_job():
    """Возвращает job_id текущего выполняющегося задания (или null), чтобы
    фронтенд мог восстановить трекер прогресса после перезагрузки страницы —
    Streamlit создаёт новую сессию на F5 и теряет session_state."""
    return {"job_id": get_active_job_id()}


@app.get("/status/{job_id}", response_model=JobStatusResponse, responses={404: {}})
def status(job_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return jobs.status_dict(job)


@app.post("/jobs/{job_id}/cancel", response_model=CancelResponse, responses={404: {}, 409: {}})
def cancel_job_endpoint(job_id: str):
    """Просит задание остановиться на ближайшей проверке — см. cancel_job()
    в backend/jobs.py. Не мгновенно: status станет "cancelled" в /status,
    когда pipeline.run() дойдёт до следующей проверки should_cancel()."""
    try:
        cancel_job(job_id)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    return {"status": "cancelling"}


@app.get("/jobs/status_snapshot", response_model=JobStatusResponse, responses={400: {}, 404: {}})
def job_status_snapshot(output_dir: str):
    """Статус последнего задания для output_dir, переживший рестарт
    backend'а (в отличие от /status/{job_id} — job_id теряется вместе с
    памятью процесса, см. докстринг backend/jobs.py)."""
    _reject_outside_data_root(output_dir, "output_dir")
    snapshot = get_status_snapshot(output_dir)
    if snapshot is None:
        raise HTTPException(404, "Снэпшот не найден для этой output_dir")
    return snapshot


@app.get("/result/{job_id}", responses={404: {}, 409: {}})
def result(job_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    if job.status != "done":
        raise HTTPException(409, f"Результат не готов (status={job.status})")
    return job.result


@app.get("/models/status")
def models_status_endpoint():
    return {
        name: {"status": state.status, "detail": state.detail}
        for name, state in models_status.get_status().items()
    }


@app.post("/models/prepare", responses={400: {}})
def models_prepare(req: PrepareRequest):
    try:
        models_status.prepare(req.model)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"status": "started"}
