import os
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from backend.config import DEFAULT_SCORE_THRESHOLD
from backend.jobs import get_job, start_job
from backend.recognizers import DEFAULT_LATIN_MODEL_SIZE, LATIN_MODEL_SIZES

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


@app.post("/run")
def run(req: RunRequest):
    if not os.path.isdir(req.input_dir):
        raise HTTPException(400, f"input_dir не найдена: {req.input_dir}")
    if req.lang not in ("ru", "latin"):
        raise HTTPException(400, f"lang должен быть 'ru' или 'latin': {req.lang}")
    if req.latin_model_size not in LATIN_MODEL_SIZES:
        raise HTTPException(
            400,
            f"latin_model_size должен быть одним из {LATIN_MODEL_SIZES}: "
            f"{req.latin_model_size}",
        )

    job_id = start_job(
        req.input_dir,
        req.output_dir,
        req.score_threshold,
        req.preferred_model,
        req.lang,
        req.latin_model_size,
    )
    return {"job_id": job_id}


@app.get("/status/{job_id}")
def status(job_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return {"status": job.status, "error": job.error}


@app.get("/result/{job_id}")
def result(job_id: str):
    job = get_job(job_id)
    if job is None or job.status != "done":
        raise HTTPException(404, "Result not ready")
    return job.result
