<!-- Generated: 2026-08-19 | Files scanned: 11 | Token estimate: ~550 -->

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
├─ src/ui/list_view.py::render_image_list(manager, filtered_images) — filter + pagination
├─ src/ui/editor_view.py::render_image_editor(manager) — text edit/delete/rotate/nav; _render_delete_confirm
│    (nav buttons carry literal ←/→ text matched by src/hotkeys.py::register_hotkeys JS)
└─ src/ui/sidebar.py::render_sidebar(manager) — stats, save-all, backup list/restore

## Component hierarchy — generation mode
generation_view.py::render_generation_mode()
├─ _render_model_status() — polls GET /models/status, POST /models/prepare
├─ _render_run_controls() — POST /run, GET /status/{job_id}
└─ on job done: "📥 Перейти к разметке результатов" → _build_manager_from_output(output_dir)
     → new AnnotationManager(output_dir, output_dir/"review.txt"), loads good.txt (is_marked=True)
       and needs_review.txt (unmarked) via manager.load_from_file
     → session_state.manager = manager; session_state.app_mode = "manual"; st.rerun()
     (manual_mode.py then skips the file_uploader step since manager is pre-populated)

## Key files
src/models.py (11) — ImageRecord dataclass: relative_path, absolute_path, annotation, is_marked=False
src/backup.py (105) — BackupManager(base_dir, max_backups=5): create_backup(); metadata in .backups/metadata.json
src/annotations.py (197) — AnnotationManager(base_dir, annotation_file): load_from_file, get_image_list, delete_record, save_changes; module fn save_as_handwritten
src/image_ops.py (36) — load_and_resize_image (@st.cache_data), rotate_image (calls .clear() on that cache — fragile coupling, see docs/architecture.md)
src/hotkeys.py (54) — register_hotkeys(): injects JS matching buttons by literal ←/→ text
src/ui/list_view.py (91) — render_image_list
src/ui/editor_view.py (200) — render_image_editor, _render_delete_confirm
src/ui/sidebar.py (76) — render_sidebar
src/ui/manual_mode.py (65) — render_manual_mode
src/ui/generation_view.py (142) — render_generation_mode, _render_model_status, _render_run_controls, _build_manager_from_output
wrapper.py — PyInstaller entry point, launches Streamlit headless from bundled exe

## State management
All state lives in `st.session_state` — no external state library. See "Page tree / mode dispatch" above for the full key list.

## Dependencies
streamlit==1.36.0, Pillow==10.4.0, requests==2.32.3 (talks to backend via `CONSENSUS_BACKEND_URL`, default `http://127.0.0.1:8756`)
