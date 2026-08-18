import os
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from backend.config import DEFAULT_SCORE_THRESHOLD
from backend.jobs import get_job, start_job

# Локальный однопользовательский сервис без аутентификации (см. backend/README.md) —
# входные пути не ограничены заранее известным корнем намеренно, так как
# мейнтейнер сам указывает произвольную рабочую папку с документами.
app = FastAPI(title="OCR Consensus Backend")


class RunRequest(BaseModel):
    input_dir: str
    output_dir: str
    score_threshold: float = DEFAULT_SCORE_THRESHOLD
    preferred_model: Optional[str] = None


@app.post("/run")
def run(req: RunRequest):
    if not os.path.isdir(req.input_dir):
        raise HTTPException(400, f"input_dir не найдена: {req.input_dir}")

    job_id = start_job(
        req.input_dir, req.output_dir, req.score_threshold, req.preferred_model
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
