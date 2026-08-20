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
from backend.detector import DEFAULT_DETECTOR_ENGINE
from backend.recognizers import DEFAULT_LATIN_MODEL_SIZE

JobStatus = Literal["running", "done", "error"]


@dataclass
class JobState:
    status: JobStatus
    result: Optional[dict] = None
    error: Optional[str] = None
    # Живой трекер прогресса — обновляется на месте по ходу pipeline.run()
    # через on_found/on_file_done/on_line_done, а не пересобирается по
    # завершении, чтобы GET /status видел актуальные значения, пока status
    # ещё "running". on_line_done — самый частый сигнал (распознавание одной
    # строки Surya может занимать до ~20с), поэтому good_count/review_count/
    # diverged_count считаются построчно, а не по завершении файла целиком.
    docs_found: int = 0
    docs_processed: int = 0
    good_count: int = 0
    review_count: int = 0
    diverged_count: int = 0


_jobs: Dict[str, JobState] = {}
# Единственное активное задание (см. модуль-докстринг: одно задание за раз).
# Используется, чтобы (1) отклонять повторный /run, пока прошлое не
# завершилось, и (2) дать фронтенду восстановить job_id после перезагрузки
# страницы (Streamlit-сессия при F5 создаётся заново и теряет session_state).
_active_job_id: Optional[str] = None


def _run_job(
    job_id: str,
    input_dir: str,
    output_dir: str,
    threshold: float,
    preferred_model: Optional[str],
    lang: str,
    latin_model_size: str,
    extract_pdf_text_layer: bool,
    detector_engine: str,
):
    global _active_job_id
    state = _jobs[job_id]

    def on_found(count: int) -> None:
        state.docs_found = count

    def on_file_done() -> None:
        state.docs_processed += 1

    def on_line_done(bucket: str, diverged: bool) -> None:
        if bucket == "good":
            state.good_count += 1
        else:
            state.review_count += 1
        if diverged:
            state.diverged_count += 1

    try:
        good_count, needs_review_count = pipeline.run(
            input_dir,
            output_dir,
            threshold,
            preferred_model,
            lang,
            latin_model_size,
            extract_pdf_text_layer,
            detector_engine,
            on_found=on_found,
            on_file_done=on_file_done,
            on_line_done=on_line_done,
        )
        state.status = "done"
        state.result = {
            "output_dir": output_dir,
            "good_count": good_count,
            "needs_review_count": needs_review_count,
        }
    except Exception as e:
        state.status = "error"
        state.error = str(e)
    finally:
        _active_job_id = None


def start_job(
    input_dir: str,
    output_dir: str,
    threshold: float,
    preferred_model: Optional[str] = None,
    lang: str = "ru",
    latin_model_size: str = DEFAULT_LATIN_MODEL_SIZE,
    extract_pdf_text_layer: bool = True,
    detector_engine: str = DEFAULT_DETECTOR_ENGINE,
) -> str:
    """Запускает pipeline.run в фоновом потоке и сразу возвращает job_id.

    Поднимает RuntimeError, если уже выполняется другое задание — вызывающий
    код (main.py) должен превращать это в HTTP 409.
    """
    global _active_job_id
    if _active_job_id is not None:
        raise RuntimeError(f"Уже выполняется задание {_active_job_id}")

    job_id = str(uuid.uuid4())
    _jobs[job_id] = JobState(status="running")
    _active_job_id = job_id
    thread = threading.Thread(
        target=_run_job,
        args=(
            job_id,
            input_dir,
            output_dir,
            threshold,
            preferred_model,
            lang,
            latin_model_size,
            extract_pdf_text_layer,
            detector_engine,
        ),
        daemon=True,
    )
    thread.start()
    return job_id


def get_job(job_id: str) -> Optional[JobState]:
    return _jobs.get(job_id)


def get_active_job_id() -> Optional[str]:
    return _active_job_id
