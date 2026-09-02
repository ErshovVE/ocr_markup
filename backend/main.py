import os
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from backend import jobs, models_status
from backend.config import (
    DEFAULT_ENGINES,
    DEFAULT_IOU_THRESHOLD,
    DEFAULT_MIN_AGREE,
    DEFAULT_SCORE_THRESHOLD,
    DEFAULT_VLM_MIN_AGREE,
    RECOGNITION_ENGINES,
    VLM_ENGINES,
)
from backend.detector import DEFAULT_DETECTOR_ENGINE, DETECTOR_ENGINES
from backend.jobs import cancel_job, get_active_job_id, get_job, get_status_snapshot, start_job
from backend.recognizers import DEFAULT_LATIN_MODEL_SIZE, LATIN_MODEL_SIZES

# Ключ детектора в models_status.get_status() для каждого detector_engine.
# "tesseract" не включён отдельно — он уже проверяется как движок
# распознавания (общий бинарник на детекцию и распознавание, см.
# backend/README.md), дублировать предупреждение незачем.
_DETECTOR_STATUS_KEYS = {"paddle": "paddle_detector", "surya": "surya_detector"}


def _readiness_warnings(req: "RunRequest") -> List[str]:
    """Предупреждения о неготовых моделях перед стартом job'а — раньше /run
    просто стартовал вслепую, и первая же строка могла "молча" зависнуть на
    скачивании гигабайтных весов без единого объяснения в UI."""
    status = models_status.get_status()
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
    det_key = _DETECTOR_STATUS_KEYS.get(req.detector_engine)
    if det_key:
        check(det_key, "Детектор строк")
    return warnings

# Локальный однопользовательский сервис без аутентификации (см. backend/README.md) —
# входные пути не ограничены заранее известным корнем намеренно, так как
# мейнтейнер сам указывает произвольную рабочую папку с документами.
app = FastAPI(title="OCR Consensus Backend")


class RunRequest(BaseModel):
    input_dir: str
    output_dir: str
    score_threshold: float = DEFAULT_SCORE_THRESHOLD
    preferred_model: Optional[str] = None
    # "ru" (по умолчанию) — распознавание кириллицы (cyrillic_PP-OCRv5_mobile_rec).
    # "latin" — вместо него используется PaddleOCR PP-OCRv6 для латиницы/не-русского
    # текста; tesseract при этом тоже переключается на lang="eng".
    lang: str = "ru"
    latin_model_size: str = DEFAULT_LATIN_MODEL_SIZE
    # Если во входной папке есть PDF с извлекаемым текстовым слоем —
    # вытащить текст+координаты напрямую (без OCR) и сразу пометить как good.
    # См. backend/README.md, раздел "PDF".
    extract_pdf_text_layer: bool = True
    # Движок детекции строк текста — независим от preferred_model
    # (который влияет только на голосование распознавания).
    detector_engine: str = DEFAULT_DETECTOR_ENGINE
    # Какие движки распознавания вообще прогонять на строку — раньше всегда
    # были прошиты все 3. engines/min_agree вместе задают схему "N из M" из
    # фронтенда (1 из 1 / 1 из 2 / 2 из 2 / 2 из 3, см.
    # frontend/src/ui/generation_view.py): min_agree — сколько из engines
    # должны сойтись в одном тексте, чтобы принять его без разбора (см.
    # backend/consensus.py::vote).
    engines: List[str] = list(DEFAULT_ENGINES)
    min_agree: int = DEFAULT_MIN_AGREE
    # mode="consensus" (по умолчанию) — классический построчный консенсус;
    # mode="vlm" — полностраничный VLM-парсинг (см. backend/pipeline_vlm.py).
    # При mode="vlm" классические поля (engines/min_agree/detector_engine/lang)
    # игнорируются, работают vlm_engines/vlm_min_agree/iou_threshold.
    mode: str = "consensus"
    vlm_engines: List[str] = []
    vlm_min_agree: int = DEFAULT_VLM_MIN_AGREE
    iou_threshold: float = DEFAULT_IOU_THRESHOLD


class PrepareRequest(BaseModel):
    model: str


@app.post("/run")
def run(req: RunRequest):
    if not os.path.isdir(req.input_dir):
        raise HTTPException(400, f"input_dir не найдена: {req.input_dir}")
    if req.mode not in ("consensus", "vlm"):
        raise HTTPException(400, f"mode должен быть 'consensus' или 'vlm': {req.mode}")

    if req.mode == "vlm":
        if not req.vlm_engines or any(e not in VLM_ENGINES for e in req.vlm_engines):
            raise HTTPException(
                400,
                f"vlm_engines должен быть непустым подмножеством {VLM_ENGINES}: "
                f"{req.vlm_engines}",
            )
        if not (1 <= req.vlm_min_agree <= len(req.vlm_engines)):
            raise HTTPException(
                400,
                f"vlm_min_agree должен быть от 1 до len(vlm_engines)="
                f"{len(req.vlm_engines)}: {req.vlm_min_agree}",
            )
        if not (0.0 < req.iou_threshold <= 1.0):
            raise HTTPException(400, f"iou_threshold должен быть в (0, 1]: {req.iou_threshold}")
    else:
        if req.lang not in ("ru", "latin"):
            raise HTTPException(400, f"lang должен быть 'ru' или 'latin': {req.lang}")
        if req.latin_model_size not in LATIN_MODEL_SIZES:
            raise HTTPException(
                400,
                f"latin_model_size должен быть одним из {LATIN_MODEL_SIZES}: "
                f"{req.latin_model_size}",
            )
        if req.detector_engine not in DETECTOR_ENGINES:
            raise HTTPException(
                400,
                f"detector_engine должен быть одним из {DETECTOR_ENGINES}: {req.detector_engine}",
            )
        if not req.engines or any(e not in RECOGNITION_ENGINES for e in req.engines):
            raise HTTPException(
                400,
                f"engines должен быть непустым подмножеством {RECOGNITION_ENGINES}: {req.engines}",
            )
        if not (1 <= req.min_agree <= len(req.engines)):
            raise HTTPException(
                400,
                f"min_agree должен быть от 1 до len(engines)={len(req.engines)}: {req.min_agree}",
            )

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
        )
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    return {"job_id": job_id, "warnings": _readiness_warnings(req)}


@app.get("/jobs/active")
def active_job():
    """Возвращает job_id текущего выполняющегося задания (или null), чтобы
    фронтенд мог восстановить трекер прогресса после перезагрузки страницы —
    Streamlit создаёт новую сессию на F5 и теряет session_state."""
    return {"job_id": get_active_job_id()}


@app.get("/status/{job_id}")
def status(job_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return jobs.status_dict(job)


@app.post("/jobs/{job_id}/cancel")
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


@app.get("/jobs/status_snapshot")
def job_status_snapshot(output_dir: str):
    """Статус последнего задания для output_dir, переживший рестарт
    backend'а (в отличие от /status/{job_id} — job_id теряется вместе с
    памятью процесса, см. докстринг backend/jobs.py)."""
    snapshot = get_status_snapshot(output_dir)
    if snapshot is None:
        raise HTTPException(404, "Снэпшот не найден для этой output_dir")
    return snapshot


@app.get("/result/{job_id}")
def result(job_id: str):
    job = get_job(job_id)
    if job is None or job.status != "done":
        raise HTTPException(404, "Result not ready")
    return job.result


@app.get("/models/status")
def models_status_endpoint():
    return {
        name: {"status": state.status, "detail": state.detail}
        for name, state in models_status.get_status().items()
    }


@app.post("/models/prepare")
def models_prepare(req: PrepareRequest):
    try:
        models_status.prepare(req.model)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"status": "started"}
