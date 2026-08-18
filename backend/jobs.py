"""Хранилище задач в памяти процесса.

Никакой персистентности: при перезапуске backend'а состояние всех задач
теряется. Это осознанное упрощение для одноразового спайка с одним
одновременным заданием на одной машине, а не недоработка.
"""

import threading
import uuid
from dataclasses import dataclass
from typing import Dict, Literal, Optional

from backend import pipeline

JobStatus = Literal["running", "done", "error"]


@dataclass
class JobState:
    status: JobStatus
    result: Optional[dict] = None
    error: Optional[str] = None


_jobs: Dict[str, JobState] = {}


def _run_job(
    job_id: str,
    input_dir: str,
    output_dir: str,
    threshold: float,
    preferred_model: Optional[str],
):
    try:
        good_count, needs_review_count = pipeline.run(
            input_dir, output_dir, threshold, preferred_model
        )
        _jobs[job_id] = JobState(
            status="done",
            result={
                "output_dir": output_dir,
                "good_count": good_count,
                "needs_review_count": needs_review_count,
            },
        )
    except Exception as e:
        _jobs[job_id] = JobState(status="error", error=str(e))


def start_job(
    input_dir: str,
    output_dir: str,
    threshold: float,
    preferred_model: Optional[str] = None,
) -> str:
    """Запускает pipeline.run в фоновом потоке и сразу возвращает job_id"""
    job_id = str(uuid.uuid4())
    _jobs[job_id] = JobState(status="running")
    thread = threading.Thread(
        target=_run_job,
        args=(job_id, input_dir, output_dir, threshold, preferred_model),
        daemon=True,
    )
    thread.start()
    return job_id


def get_job(job_id: str) -> Optional[JobState]:
    return _jobs.get(job_id)
