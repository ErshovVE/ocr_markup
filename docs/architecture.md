# Architecture

<p align="center">
  <strong>Language:</strong>
  <b>English</b> |
  <a href="ru/architecture.md">🇷🇺 Русский</a>
</p>

## Module map

Frontend (`frontend/`) — the Streamlit labeling app:

| File | Responsibility |
|---|---|
| `frontend/app.py` | Thin mode router: `st.set_page_config`, CSS, `init_session_state`, the mode-selection landing screen (`render_mode_landing`), routes into `render_generation_mode`/`render_manual_mode` |
| `frontend/src/models.py` | `ImageRecord` — data structure for a single image record |
| `frontend/src/backup.py` | `BackupManager` — creates, rotates, and restores backups of the annotation file |
| `frontend/src/annotations.py` | `AnnotationManager` — load/save annotations, status cache, record deletion; `save_as_handwritten` — exports an image as handwritten |
| `frontend/src/image_ops.py` | `load_and_resize_image` (cached image load) and `rotate_image` (90° rotation, clears the cache) |
| `frontend/src/hotkeys.py` | `register_hotkeys` — JS handler for the ←/→ hotkeys |
| `frontend/src/i18n.py` | `t`/`get_lang`/`set_lang`/`render_language_switch` — UI string localization (RU/EN) and the flag-based language switcher |
| `frontend/src/ui/list_view.py` | `render_image_list` — filtered, paginated image list |
| `frontend/src/ui/editor_view.py` | `render_image_editor` — the current image's editor: text, delete, rotate, navigation |
| `frontend/src/ui/sidebar.py` | `render_sidebar` — stats, save-all, backup management |
| `frontend/src/ui/manual_mode.py` | `render_manual_mode` — the manual-labeling flow: file/working-directory upload, `AnnotationManager` init, list/editor/sidebar |
| `frontend/src/ui/generation_view.py` | `render_generation_mode` — Paddle/Surya/Tesseract model status, OCR-consensus run/status, handoff into manual mode without a file_uploader |

Backend (`backend/`) — the FastAPI OCR-consensus spike: see `backend/README.md`.

## Data formats

### Annotation file (`rec.txt` / uploaded .txt)
Tab-separated format, one line per image:
```
relative_path\tannotation_text
```
Source: `AnnotationManager.load_from_file` (`frontend/src/annotations.py`), `AnnotationManager.save_changes` (`frontend/src/annotations.py`).

### `status_cache.txt`
One image filename (not a path) per line — the list of images with `is_marked=True`. Located at `base_dir/<first_path_segment>/status_cache.txt`, where `<first_path_segment>` is taken from the first component of the relative path of the first loaded record.
Source: `AnnotationManager._load_status_cache` (`frontend/src/annotations.py`).

### `handwritten.txt`
Tab-separated, append-only file with duplicate checking by exact line match:
```
handwritten_images/relative_path\tannotation_text
```
Accompanied by a physical copy of the image under `base_dir/handwritten_images/`.
Source: `save_as_handwritten` (`frontend/src/annotations.py`).

### `.backups/metadata.json`
JSON with a `"backups"` key — a list of `{file, timestamp, operation, original}` objects, rotated down to `max_backups` entries (default 5).
Source: `BackupManager` (`frontend/src/backup.py`).

## Known fragile couplings

### Image cache coupling (`frontend/src/image_ops.py`)
`load_and_resize_image` is decorated with `@st.cache_data`. After saving a rotated file, `rotate_image` calls `load_and_resize_image.clear()`, which resets **the entire** cache for that function (not just the specific `image_path`), so the next render re-reads the file from disk instead of returning a stale cached preview. Both functions must live in the same module — if `load_and_resize_image` is ever duplicated or re-decorated elsewhere, `.clear()` stops working on the right cache instance, and rotated images will silently show a stale preview with no error in the logs.

### Hotkeys coupled to button text (`frontend/src/hotkeys.py` ↔ `frontend/src/ui/editor_view.py`)
The JS handler in `register_hotkeys` (`frontend/src/hotkeys.py`) finds navigation buttons purely by a literal match of the `←`/`→` characters in `btn.textContent` — it does not use `id`/`key`. Navigation buttons are created in `render_image_editor` (`frontend/src/ui/editor_view.py`, the `st.button("←", ...)` and `st.button("→", ...)` lines). If that button text changes even cosmetically (a space, an emoji), the hotkeys silently stop working — with no errors. This is exactly why these two glyphs stay hardcoded rather than going through `frontend/src/i18n.py`: they're language-independent by design, on purpose.
