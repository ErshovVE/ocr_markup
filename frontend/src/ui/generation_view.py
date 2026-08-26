import os
from typing import Optional

import requests
import streamlit as st

from src.annotations import AnnotationManager
from src.i18n import t

BACKEND_URL = os.environ.get("CONSENSUS_BACKEND_URL", "http://127.0.0.1:8756")
ENGINES = (("paddle", "PaddleOCR"), ("surya", "SuryaOCR"), ("tesseract", "Tesseract"))
ENGINE_LABELS = dict(ENGINES)
ENGINE_KEYS = tuple(k for k, _ in ENGINES)
DETECTOR_STATUS_KEYS = {
    "paddle": "paddle_detector",
    "surya": "surya_detector",
    "tesseract": "tesseract",
}
# Схема сверки движков распознавания: сколько движков вообще прогонять на
# строку (engines_count) и сколько из них должны сойтись в одном тексте,
# чтобы принять его без ручной проверки (min_agree, см. backend/consensus.py
# vote()/backend/main.py RunRequest.min_agree). Раньше здесь не было выбора —
# всегда прогонялись все 3 движка с требованием совпадения любых двух
# ("2 из 3" ниже) вне зависимости от того, что реально нужно разметчику.
CONSENSUS_SCHEME_KEYS = ("1_of_1", "1_of_2", "2_of_2", "2_of_3")
CONSENSUS_SCHEME_ENGINES_COUNT = {"1_of_1": 1, "1_of_2": 2, "2_of_2": 2, "2_of_3": 3}
CONSENSUS_SCHEME_MIN_AGREE = {"1_of_1": 1, "1_of_2": 1, "2_of_2": 2, "2_of_3": 2}
DEFAULT_CONSENSUS_SCHEME = "2_of_3"


def _status_labels():
    return {
        "ready": t("status_ready"),
        "checking": t("status_checking"),
        "error": t("status_error"),
        "not_checked": t("status_not_checked"),
    }


def _job_status_labels():
    return {
        "running": t("job_status_running"),
        "done": t("job_status_done"),
        "error": t("job_status_error"),
        "cancelled": t("job_status_cancelled"),
    }


def _consensus_schemes():
    """Схемы сверки движков — локализованный label/help по CONSENSUS_SCHEME_KEYS"""
    return {
        key: {
            "label": t(f"scheme_{key}_label"),
            "engines_count": CONSENSUS_SCHEME_ENGINES_COUNT[key],
            "min_agree": CONSENSUS_SCHEME_MIN_AGREE[key],
            "help": t(f"scheme_{key}_help"),
        }
        for key in CONSENSUS_SCHEME_KEYS
    }


def render_generation_mode():
    """Отрисовывает режим авторазметки: статус моделей + запуск консенсуса + handoff.

    Разбито на вкладки (а не один длинный столбец), чтобы окно не приходилось
    прокручивать — статус моделей и форма запуска редко нужны одновременно.
    """
    st.header(t("gen_header"))
    tab_models, tab_run = st.tabs([t("gen_tab_models"), t("gen_tab_run")])
    with tab_models:
        _render_model_status()
    with tab_run:
        _render_run_controls()


def _render_engine_status_cell(col, status_key, downloadable, key_prefix):
    """Рисует статус одного движка в ячейке таблицы: текст + кнопка «Скачать» под ним, если нужна"""
    info = st.session_state.models_status_cache.get(status_key, {})
    status = info.get("status", "not_checked")
    text = _status_labels().get(status, status)
    if info.get("detail"):
        text += f" · {info['detail']}"
    with col:
        st.write(text)
        if downloadable and status not in ("ready", "checking"):
            if st.button(t("download_btn"), key=f"prepare_{key_prefix}_{status_key}"):
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
                    st.error(t("prepare_start_error", err=e))


def _render_model_status():
    """Компактная таблица движок × (распознавание, детекция) вместо построчного списка"""
    if "models_status_cache" not in st.session_state:
        try:
            resp = requests.get(f"{BACKEND_URL}/models/status", timeout=5)
            resp.raise_for_status()
            st.session_state.models_status_cache = resp.json()
        except Exception as e:
            st.error(t("backend_unavailable", err=e))
            return

    header = st.columns([2, 3, 3])
    header[0].markdown(t("engine_col"))
    header[1].markdown(t("recognition_col"))
    header[2].markdown(t("detection_col"))

    for name, label in ENGINES:
        row = st.columns([2, 3, 3])
        row[0].write(label)
        _render_engine_status_cell(row[1], name, name != "tesseract", "rec")
        det_key = DETECTOR_STATUS_KEYS[name]
        _render_engine_status_cell(row[2], det_key, det_key != "tesseract", "det")

    if st.button(t("refresh_status_btn"), key="models_refresh"):
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
    if st.button(t("go_to_manual_btn"), key=key, use_container_width=True):
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
        t("input_dir_label"), key="consensus_input", placeholder=t("working_dir_placeholder")
    )
    output_dir = col_out.text_input(
        t("output_dir_label"), key="consensus_output", placeholder=t("output_dir_placeholder")
    )

    col_det, col_thr = st.columns(2)
    detector_engine = col_det.selectbox(
        t("detector_engine_label"),
        ["paddle", "surya", "tesseract"],
        key="consensus_detector",
    )
    threshold = col_thr.slider(
        t("confidence_threshold_label"), 0.0, 1.0, 0.95, key="consensus_threshold"
    )

    schemes = _consensus_schemes()
    scheme_key = st.selectbox(
        t("consensus_scheme_label"),
        list(schemes.keys()),
        index=list(schemes.keys()).index(DEFAULT_CONSENSUS_SCHEME),
        format_func=lambda k: schemes[k]["label"],
        key="consensus_scheme",
    )
    scheme = schemes[scheme_key]
    st.caption(scheme["help"])
    engines_count = scheme["engines_count"]
    min_agree = scheme["min_agree"]

    if engines_count == len(ENGINE_KEYS):
        engines = list(ENGINE_KEYS)
        st.caption(t("engines_prefix") + ", ".join(ENGINE_LABELS[e] for e in engines))
    elif engines_count == 1:
        engines = [
            st.selectbox(
                t("engine_select_label"),
                ENGINE_KEYS,
                format_func=lambda k: ENGINE_LABELS[k],
                key="consensus_single_engine",
            )
        ]
    else:
        engines = st.multiselect(
            t("engines_multiselect_label", count=engines_count),
            ENGINE_KEYS,
            format_func=lambda k: ENGINE_LABELS[k],
            max_selections=engines_count,
            key="consensus_multi_engines",
        )

    preferred = None
    if len(engines) >= 2:
        preferred = st.selectbox(
            t("preferred_model_label"),
            [None, *engines],
            format_func=lambda k: "—" if k is None else ENGINE_LABELS[k],
            key="consensus_preferred",
        )

    extract_pdf_text_layer = st.checkbox(
        t("extract_pdf_label"),
        value=True,
        key="consensus_extract_pdf",
    )

    if st.button(t("run_btn"), key="consensus_run"):
        if len(engines) != engines_count:
            st.error(t("choose_exact_engines_error", count=engines_count))
        else:
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
                        "engines": engines,
                        "min_agree": min_agree,
                    },
                    timeout=5,
                )
                resp.raise_for_status()
                run_data = resp.json()
                st.session_state.consensus_job_id = run_data["job_id"]
                st.session_state.pop("consensus_status_data", None)
                st.session_state.pop("consensus_snapshot", None)
                st.success(t("run_started"))
                for warning in run_data.get("warnings", []):
                    st.warning(warning)
            except Exception as e:
                st.error(t("run_start_error", err=_format_backend_error(e)))

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
            if job_status == "running" and st.button(t("cancel_btn_gen"), key="consensus_cancel"):
                try:
                    resp = requests.post(
                        f"{BACKEND_URL}/jobs/{st.session_state.consensus_job_id}/cancel",
                        timeout=5,
                    )
                    resp.raise_for_status()
                    st.info(t("cancelling_msg"))
                except Exception as e:
                    st.error(t("cancel_error", err=_format_backend_error(e)))
    elif output_dir:
        # Нет отслеживаемого job_id в этой сессии (например, backend
        # перезапускался и потерял состояние в памяти, см. backend/jobs.py) —
        # снэпшот последнего статуса для этой output_dir переживает рестарт,
        # в отличие от job_id.
        if st.button(t("check_last_run_btn"), key="consensus_check_snapshot"):
            try:
                resp = requests.get(
                    f"{BACKEND_URL}/jobs/status_snapshot",
                    params={"output_dir": output_dir},
                    timeout=5,
                )
                if resp.status_code == 404:
                    st.session_state.pop("consensus_snapshot", None)
                    st.info(t("no_runs_yet"))
                else:
                    resp.raise_for_status()
                    st.session_state.consensus_snapshot = resp.json()
            except Exception as e:
                st.error(t("check_status_error", err=_format_backend_error(e)))

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
        st.error(f"{t('status_error')}: {e}")
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

    status_label = _job_status_labels().get(status_data["status"], status_data["status"])
    st.caption(t("docs_progress_caption", status=status_label, processed=processed, found=found))
    if status_data.get("error"):
        st.error(status_data["error"])

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric(t("lines_total_metric"), good + review)
    col2.metric(t("good_metric"), good)
    col3.metric(t("review_metric"), review)
    col4.metric(t("diverged_metric"), diverged)
    col5.metric(t("errors_metric"), error_count)

    errors = status_data.get("errors") or []
    if errors:
        with st.expander(t("errors_timeouts_expander", count=error_count)):
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
                st.error(t("import_error", fname=fname, err=error))
                continue
            if mark_as_done:
                for name in imported_names & manager.records.keys():
                    manager.records[name].is_marked = True
                    manager.modified_records.add(name)
    except Exception as e:
        st.error(t("import_general_error", err=e))
        return None

    if not manager.records:
        st.warning(t("no_results_found"))
        return None

    return manager
