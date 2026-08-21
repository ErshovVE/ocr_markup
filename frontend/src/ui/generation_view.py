import os
from typing import Optional

import requests
import streamlit as st

from src.annotations import AnnotationManager

BACKEND_URL = os.environ.get("CONSENSUS_BACKEND_URL", "http://127.0.0.1:8756")
STATUS_LABELS = {
    "ready": "✅ Готово",
    "checking": "⏳ Проверка/скачивание...",
    "error": "❌ Ошибка",
    "not_checked": "⚪ Не проверено",
}
JOB_STATUS_LABELS = {
    "running": "⏳ Выполняется",
    "done": "✅ Готово",
    "error": "❌ Ошибка",
    "cancelled": "⏹ Отменено",
}
ENGINES = (("paddle", "PaddleOCR"), ("surya", "SuryaOCR"), ("tesseract", "Tesseract"))
DETECTOR_STATUS_KEYS = {
    "paddle": "paddle_detector",
    "surya": "surya_detector",
    "tesseract": "tesseract",
}


def render_generation_mode():
    """Отрисовывает режим авторазметки: статус моделей + запуск консенсуса + handoff.

    Разбито на вкладки (а не один длинный столбец), чтобы окно не приходилось
    прокручивать — статус моделей и форма запуска редко нужны одновременно.
    """
    st.header("🤖 Авторазметка")
    tab_models, tab_run = st.tabs(["📦 Модели", "▶ Запуск"])
    with tab_models:
        _render_model_status()
    with tab_run:
        _render_run_controls()


def _render_engine_status_cell(col, status_key, downloadable, key_prefix):
    """Рисует статус одного движка в ячейке таблицы: текст + кнопка «Скачать» под ним, если нужна"""
    info = st.session_state.models_status_cache.get(status_key, {})
    status = info.get("status", "not_checked")
    text = STATUS_LABELS.get(status, status)
    if info.get("detail"):
        text += f" · {info['detail']}"
    with col:
        st.write(text)
        if downloadable and status not in ("ready", "checking"):
            if st.button("Скачать", key=f"prepare_{key_prefix}_{status_key}"):
                try:
                    resp = requests.post(
                        f"{BACKEND_URL}/models/prepare",
                        json={"model": status_key},
                        timeout=5,
                    )
                    resp.raise_for_status()
                    st.session_state.pop("models_status_cache", None)
                    st.rerun()
                except Exception as e:
                    st.error(f"Ошибка запуска подготовки: {e}")


def _render_model_status():
    """Компактная таблица движок × (распознавание, детекция) вместо построчного списка"""
    if "models_status_cache" not in st.session_state:
        try:
            resp = requests.get(f"{BACKEND_URL}/models/status", timeout=5)
            resp.raise_for_status()
            st.session_state.models_status_cache = resp.json()
        except Exception as e:
            st.error(f"Backend недоступен: {e}")
            return

    header = st.columns([2, 3, 3])
    header[0].markdown("**Движок**")
    header[1].markdown("**Распознавание**")
    header[2].markdown("**Детекция строк**")

    for name, label in ENGINES:
        row = st.columns([2, 3, 3])
        row[0].write(label)
        _render_engine_status_cell(row[1], name, name != "tesseract", "rec")
        det_key = DETECTOR_STATUS_KEYS[name]
        _render_engine_status_cell(row[2], det_key, det_key != "tesseract", "det")

    if st.button("🔄 Обновить статус", key="models_refresh"):
        st.session_state.pop("models_status_cache", None)
        st.rerun()


def _adopt_active_job():
    """Восстанавливает job_id уже выполняющегося задания в session_state.

    Streamlit создаёт новую сессию (и обнуляет session_state) на перезагрузку
    страницы, поэтому без этого трекер прогресса "терялся" бы после F5, хотя
    задание в backend продолжает выполняться (backend/jobs.py допускает
    только одно активное задание, см. GET /jobs/active).
    """
    try:
        resp = requests.get(f"{BACKEND_URL}/jobs/active", timeout=5)
        resp.raise_for_status()
        job_id = resp.json().get("job_id")
        if job_id:
            st.session_state.consensus_job_id = job_id
    except Exception:
        pass


def _format_backend_error(e: Exception) -> str:
    """Достаёт JSON-поле detail из ответа FastAPI, если оно есть — иначе str(e)"""
    response = getattr(e, "response", None)
    if response is not None:
        try:
            detail = response.json().get("detail")
            if detail:
                return detail
        except ValueError:
            pass
    return str(e)


def _render_go_to_manual_button(output_dir: str, diverged_count: int, key: str):
    """Кнопка перехода в ручную разметку результатов — общая для живого
    трекера и восстановленного из снэпшота статуса (см. _render_run_controls)."""
    if st.button("📥 Перейти к разметке результатов", key=key, use_container_width=True):
        manager = _build_manager_from_output(output_dir)
        if manager:
            st.session_state.manager = manager
            # Если есть спорные строки — сразу показываем их, а не "Все"
            # (иначе разметчику пришлось бы переключать фильтр вручную,
            # чтобы найти как раз то, ради чего он сюда пришёл).
            if diverged_count > 0 and manager.get_image_list("diverged"):
                st.session_state.filter_option = "diverged"
            st.session_state.app_mode = "manual"
            st.rerun()


def _render_run_controls():
    if "consensus_job_id" not in st.session_state:
        _adopt_active_job()

    col_in, col_out = st.columns(2)
    input_dir = col_in.text_input(
        "Папка с документами", key="consensus_input", placeholder="Например: /data/Датасет"
    )
    output_dir = col_out.text_input(
        "Папка вывода", key="consensus_output", placeholder="Например: /data/Датасет_результат"
    )

    col_det, col_pref, col_thr = st.columns(3)
    detector_engine = col_det.selectbox(
        "Детектор строк текста",
        ["paddle", "surya", "tesseract"],
        key="consensus_detector",
    )
    preferred = col_pref.selectbox(
        "Предпочитаемая модель (при разногласии)",
        [None, "paddle", "surya", "tesseract"],
        key="consensus_preferred",
    )
    threshold = col_thr.slider("Порог уверенности", 0.0, 1.0, 0.95, key="consensus_threshold")

    extract_pdf_text_layer = st.checkbox(
        "Извлекать текст из PDF напрямую, без OCR (если есть текстовый слой)",
        value=True,
        key="consensus_extract_pdf",
    )

    if st.button("▶ Запустить", key="consensus_run"):
        try:
            resp = requests.post(
                f"{BACKEND_URL}/run",
                json={
                    "input_dir": input_dir,
                    "output_dir": output_dir,
                    "score_threshold": threshold,
                    "preferred_model": preferred,
                    "extract_pdf_text_layer": extract_pdf_text_layer,
                    "detector_engine": detector_engine,
                },
                timeout=5,
            )
            resp.raise_for_status()
            run_data = resp.json()
            st.session_state.consensus_job_id = run_data["job_id"]
            st.session_state.pop("consensus_status_data", None)
            st.session_state.pop("consensus_snapshot", None)
            st.success("Запущено")
            for warning in run_data.get("warnings", []):
                st.warning(warning)
        except Exception as e:
            st.error(f"Ошибка запуска: {_format_backend_error(e)}")

    if st.session_state.get("consensus_job_id"):
        _render_live_tracker()

        col_to_manual, col_cancel = st.columns(2)
        with col_to_manual:
            status_data = st.session_state.get("consensus_status_data") or {}
            _render_go_to_manual_button(
                output_dir, status_data.get("diverged_count", 0), key="consensus_to_manual"
            )
        with col_cancel:
            job_status = (st.session_state.get("consensus_status_data") or {}).get("status")
            if job_status == "running" and st.button("⏹ Отменить", key="consensus_cancel"):
                try:
                    resp = requests.post(
                        f"{BACKEND_URL}/jobs/{st.session_state.consensus_job_id}/cancel",
                        timeout=5,
                    )
                    resp.raise_for_status()
                    st.info("Останавливается...")
                except Exception as e:
                    st.error(f"Ошибка отмены: {_format_backend_error(e)}")
    elif output_dir:
        # Нет отслеживаемого job_id в этой сессии (например, backend
        # перезапускался и потерял состояние в памяти, см. backend/jobs.py) —
        # снэпшот последнего статуса для этой output_dir переживает рестарт,
        # в отличие от job_id.
        if st.button("🔍 Проверить статус последнего запуска", key="consensus_check_snapshot"):
            try:
                resp = requests.get(
                    f"{BACKEND_URL}/jobs/status_snapshot",
                    params={"output_dir": output_dir},
                    timeout=5,
                )
                if resp.status_code == 404:
                    st.session_state.pop("consensus_snapshot", None)
                    st.info("Для этой папки вывода ещё не было запусков")
                else:
                    resp.raise_for_status()
                    st.session_state.consensus_snapshot = resp.json()
            except Exception as e:
                st.error(f"Ошибка проверки: {_format_backend_error(e)}")

        # Вынесено из-под if st.button(...) выше намеренно: кнопка "Проверить"
        # истинна только в том самом rerun'е, когда её нажали. Кнопка "Перейти
        # к разметке" внутри неё же не пережила бы свой собственный клик —
        # на следующем rerun'е "Проверить" снова false, и весь вложенный блок
        # (вместе с обработкой клика по вложенной кнопке) просто не выполнился
        # бы. Читая снэпшот из session_state здесь, вне if, обе кнопки — и
        # "Проверить", и "Перейти" — остаются рабочими на любом rerun'е.
        snapshot = st.session_state.get("consensus_snapshot")
        if snapshot:
            _render_progress_tracker(snapshot)
            if snapshot.get("status") == "done":
                _render_go_to_manual_button(
                    output_dir,
                    snapshot.get("diverged_count", 0),
                    key="consensus_to_manual_snapshot",
                )


@st.experimental_fragment(run_every="2s")
def _render_live_tracker():
    """Опрашивает GET /status раз в 2с, пока задание не завершится (см. #st.experimental_fragment).

    Именно experimental_fragment, а не st.fragment: последний появился в
    streamlit 1.37, а в проекте зафиксирована 1.36.0 (frontend/requirements.txt).
    """
    job_id = st.session_state.get("consensus_job_id")
    if not job_id:
        return

    status_data = st.session_state.get("consensus_status_data")
    if status_data and status_data["status"] in ("done", "error", "cancelled"):
        _render_progress_tracker(status_data)
        return

    try:
        resp = requests.get(f"{BACKEND_URL}/status/{job_id}", timeout=5)
        resp.raise_for_status()
        st.session_state.consensus_status_data = resp.json()
    except Exception as e:
        st.error(f"Ошибка статуса: {e}")
        return

    _render_progress_tracker(st.session_state.consensus_status_data)


def _render_progress_tracker(status_data: Optional[dict]):
    """Отрисовывает трекер прогресса задания по данным GET /status"""
    if not status_data:
        return

    found = status_data.get("docs_found", 0)
    processed = status_data.get("docs_processed", 0)
    good = status_data.get("good_count", 0)
    review = status_data.get("review_count", 0)
    diverged = status_data.get("diverged_count", 0)
    error_count = status_data.get("error_count", 0)

    status_label = JOB_STATUS_LABELS.get(status_data["status"], status_data["status"])
    st.caption(f"{status_label} · документов {processed} / {found}")
    if status_data.get("error"):
        st.error(status_data["error"])

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Строк всего", good + review)
    col2.metric("Хороших", good)
    col3.metric("Плохих", review)
    col4.metric("Разошедшихся", diverged)
    col5.metric("Ошибок", error_count)

    errors = status_data.get("errors") or []
    if errors:
        with st.expander(f"⚠️ Ошибки/таймауты ({error_count})"):
            for msg in errors:
                st.caption(msg)


def _build_manager_from_output(output_dir: str):
    """Строит новый AnnotationManager из good.txt/needs_review.txt в output_dir"""
    manager = AnnotationManager(output_dir, os.path.join(output_dir, "review.txt"))
    try:
        for fname, mark_as_done in (("good.txt", True), ("needs_review.txt", False)):
            path = os.path.join(output_dir, fname)
            if not os.path.exists(path):
                continue
            with open(path, "r", encoding="utf-8") as f:
                contents = f.read()
            imported_names = {
                os.path.basename(line.split("\t", 1)[0].strip())
                for line in contents.splitlines()
                if line.strip()
            }
            success, error = manager.load_from_file(contents)
            if not success:
                st.error(f"{fname}: {error}")
                continue
            if mark_as_done:
                for name in imported_names & manager.records.keys():
                    manager.records[name].is_marked = True
                    manager.modified_records.add(name)
    except Exception as e:
        st.error(f"Ошибка импорта: {e}")
        return None

    if not manager.records:
        st.warning("В папке вывода не найдено результатов")
        return None

    return manager
