"""Хранилище задач в памяти процесса.

Состояние задач (счётчики/статус) не переживает перезапуск backend'а — это
осознанное упрощение для одноразового спайка с одним одновременным заданием
на одной машине. Сами результаты (good.txt/needs_review.txt/debug.jsonl) не
теряются, так как пишутся на диск построчно (см. backend/pipeline.py); чтобы
после рестарта можно было понять, чем закончилось прошлое задание, статус
дополнительно дублируется на диск снэпшотом (см. _write_snapshot) —
GET /jobs/status_snapshot читает его по output_dir, а не по job_id.
"""

import json
import os
import threading
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional

from backend import pipeline
from backend.detector import DEFAULT_DETECTOR_ENGINE
from backend.recognizers import DEFAULT_LATIN_MODEL_SIZE

JobStatus = Literal["running", "done", "error", "cancelled"]
SNAPSHOT_FILENAME = "_job_status.json"
# Сколько последних сообщений об ошибках/таймаутах хранить целиком — сам
# error_count при этом растёт без ограничения, обрезается только список.
MAX_STORED_ERRORS = 50


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
    # Ошибки/таймауты отдельных файлов/строк (см. on_error в
    # backend/pipeline.py) — раньше уходили только в print(), т.е. были
    # невидимы в UI: пользователь видел просто меньшую итоговую цифру без
    # объяснения. error_count считает все случаи, errors хранит последние
    # MAX_STORED_ERRORS сообщений (не безгранично, чтобы не раздувать память
    # на большой папке с систематической проблемой).
    error_count: int = 0
    errors: List[str] = field(default_factory=list)
    # Кооперативная отмена — поток нельзя убить напрямую, поэтому
    # pipeline.run() сам проверяет этот флаг между файлами/страницами/
    # строками (см. should_cancel в backend/pipeline.py).
    cancel_event: threading.Event = field(default_factory=threading.Event)


def _snapshot_path(output_dir: str) -> str:
    return os.path.join(output_dir, SNAPSHOT_FILENAME)


def _write_snapshot(output_dir: str, state: JobState) -> None:
    """Лучшее-из-возможного дублирование статуса на диск — если это упадёт
    (например, output_dir не существует ещё на самом первом чекпоинте), job
    не должен из-за этого прерываться."""
    try:
        with open(_snapshot_path(output_dir), "w", encoding="utf-8") as f:
            json.dump(status_dict(state), f, ensure_ascii=False)
    except OSError:
        pass


def status_dict(state: JobState) -> dict:
    """Общая форма для GET /status/{job_id} и снэпшота на диске.

    errors копируется (не отдаётся напрямую) — state.errors мутируется
    (append/pop(0)) из фонового потока job'а в on_error (см. _run_job), а
    этот словарь может параллельно сериализоваться в HTTP-потоке FastAPI
    (/status) или при записи снэпшота. list(...) делает каждый вызов
    консистентным снимком вместо общей изменяемой ссылки.
    """
    return {
        "status": state.status,
        "error": state.error,
        "docs_found": state.docs_found,
        "docs_processed": state.docs_processed,
        "good_count": state.good_count,
        "review_count": state.review_count,
        "diverged_count": state.diverged_count,
        "error_count": state.error_count,
        "errors": list(state.errors),
    }


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
        _write_snapshot(output_dir, state)

    def on_line_done(bucket: str, diverged: bool) -> None:
        if bucket == "good":
            state.good_count += 1
        else:
            state.review_count += 1
        if diverged:
            state.diverged_count += 1

    def on_error(msg: str) -> None:
        state.error_count += 1
        state.errors.append(msg)
        if len(state.errors) > MAX_STORED_ERRORS:
            state.errors.pop(0)

    def should_cancel() -> bool:
        return state.cancel_event.is_set()

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
            on_error=on_error,
            should_cancel=should_cancel,
        )
        state.status = "cancelled" if state.cancel_event.is_set() else "done"
        state.result = {
            "output_dir": output_dir,
            "good_count": good_count,
            "needs_review_count": needs_review_count,
        }
    except Exception as e:
        state.status = "error"
        state.error = str(e)
    finally:
        _write_snapshot(output_dir, state)
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


def cancel_job(job_id: str) -> None:
    """Просит выполняющееся задание остановиться на ближайшей проверке
    (см. should_cancel в backend/pipeline.py) — не убивает поток напрямую,
    поэтому уже записанные good.txt/needs_review.txt/debug.jsonl не портятся.

    Поднимает KeyError, если job_id неизвестен, и RuntimeError, если задание
    уже не выполняется — main.py превращает их в 404/409.
    """
    state = _jobs.get(job_id)
    if state is None:
        raise KeyError(f"Задание {job_id} не найдено")
    if state.status != "running":
        raise RuntimeError(f"Задание {job_id} уже не выполняется (status={state.status})")
    state.cancel_event.set()


def get_status_snapshot(output_dir: str) -> Optional[dict]:
    """Читает последний записанный на диск снэпшот статуса для output_dir —
    переживает перезапуск backend'а, в отличие от _jobs (см. докстринг
    модуля). Возвращает None, если снэпшота нет или он повреждён."""
    try:
        with open(_snapshot_path(output_dir), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
