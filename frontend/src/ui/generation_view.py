import os

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
ENGINES = (("paddle", "PaddleOCR"), ("surya", "SuryaOCR"), ("tesseract", "Tesseract"))


def render_generation_mode():
    """Отрисовывает режим авторазметки: статус моделей + запуск консенсуса + handoff"""
    st.header("🤖 Авторазметка")
    _render_model_status()
    st.divider()
    _render_run_controls()


def _render_model_status():
    st.subheader("Модели")
    if st.button("🔄 Обновить статус", key="models_refresh"):
        st.session_state.pop("models_status_cache", None)

    if "models_status_cache" not in st.session_state:
        try:
            resp = requests.get(f"{BACKEND_URL}/models/status", timeout=5)
            resp.raise_for_status()
            st.session_state.models_status_cache = resp.json()
        except Exception as e:
            st.error(f"Backend недоступен: {e}")
            return

    for name, label in ENGINES:
        info = st.session_state.models_status_cache.get(name, {})
        status = info.get("status", "not_checked")
        col1, col2, col3 = st.columns([2, 2, 1])
        col1.write(label)
        col2.write(STATUS_LABELS.get(status, status))
        if name != "tesseract" and status not in ("ready", "checking"):
            if col3.button("Скачать", key=f"prepare_{name}"):
                try:
                    resp = requests.post(
                        f"{BACKEND_URL}/models/prepare",
                        json={"model": name},
                        timeout=5,
                    )
                    resp.raise_for_status()
                    st.session_state.pop("models_status_cache", None)
                    st.rerun()
                except Exception as e:
                    st.error(f"Ошибка запуска подготовки: {e}")
        if info.get("detail"):
            st.caption(info["detail"])


def _render_run_controls():
    input_dir = st.text_input("Папка с документами", key="consensus_input")
    output_dir = st.text_input("Папка вывода", key="consensus_output")
    threshold = st.slider("Порог уверенности", 0.0, 1.0, 0.95, key="consensus_threshold")
    preferred = st.selectbox(
        "Предпочитаемая модель (при разногласии)",
        [None, "paddle", "surya", "tesseract"],
        key="consensus_preferred",
    )
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
                },
                timeout=5,
            )
            resp.raise_for_status()
            st.session_state.consensus_job_id = resp.json()["job_id"]
            st.success("Запущено")
        except Exception as e:
            st.error(f"Ошибка запуска: {e}")

    if st.session_state.get("consensus_job_id"):
        if st.button("🔄 Статус", key="consensus_status"):
            try:
                resp = requests.get(
                    f"{BACKEND_URL}/status/{st.session_state.consensus_job_id}",
                    timeout=5,
                )
                resp.raise_for_status()
                st.info(resp.json()["status"])
            except Exception as e:
                st.error(f"Ошибка статуса: {e}")

        if st.button("📥 Перейти к разметке результатов", key="consensus_to_manual"):
            manager = _build_manager_from_output(output_dir)
            if manager:
                st.session_state.manager = manager
                st.session_state.app_mode = "manual"
                st.rerun()


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
