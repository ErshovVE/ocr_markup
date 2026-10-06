<!-- Generated: 2026-10-06 | Files scanned: 14 py (frontend) | Token estimate: ~650 -->

# Frontend (Streamlit labeling app)

Entry point `frontend/app.py`; run `cd frontend && streamlit run app.py --server.enableXsrfProtection=false`.
UI strings go through `src/i18n.py::t()` (RU/EN, `st.session_state["lang"]`, flag switch at the top).

## Page tree
app.py::main()
├─ init_session_state() · render_language_switch()
├─ app_mode None → render_mode_landing() ("Авторазметка" → generation, "Ручная разметка" → manual)
├─ generation → src/ui/generation_view.py::render_generation_mode()
│   ├─ tab models: _render_model_status() — GET /models/status (cached), POST /models/prepare; VLM rows (no download)
│   └─ tab run: _render_run_controls()
│       ├─ run type classic | vlm → _render_classic_run_form (engines "N из M", detector, lang, PDF text layer,
│       │   OCR fallback) | _render_vlm_run_form (vlm_engines, min agree, IoU); _render_label_options
│       │   (append_crop_size, normalize_labels, alphabet_file) → _submit_run → POST /run (warnings shown)
│       └─ _render_job_tracker_section — _adopt_active_job (GET /jobs/active after F5), _render_live_tracker
│           (GET /status every 2 s), cancel (POST /jobs/{id}/cancel), snapshot (GET /jobs/status_snapshot),
│           _render_go_to_manual_button → _build_manager_from_output → manual mode (filter "diverged" if any)
└─ manual → src/ui/manual_mode.py::render_manual_mode()
    ├─ upload/working dir → AnnotationManager (skipped when generation already set session_state.manager)
    ├─ src/ui/list_view.py::render_image_list — filters all/unmarked/marked/diverged, pagination, ⚠️ on diverged
    ├─ src/ui/editor_view.py::render_image_editor — edit form, action buttons (←/→ nav, rotate, delete, handwritten),
    │   unsaved banner, _render_engine_details (per-engine text+score from debug.jsonl)
    └─ src/ui/sidebar.py::render_sidebar — stats, save all, backups

## Key files
src/annotations.py (297) — AnnotationManager: load_from_file, _load_debug_file, update_annotation, swap_crop_size,
  delete_record, save_changes, get_image_list; split_crop_size/format_line (`\tw\th` tail); save_as_handwritten
src/backup.py (111) — BackupManager (5 rotated backups) · src/models.py (23) — ImageRecord
src/image_ops.py (75) — load_and_resize_image (@st.cache_data), rotate_image (clears that cache — fragile coupling)
src/hotkeys.py (54) — JS hotkeys matched to literal ←/→ button text · src/i18n.py (366) — STRINGS RU/EN, t()
src/ui/generation_view.py (574) — see tree above · wrapper.py — PyInstaller entry

## Deliberately not in the UI
`degrade_*` options of POST /run (page degradation) — API/CLI only by design: the UI is for labeling real documents
via OCR/VLM, while degradation is batch dataset production for clean-label sources (synthetic, born-digital PDFs),
driven by scripts or doc-generator's balancer; degraded crops in manual review would also invite "fixing" correct labels.

## State
Only `st.session_state`: manager, current_idx, current_page, page_size, filter_option, unsaved_changes,
confirm_delete, show_backups, app_mode, lang, models_status_cache, consensus_job_id, consensus_status_data,
consensus_snapshot.
