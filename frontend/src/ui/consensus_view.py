import os

import requests
import streamlit as st

from src.annotations import AnnotationManager

BACKEND_URL = "http://127.0.0.1:8756"


def render_consensus_section(manager: AnnotationManager):
    """Отрисовывает секцию запуска и импорта OCR-консенсуса"""
    st.sidebar.divider()
    st.sidebar.header("🤖 Консенсус OCR")

    input_dir = st.sidebar.text_input("Папка с документами", key="consensus_input")
    output_dir = st.sidebar.text_input("Папка вывода", key="consensus_output")
    threshold = st.sidebar.slider(
        "Порог уверенности", 0.0, 1.0, 0.95, key="consensus_threshold"
    )
    preferred = st.sidebar.selectbox(
        "Предпочитаемая модель (при разногласии)",
        [None, "paddle", "surya", "tesseract"],
        key="consensus_preferred",
    )

    if st.sidebar.button("▶ Запустить", key="consensus_run"):
        try:
            resp = requests.post(
                f"{BACKEND_URL}/run",
                json={
                    "input_dir": input_dir,
                    "output_dir": output_dir,
                    "score_threshold": threshold,
                    "preferred_model": preferred,
                },
                timeout=5,
            )
            resp.raise_for_status()
            st.session_state.consensus_job_id = resp.json()["job_id"]
            st.sidebar.success("Запущено")
        except Exception as e:
            st.sidebar.error(f"Ошибка запуска: {e}")

    if st.session_state.get("consensus_job_id"):
        if st.sidebar.button("🔄 Статус", key="consensus_status"):
            try:
                resp = requests.get(
                    f"{BACKEND_URL}/status/{st.session_state.consensus_job_id}",
                    timeout=5,
                )
                resp.raise_for_status()
                st.sidebar.info(resp.json()["status"])
            except Exception as e:
                st.sidebar.error(f"Ошибка статуса: {e}")

        st.sidebar.caption(
            "⚠️ Перезапишет существующие записи с тем же именем файла"
        )
        if st.sidebar.button("📥 Импортировать", key="consensus_import"):
            _import_results(manager, output_dir)


def _import_results(manager: AnnotationManager, output_dir: str):
    """Импортирует good.txt/needs_review.txt в текущий AnnotationManager"""
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
                st.sidebar.error(f"{fname}: {error}")
                continue
            if mark_as_done:
                for name in imported_names & manager.records.keys():
                    manager.records[name].is_marked = True
                    manager.modified_records.add(name)
        st.sidebar.success("Импортировано")
    except Exception as e:
        st.sidebar.error(f"Ошибка импорта: {e}")
