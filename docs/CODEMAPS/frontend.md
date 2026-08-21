<!-- Generated: 2026-08-21 | Files scanned: 11 | Token estimate: ~650 -->

# Frontend (Streamlit labeling app)

Entry point: `frontend/app.py`. Run: `cd frontend && streamlit run app.py --server.enableXsrfProtection=false`.
Russian-language UI strings throughout — keep new code consistent.

## Page tree / mode dispatch
app.py::main()
├─ init_session_state() — defaults: manager=None, current_idx=0, current_page=0, page_size=50,
│    filter_option="all", unsaved_changes=0, confirm_delete=None, show_backups=False,
│    hotkey_trigger=0, app_mode=None
├─ if app_mode is None → render_mode_landing()
│    ├─ "Авторазметка" button → app_mode="generation" → st.rerun()
│    └─ "Ручная разметка" button → app_mode="manual" → st.rerun()
├─ "Сменить режим" button → app_mode=None (back to landing)
├─ if app_mode == "generation" → src/ui/generation_view.py::render_generation_mode()
└─ if app_mode == "manual"     → src/ui/manual_mode.py::render_manual_mode()

## Component hierarchy — manual mode
manual_mode.py::render_manual_mode()
├─ file upload + working-dir input (skipped if session_state.manager already set)
├─ builds AnnotationManager(base_dir, annotation_file) if manager is None
├─ src/ui/list_view.py::render_image_list(manager, filtered_images) — filter (all/unmarked/marked/**diverged — "Спорные"**) + pagination; ⚠️ marker on diverged rows
├─ src/ui/editor_view.py::render_image_editor(manager) — text edit/delete/rotate/nav; _render_delete_confirm; _render_engine_details — expander "🔍 Что видели движки" (per-engine text+score, 🏆 on the winner) shown only when AnnotationManager.debug_by_path has a record for the current image; ⚠️ suffix on the subheader when record.diverged
│    (nav buttons carry literal ←/→ text matched by src/hotkeys.py::register_hotkeys JS)
└─ src/ui/sidebar.py::render_sidebar(manager) — stats, save-all, backup list/restore

## Component hierarchy — generation mode
generation_view.py::render_generation_mode()
├─ _render_model_status() — polls GET /models/status, POST /models/prepare
├─ _render_run_controls() — POST /run (shows returned `warnings` via st.warning); while a job is tracked: _render_live_tracker() (GET /status/{job_id} every 2s) + _render_go_to_manual_button() + "⏹ Отменить" (POST /jobs/{id}/cancel, only while status=="running"); if no job is tracked but output_dir is filled: "🔍 Проверить статус последнего запуска" (GET /jobs/status_snapshot) — recovers status after a backend restart, result cached in session_state.consensus_snapshot (kept outside the button's own `if` so a follow-up click on the button it renders still works on the next rerun)
└─ _render_go_to_manual_button(output_dir, diverged_count, key) — shared by both the live and the recovered-snapshot path: _build_manager_from_output(output_dir) → session_state.manager; defaults filter_option to "diverged" when diverged_count>0 and that filter is non-empty; session_state.app_mode="manual"; st.rerun()
     (manual_mode.py then skips the file_uploader step since manager is pre-populated)

## Key files
src/models.py (17) — ImageRecord dataclass: relative_path, absolute_path, annotation, is_marked=False, diverged=False (set from debug.jsonl, see annotations.py)
src/backup.py (105) — BackupManager(base_dir, max_backups=5): create_backup(); metadata in .backups/metadata.json
src/annotations.py (248) — AnnotationManager(base_dir, annotation_file): load_from_file, get_image_list (filter_type: all|unmarked|marked|diverged), delete_record, save_changes; debug_by_path: Dict[relative_path, debug.jsonl record], loaded once per manager (_debug_file_loaded guard — load_from_file may be called more than once on the same manager, see generation_view.py::_build_manager_from_output) via _load_debug_file(), which also backfills ImageRecord.diverged; module fn save_as_handwritten
src/image_ops.py (36) — load_and_resize_image (@st.cache_data), rotate_image (calls .clear() on that cache — fragile coupling, see docs/architecture.md)
src/hotkeys.py (54) — register_hotkeys(): injects JS matching nav buttons by literal ←/→ text (kept — a streamlit-hotkeys-based replacement was tried and reverted, see git history around commit 54f0cfe)
src/ui/list_view.py (93) — render_image_list; diverged filter option + ⚠️ row marker
src/ui/editor_view.py (228) — render_image_editor, _render_delete_confirm, _render_engine_details
src/ui/sidebar.py (76) — render_sidebar
src/ui/manual_mode.py (66) — render_manual_mode
src/ui/generation_view.py (348) — render_generation_mode, _render_model_status, _render_run_controls, _render_go_to_manual_button, _render_live_tracker, _render_progress_tracker, _build_manager_from_output
wrapper.py — PyInstaller entry point, launches Streamlit headless from bundled exe

## State management
All state lives in `st.session_state` — no external state library. New keys this cycle: `consensus_snapshot` (cached GET /jobs/status_snapshot result). See "Page tree / mode dispatch" above for the full key list.

## Dependencies
streamlit==1.36.0, Pillow==10.4.0, requests==2.32.3 (talks to backend via `CONSENSUS_BACKEND_URL`, default `http://127.0.0.1:8756`)
