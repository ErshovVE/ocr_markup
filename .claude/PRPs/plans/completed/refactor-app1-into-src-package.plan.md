# Plan: Refactor app1.py into a src/ package (Phases 1-4)

## Summary
Archive the dead `app.py`, then split the 823-line `app1.py` monolith into a documented `src/` package (`models.py`, `backup.py`, `annotations.py`, `ui/list_view.py`, `ui/editor_view.py`, `ui/sidebar.py`, `hotkeys.py`), leaving `app1.py` as a thin entry point that only initializes session state and wires the pieces together. Finish with a documentation pass covering the module map, the on-disk data formats, and the two known fragile couplings. This is Track A of the PRD (`.claude/PRPs/prds/ocr-markup-v2.prd.md`) — Phases 1-4 — and covers only the refactor, not Track B (OCR consensus backend) or the manual regression click-through (Phase 5), which is a separate follow-up plan.

## User Story
As the sole maintainer of this labeling tool, I want the code split into clear module boundaries with the module layout and data formats documented, so I can add new features later without fear of breaking unrelated parts of the app.

## Problem → Solution
Today: two diverged entry points (`app.py` abandoned, `app1.py` live) and all logic — UI rendering, session-state management, file I/O, backups, image ops — packed into one file with no boundaries or docs.
After: `app.py` is archived and clearly marked as dead; `app1.py` is a short entry point; data/backup/annotation logic lives in `src/`; UI rendering lives in `src/ui/`; a doc explains the layout, the `rec.txt`/`status_cache.txt`/`handwritten.txt` formats, and the two fragile couplings that must survive future edits.

## Metadata
- **Complexity**: Medium (7 files touched: 1 archive move, 1 new entry point, 6 new `src/` files, 1 new doc)
- **Source PRD**: `.claude/PRPs/prds/ocr-markup-v2.prd.md`
- **PRD Phase**: Phases 1, 2, 3, 4 (combined into one plan per user request)
- **Estimated Files**: 9 (1 moved, 1 rewritten, 6 created, 1 doc created)

---

## UX Design

### Before
N/A — this is a pure internal refactor. The Streamlit UI, session-state behavior, hotkeys, and file formats must be pixel-for-pixel identical after the split. No user-facing change is in scope for Phases 1-4 (behavioral verification itself is Phase 5, out of scope for this plan).

### After
N/A — same as above.

### Interaction Changes
| Touchpoint | Before | After | Notes |
|---|---|---|---|
| Which file to run | `app.py` or `app1.py` (ambiguous) | Only `app1.py`, documented as the sole entry point | `app.py` moved to `legacy/app.py`, README updated |
| Everything else | — | — | No behavior changes; this plan is structure-only |

---

## Mandatory Reading

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | `app1.py` | 1-824 | Entire file to be split; every symbol below is extracted from here |
| P0 | `app1.py` | 66-161 | `BackupManager` — moves to `src/backup.py` verbatim |
| P0 | `app1.py` | 164-171 | `ImageRecord` dataclass — moves to `src/models.py` verbatim |
| P0 | `app1.py` | 174-321 | `AnnotationManager` — moves to `src/annotations.py`; depends on `BackupManager` |
| P0 | `app1.py` | 324-353 | `load_and_resize_image` + `rotate_image` — the fragile cache-clear coupling (see GOTCHA below); moves to `src/image_ops.py` |
| P0 | `app1.py` | 15-63 | `register_hotkeys` — JS hotkey injection tied to exact button text `←`/`→`; moves to `src/hotkeys.py` |
| P0 | `app1.py` | 356-389 | `save_as_handwritten` — depends on `AnnotationManager`; moves to `src/annotations.py` (it operates on `manager.records`/`manager.base_dir`, same module as `AnnotationManager`) |
| P0 | `app1.py` | 392-414 | `init_session_state` / `check_hotkeys` — stays in `app1.py` (entry-point responsibility per PRD) |
| P0 | `app1.py` | 416-499 | `render_image_list` — moves to `src/ui/list_view.py` |
| P0 | `app1.py` | 502-669 | `render_image_editor` — moves to `src/ui/editor_view.py`; calls `register_hotkeys`, `rotate_image`, `save_as_handwritten` |
| P0 | `app1.py` | 672-823 | `main()` — CSS block + upload/manager-init logic stays in `app1.py`; sidebar block (749-819) moves to `src/ui/sidebar.py` |
| P1 | `app.py` | 1-80+ | Confirm no unique logic beyond what's in `app1.py` before archiving (already spot-checked below) |
| P1 | `README.md` | 1-19 | Currently documents `app.py` as the entry point — must be updated to `app1.py` |
| P1 | `CLAUDE.md` | all | Already documents `app1.py` as the live file and lists a `src/` layout as *not yet present* — must be updated once `src/` exists |
| P2 | `predict.py` | 1-134 | Reference only — shares the `rec.txt`-style `path\ttext` format that `src/annotations.py` must keep producing (relevant for Phase 4 docs, not for behavior) |

## External Documentation
No external research needed — feature uses established internal patterns (Streamlit session state, dataclasses, pathlib). This is a pure code-organization task with no new dependencies.

---

## Patterns to Mirror

### NAMING_CONVENTION
// SOURCE: app1.py (whole file)
- Module-level functions: `snake_case` (`register_hotkeys`, `load_and_resize_image`, `rotate_image`, `save_as_handwritten`, `init_session_state`, `render_image_list`, `render_image_editor`, `main`)
- Classes: `PascalCase` (`BackupManager`, `ImageRecord`, `AnnotationManager`)
- Docstrings: one-line Russian imperative/descriptive strings immediately under `def`/`class`, e.g. `"""Управление резервными копиями с ротацией"""` — preserve this convention in every moved symbol, do not translate to English or add multi-line docstrings.
- No type-annotation style change: `app1.py` already uses `Dict`, `List`, `Set`, `Tuple`, `Optional` from `typing` (not `dict`/`list` builtins or `|` unions) — keep this exact style when moving code; do not "modernize" annotations as part of this refactor (out of scope, see NOT Building).

### ERROR_HANDLING
// SOURCE: app1.py:123-125, 153-155, 219-220, 267-269, 311-312, 337-339, 351-353, 387-389
```python
try:
    ...
except Exception as e:
    st.error(f"Ошибка ...: {e}")
    return None  # or False, or (False, "...")
```
Every I/O operation in `BackupManager`/`AnnotationManager`/image ops wraps in broad `try/except Exception` and surfaces via `st.error`/`st.info` directly — this is a deliberate decision recorded in the PRD's Technical Approach ("these stay as-is rather than being purified... decoupling Streamlit calls from the model layer is not required"). Do NOT refactor these into raised exceptions or a separate error-reporting layer during Phases 1-4.

### STATE_ACCESS_PATTERN
// SOURCE: app1.py:392-407, 438-442, 466-472, etc.
```python
if key not in st.session_state:
    st.session_state[key] = value
...
st.session_state.current_idx = global_idx
st.rerun()
```
`st.session_state` is read/written directly by attribute or key access throughout UI functions — no wrapper/accessor class exists and none should be introduced (would be an unrequested abstraction). Keep this pattern identical when moving `render_image_list`/`render_image_editor`/sidebar code into `src/ui/`.

### CACHE_INVALIDATION_COUPLING (fragile — must be preserved)
// SOURCE: app1.py:324-353
```python
@st.cache_data
def load_and_resize_image(image_path: str, max_height: int = 100, max_width: int = 1000):
    ...

def rotate_image(image_path: str, direction: str) -> bool:
    ...
    rotated.save(image_path)
    load_and_resize_image.clear()   # <-- clears the ENTIRE cache, not just this image_path
    return True
```
`rotate_image` calls `load_and_resize_image.clear()` (a `@st.cache_data`-decorated function's `.clear()` method) after saving the rotated file, so the next render re-reads the file from disk instead of serving a stale cached thumbnail. Both functions must live in the same module (`src/image_ops.py`) and `rotate_image` must keep importing/calling the exact same decorated function object — if `load_and_resize_image` is duplicated or re-decorated in two places, the cache-clear becomes a no-op for the wrong cache instance.

### HOTKEY_BUTTON_TEXT_COUPLING (fragile — must be preserved)
// SOURCE: app1.py:36-53, 626, 638
```javascript
if (btn.textContent.includes('←') && !btn.disabled) { btn.click(); }
...
if (btn.textContent.includes('→') && !btn.disabled) { btn.click(); }
```
matched against the actual Streamlit buttons:
```python
if st.button("←", ..., disabled=prev_disabled, key=f"prev_{current_name}", ...):
if st.button("→", ..., disabled=next_disabled, key=f"next_{current_name}", ...):
```
The JS in `register_hotkeys` (moving to `src/hotkeys.py`) finds nav buttons purely by matching the literal `←`/`→` characters in `btn.textContent` — there is no `id`/`key`-based lookup. If `render_image_editor`'s button labels in `src/ui/editor_view.py` change even cosmetically (e.g. adding a space, wrapping in an emoji, translating), the hotkeys silently stop working with no error. Call this out explicitly in both the code (a comment at the `register_hotkeys` call site referencing the button labels) and Phase 4's documentation.

### CALL_GRAPH (for wiring after the split)
// SOURCE: app1.py:502-669, 672-823
```
app1.py:main()
  ├─ init_session_state()                         [stays in app1.py]
  ├─ AnnotationManager(...)                        [src/annotations.py]
  │    └─ BackupManager(...)                       [src/backup.py]
  ├─ manager.get_image_list(...)                   [src/annotations.py]
  ├─ render_image_list(manager, filtered)          [src/ui/list_view.py]
  ├─ render_image_editor(manager)                  [src/ui/editor_view.py]
  │    ├─ load_and_resize_image(...)                [src/image_ops.py]
  │    ├─ rotate_image(...)                         [src/image_ops.py]
  │    ├─ save_as_handwritten(manager, ...)         [src/annotations.py]
  │    └─ register_hotkeys()                        [src/hotkeys.py]
  └─ sidebar block (stats, save-all, backups list)  [src/ui/sidebar.py]
       └─ manager.backup_manager.get_backups_list() / restore_backup()  [src/backup.py]
```

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `app.py` | MOVE → `legacy/app.py` | Phase 1: archive with no functional migration (PRD confirms no unique logic) |
| `README.md` | UPDATE | Phase 1: change run instructions from `app.py` to `app1.py`; note `app.py` is archived under `legacy/` |
| `src/__init__.py` | CREATE (empty) | Make `src/` an importable package |
| `src/models.py` | CREATE | Phase 2: `ImageRecord` dataclass, moved verbatim from `app1.py:164-171` |
| `src/backup.py` | CREATE | Phase 2: `BackupManager`, moved verbatim from `app1.py:66-161`; imports `streamlit as st` for `st.error` (kept per PRD decision) |
| `src/annotations.py` | CREATE | Phase 2: `AnnotationManager` (`app1.py:174-321`) + `save_as_handwritten` (`app1.py:356-389`); imports `ImageRecord` from `src/models.py`, `BackupManager` from `src/backup.py` |
| `src/image_ops.py` | CREATE | Phase 2/3 boundary: `load_and_resize_image` + `rotate_image` (`app1.py:324-353`) — grouped together to preserve the cache-clear coupling |
| `src/hotkeys.py` | CREATE | Phase 3: `register_hotkeys` (`app1.py:15-63`), unchanged |
| `src/ui/__init__.py` | CREATE (empty) | Make `src/ui/` an importable package |
| `src/ui/list_view.py` | CREATE | Phase 3: `render_image_list` (`app1.py:416-499`), unchanged logic |
| `src/ui/editor_view.py` | CREATE | Phase 3: `render_image_editor` (`app1.py:502-669`), imports `load_and_resize_image`/`rotate_image` from `src/image_ops.py`, `save_as_handwritten` from `src/annotations.py`, `register_hotkeys` from `src/hotkeys.py` |
| `src/ui/sidebar.py` | CREATE | Phase 3: sidebar block (`app1.py:748-819`), extracted into a `render_sidebar(manager)` function |
| `app1.py` | REWRITE | Phase 3: shrinks to `st.set_page_config`, CSS block, `init_session_state`, upload/working-dir/manager-init logic, and calls into `src/` — target ~120-150 lines (from 824) |
| `docs/architecture.md` | CREATE | Phase 4: module map, data model, fragile-coupling call-outs |
| `CLAUDE.md` | UPDATE | Phase 4: reflect the new `src/` layout (currently says "no `src/` layout") and point to `docs/architecture.md` |

## NOT Building
- No behavior changes to any flow (upload, edit, save, rotate, delete, backup/restore, hotkeys, handwritten export) — this plan is structure-only
- No manual regression click-through execution (that is PRD Phase 5, a separate plan/step, though this plan's Task list ends with a self-check pass)
- No migration of any `app.py`-only functionality (confirmed none exists beyond what `app1.py` already covers)
- No decoupling of `st.error`/`st.info` calls out of `BackupManager`/`AnnotationManager` (explicit PRD decision — out of scope)
- No type-annotation modernization (`Dict`→`dict`, `Optional[X]`→`X | None`) — preserve existing style exactly
- No new tests/test framework (none exists in this repo; not requested for these phases)
- No Track B (OCR consensus backend) work — entirely separate, unrelated code path

---

## Step-by-Step Tasks

### Task 1: Archive app.py
- **ACTION**: Create a `legacy/` directory and move `app.py` into it.
- **IMPLEMENT**:
  ```
  mkdir legacy
  git mv app.py legacy/app.py
  ```
- **MIRROR**: N/A (file move, no code pattern)
- **IMPORTS**: N/A
- **GOTCHA**: `wrapper.py` and `pyinst_command.txt` currently reference `app.py` as the bundled file for the PyInstaller build (`resource_path("app.py")` in `wrapper.py:18`, `--add-data "app.py;."` in `pyinst_command.txt`). These are **out of scope** for Phases 1-4 per the PRD (the exe build target isn't mentioned in Phase 1's scope), but leaving them pointing at a now-archived file will silently break the next `.exe` build. Add a one-line note in `docs/architecture.md` (Task 9) flagging that `wrapper.py`/`pyinst_command.txt` still reference the old `app.py` path and need updating in a future pass — do not silently fix or silently ignore.
- **VALIDATE**: `git status` shows `app.py` renamed to `legacy/app.py`; `Test-Path legacy/app.py` is true; `Test-Path app.py` is false.

### Task 2: Update README.md to point at app1.py
- **ACTION**: Edit the "Установка и запуск" section.
- **IMPLEMENT**: Change step 3 from `streamlit run app.py --server.enableXsrfProtection=false` to `streamlit run app1.py --server.enableXsrfProtection=false`. Add a line noting `app.py` is archived in `legacy/` for reference only.
- **MIRROR**: Keep the existing Russian-language style and Markdown structure of `README.md` exactly.
- **IMPORTS**: N/A
- **GOTCHA**: Don't touch the "Возможности" feature list — it still accurately describes `app1.py`'s behavior (upload, edit, navigate, save); no need to expand it with hotkeys/rotation/backups here (that's Phase 4's `docs/architecture.md` job, not the top-level README's).
- **VALIDATE**: `README.md` no longer contains the string `run app.py`; contains `run app1.py`.

### Task 3: Create src/models.py
- **ACTION**: Create `src/__init__.py` (empty) and `src/models.py`.
- **IMPLEMENT**: Move the `ImageRecord` dataclass verbatim from `app1.py:164-171`, including its docstring. Add only the imports it needs: `from dataclasses import dataclass`.
  ```python
  from dataclasses import dataclass


  @dataclass
  class ImageRecord:
      """Структура данных для одной записи изображения"""

      relative_path: str
      absolute_path: str
      annotation: str
      is_marked: bool = False
  ```
- **MIRROR**: NAMING_CONVENTION pattern above — keep the Russian docstring unchanged, no added type-hint modernization.
- **IMPORTS**: `from dataclasses import dataclass`
- **GOTCHA**: Do not add `frozen=True` — `AnnotationManager.update_annotation` (app1.py:246-251) mutates `record.annotation` and `record.is_marked` in place; freezing the dataclass would break that call site. (This intentionally deviates from the user's global Python style preference for frozen dataclasses — the existing codebase relies on mutability here, and preserving behavior takes priority over that preference for this refactor.)
- **VALIDATE**: `python -c "from src.models import ImageRecord; r = ImageRecord('a','b','c'); print(r)"` runs without error.

### Task 4: Create src/backup.py
- **ACTION**: Create `src/backup.py`.
- **IMPLEMENT**: Move `BackupManager` verbatim from `app1.py:66-161`, including all docstrings and the `st.error` call inside `restore_backup`.
- **MIRROR**: ERROR_HANDLING pattern above — keep every `try/except Exception as e: st.error(...)` block exactly as-is.
- **IMPORTS**:
  ```python
  import json
  import shutil
  from datetime import datetime
  from pathlib import Path
  from typing import Dict, List, Optional
  import streamlit as st
  ```
- **GOTCHA**: `BackupManager.__init__` calls `self.backup_dir.mkdir(exist_ok=True)` — this has a side effect (creates `.backups/` on disk) the moment a `BackupManager` is constructed, not lazily. Preserve this exact ordering; do not defer directory creation, since `AnnotationManager.__init__` (Task 5) depends on this happening eagerly.
- **VALIDATE**: `python -c "from src.backup import BackupManager"` runs without error (no circular import).

### Task 5: Create src/image_ops.py
- **ACTION**: Create `src/image_ops.py`.
- **IMPLEMENT**: Move `load_and_resize_image` and `rotate_image` together, verbatim, from `app1.py:324-353`.
- **MIRROR**: CACHE_INVALIDATION_COUPLING pattern above — both functions MUST be in this one module so `rotate_image`'s `load_and_resize_image.clear()` call refers to the same decorated function object used by the UI layer.
- **IMPORTS**:
  ```python
  import streamlit as st
  from PIL import Image
  ```
- **GOTCHA**: This is the single most fragile extraction in the whole refactor. If `src/ui/editor_view.py` (Task 8) imports `load_and_resize_image` from anywhere other than `src.image_ops`, or if any code re-applies `@st.cache_data` to a second copy of the function, `rotate_image`'s cache-clear becomes silently ineffective (rotated images will keep showing the stale cached thumbnail until a full app restart). Add a one-line comment above `rotate_image` in the new file: `# NOTE: load_and_resize_image.clear() only works because both functions live in this module — see docs/architecture.md`.
- **VALIDATE**: `python -c "from src.image_ops import load_and_resize_image, rotate_image; print(load_and_resize_image.clear)"` runs and prints the cache `.clear` method without error.

### Task 6: Create src/annotations.py
- **ACTION**: Create `src/annotations.py`.
- **IMPLEMENT**: Move `AnnotationManager` (`app1.py:174-321`) and `save_as_handwritten` (`app1.py:356-389`) into this module, verbatim.
- **MIRROR**: ERROR_HANDLING pattern (broad try/except + `st.error`/`st.info`), STATE_ACCESS_PATTERN is not used here (this is the model layer, no `st.session_state` reads) — confirm no `st.session_state` references exist in either symbol before finalizing (there are none in the source).
- **IMPORTS**:
  ```python
  import os
  import shutil
  from pathlib import Path
  from typing import Dict, List, Optional, Set, Tuple
  import streamlit as st
  from src.backup import BackupManager
  from src.models import ImageRecord
  ```
- **GOTCHA**: `AnnotationManager.__init__` constructs `self.backup_manager = BackupManager(self.base_dir)` (app1.py:183) — keep this composition as-is; do not inject `BackupManager` as a constructor parameter (that would be an unrequested API change / scope creep beyond "move code, preserve behavior").
- **VALIDATE**: `python -c "from src.annotations import AnnotationManager, save_as_handwritten"` runs without error.

### Task 7: Create src/hotkeys.py
- **ACTION**: Create `src/hotkeys.py`.
- **IMPLEMENT**: Move `register_hotkeys` verbatim from `app1.py:15-63`, including the full JS string.
- **MIRROR**: HOTKEY_BUTTON_TEXT_COUPLING pattern above.
- **IMPORTS**:
  ```python
  from streamlit.components.v1 import html
  ```
- **GOTCHA**: Add a module-level comment at the top of the file: `# JS below matches Streamlit nav buttons by literal '←'/'→' text in editor_view.py — keep button labels unchanged or hotkeys silently break.` This is the single most important call-out for Phase 4 to also document.
- **VALIDATE**: `python -c "from src.hotkeys import register_hotkeys"` runs without error.

### Task 8: Create src/ui/ package (list_view, editor_view, sidebar)
- **ACTION**: Create `src/ui/__init__.py` (empty), `src/ui/list_view.py`, `src/ui/editor_view.py`, `src/ui/sidebar.py`.
- **IMPLEMENT**:
  - `src/ui/list_view.py`: move `render_image_list` verbatim from `app1.py:416-499`.
  - `src/ui/editor_view.py`: move `render_image_editor` verbatim from `app1.py:502-669`, updating its internal calls to use the new imports (`load_and_resize_image`, `rotate_image` from `src.image_ops`; `save_as_handwritten` from `src.annotations`; `register_hotkeys` from `src.hotkeys`).
  - `src/ui/sidebar.py`: extract the sidebar block currently inline in `main()` (`app1.py:748-819`) into a new function:
    ```python
    def render_sidebar(manager):
        """Отрисовывает сайдбар: статистика, сохранение, управление бэкапами"""
        # body = app1.py:749-819, unchanged logic
    ```
- **MIRROR**: STATE_ACCESS_PATTERN — `render_image_list`/`render_image_editor`/`render_sidebar` all continue reading/writing `st.session_state` directly by attribute, exactly as in the source.
- **IMPORTS** (per file):
  - `list_view.py`: `import streamlit as st`; type hint needs `from typing import List` and `from src.annotations import AnnotationManager` (for the type-hinted parameter).
  - `editor_view.py`: `import streamlit as st`; `from src.annotations import AnnotationManager, save_as_handwritten`; `from src.image_ops import load_and_resize_image, rotate_image`; `from src.hotkeys import register_hotkeys`.
  - `sidebar.py`: `import streamlit as st`; `from datetime import datetime` (used for `backup["timestamp"]` formatting, app1.py:795-797); `from src.annotations import AnnotationManager`.
- **GOTCHA**: The sidebar block references `manager.backup_manager.get_backups_list()` and `manager.backup_manager.restore_backup(...)` (app1.py:778, 811) — `render_sidebar` must take `manager: AnnotationManager` as its sole parameter (matching `render_image_list(manager, filtered_images)`'s existing signature style), not reach into `st.session_state.manager` itself, to keep the "who owns state" boundary consistent with the other two `render_*` functions.
- **VALIDATE**: `python -c "from src.ui.list_view import render_image_list; from src.ui.editor_view import render_image_editor; from src.ui.sidebar import render_sidebar"` runs without error.

### Task 9: Rewrite app1.py as the thin entry point
- **ACTION**: Replace `app1.py`'s body, keeping only what the PRD scopes to the entry point.
- **IMPLEMENT**: Final `app1.py` should contain, in order:
  1. Imports: `streamlit as st`, `os`, plus `from src.annotations import AnnotationManager`, `from src.ui.list_view import render_image_list`, `from src.ui.editor_view import render_image_editor`, `from src.ui.sidebar import render_sidebar`.
  2. `st.set_page_config(...)` (app1.py:12, unchanged).
  3. `init_session_state()` (app1.py:392-407, unchanged — stays here per PRD Phase 3 scope: "`app1.py` becoming a thin app1.py that just wires session-state init + calls into src/").
  4. `check_hotkeys()` (app1.py:410-413) — currently a no-op `pass`; keep it as-is (do not delete a dead function as unrequested cleanup; do not expand it either).
  5. `main()`: the CSS block (app1.py:674-687), title, file-uploader/working-dir/manager-init logic (app1.py:694-722) stay inline in `main()`; then calls `render_image_list(manager, filtered)`, `render_image_editor(manager)`, `render_sidebar(manager)` in place of the old inline blocks.
  6. `if __name__ == "__main__": main()` (unchanged).
- **MIRROR**: CALL_GRAPH pattern above for the exact wiring order.
- **IMPORTS**: as listed in step 1.
- **GOTCHA**: `manager = st.session_state.manager` (app1.py:722) must still be defined in `main()` before being passed to the three `render_*` calls — don't have `render_sidebar`/others read `st.session_state.manager` themselves, since `render_image_list`/`render_image_editor` already take `manager` as an explicit parameter and consistency matters more than saving one line.
- **VALIDATE**: `streamlit run app1.py --server.enableXsrfProtection=false` starts without a traceback (import-time errors will surface immediately in the Streamlit console); manually confirm the resulting `app1.py` is roughly 120-150 lines (down from 824), matching the PRD's Phase 3 success signal ("`app1.py` is short (roughly entry-point-sized)").

### Task 10: Write docs/architecture.md (Phase 4)
- **ACTION**: Create `docs/architecture.md`.
- **IMPLEMENT**: Structure the doc with these sections (Russian, matching the codebase's language convention):
  1. **Карта модулей** (module map) — one line per file in `src/` naming its single responsibility, mirroring the "Files to Change" table above.
  2. **Формат данных** (data formats) — document three files precisely from what's observed in code:
     - `rec.txt` / uploaded annotation file: tab-separated `relative_path\tannotation_text` per line, one line per image (source: `AnnotationManager.load_from_file`, `app1.py:185-220`; `AnnotationManager.save_changes`, `app1.py:277-312`).
     - `status_cache.txt`: one image filename (not path) per line, listing images where `is_marked=True`; located at `base_dir/<first_path_segment>/status_cache.txt`, derived from the first directory component of the first loaded record's relative path (source: `AnnotationManager._load_status_cache`, `app1.py:222-244`).
     - `handwritten.txt`: tab-separated `handwritten_images/<relative_path>\tannotation_text`, append-only with duplicate-line detection; paired with a physical copy of the image under `base_dir/handwritten_images/` (source: `save_as_handwritten`, `app1.py:356-389`).
     - `.backups/metadata.json`: JSON with a `"backups"` list of `{file, timestamp, operation, original}` objects, rotated to `max_backups` (default 5) entries (source: `BackupManager`, `app1.py:66-161`).
  3. **Известные хрупкие места** (known fragile couplings) — reproduce the CACHE_INVALIDATION_COUPLING and HOTKEY_BUTTON_TEXT_COUPLING sections above verbatim as prose, each with its file:line source reference into the new `src/` locations (not the old `app1.py` line numbers, since those are moving).
  4. **Внимание** (heads-up) note: `wrapper.py` / `pyinst_command.txt` still reference the archived `legacy/app.py` path for the PyInstaller build and need updating before the next `.exe` build (carried over from Task 1's GOTCHA).
- **MIRROR**: Match the Russian-language documentation convention already used in code docstrings and `README.md`.
- **IMPORTS**: N/A (Markdown file)
- **GOTCHA**: Do not invent formats not observed in code — every claim in section 2 must trace to an actual line in the (now-moved) source, per the plan's "Pattern Faithfulness" requirement. Update file:line references to point at the new `src/` paths, not the old `app1.py` numbers.
- **VALIDATE**: A reader with no prior context on this repo should be able to answer, from this doc alone: "which file owns backups?", "what does status_cache.txt contain?", and "why can't I rename the ← button?".

### Task 11: Update CLAUDE.md to reflect the new layout
- **ACTION**: Edit `CLAUDE.md`'s "Code Style" and "Project Structure" sections.
- **IMPLEMENT**: 
  - In "Code Style", remove/revise the line "Flat, single-file scripts — no package/module structure, no `src/` layout" since this is no longer true after Task 3-9.
  - In "Project Structure", add entries for `src/models.py`, `src/backup.py`, `src/annotations.py`, `src/image_ops.py`, `src/hotkeys.py`, `src/ui/list_view.py`, `src/ui/editor_view.py`, `src/ui/sidebar.py`, `legacy/app.py`, and `docs/architecture.md`, each with a one-line responsibility matching Task 10's module map.
  - Update "Build & Run" if it references `app.py` anywhere (it currently mentions both `app.py` and `app1.py` — clarify `app.py` now lives at `legacy/app.py` and is not runnable as documented).
- **MIRROR**: Keep `CLAUDE.md`'s existing terse, bullet-per-fact style; don't restructure sections that remain accurate (e.g., "Data model" description of `rec.txt`/`status_cache.txt` stays, just point to `docs/architecture.md` for detail instead of duplicating it).
- **IMPORTS**: N/A
- **GOTCHA**: `CLAUDE.md` is loaded into every future Claude Code session for this repo — an inaccurate `CLAUDE.md` after this refactor is worse than no update, since it will actively mislead future work. This task is not optional polish.
- **VALIDATE**: `CLAUDE.md` no longer states "no package/module structure, no src/ layout"; it accurately lists every new `src/` file.

---

## Testing Strategy

No automated test suite exists in this repo (confirmed in `CLAUDE.md` and by absence of any `test_*.py`/`pytest.ini`/`tox.ini` file), and none is being introduced in Phases 1-4 — the PRD's stated regression safety net for this refactor is manual click-through (Phase 5, a separate follow-up, not part of this plan). This plan's own verification is limited to:

### Unit Tests
N/A — none exist; not introduced here.

### Edge Cases Checklist
Not applicable in the traditional sense (no runtime logic changes), but confirm during the split:
- [ ] No circular imports between `src/annotations.py` ↔ `src/backup.py` ↔ `src/models.py` (import chain is one-directional: `annotations` → `backup`, `annotations` → `models`)
- [ ] No circular imports between `src/ui/*.py` and `app1.py` (UI modules never import from `app1.py`; only `app1.py` imports from `src/ui/*`)
- [ ] `load_and_resize_image` and `rotate_image` remain in the same module (Task 5 GOTCHA)
- [ ] Button label text (`←`/`→`) in `src/ui/editor_view.py` is byte-identical to the source (Task 7/8 GOTCHA)
- [ ] `app1.py` after rewrite still contains exactly one `st.set_page_config` call (Streamlit errors if called twice or after other st.* calls)

---

## Validation Commands

### Static Analysis
```powershell
python -m py_compile src/models.py src/backup.py src/annotations.py src/image_ops.py src/hotkeys.py src/ui/list_view.py src/ui/editor_view.py src/ui/sidebar.py app1.py
```
EXPECT: No syntax errors (no lint/type-check tooling configured in this repo, per `CLAUDE.md`)

### Import Smoke Test
```powershell
python -c "from src.models import ImageRecord; from src.backup import BackupManager; from src.annotations import AnnotationManager, save_as_handwritten; from src.image_ops import load_and_resize_image, rotate_image; from src.hotkeys import register_hotkeys; from src.ui.list_view import render_image_list; from src.ui.editor_view import render_image_editor; from src.ui.sidebar import render_sidebar; print('OK')"
```
EXPECT: Prints `OK` with no ImportError/circular-import traceback

### Unit Tests
N/A — no test suite in this repo.

### Full Test Suite
N/A — no test suite in this repo.

### Database Validation
N/A — no database in this project.

### Browser Validation
```powershell
streamlit run app1.py --server.enableXsrfProtection=false
```
EXPECT: App loads at `localhost:8501` with the file-uploader visible and no traceback in the terminal or browser

### Manual Validation
- [ ] Upload a real `rec.txt`-style file and a working directory — confirm the image list and editor render exactly as before
- [ ] Edit one annotation and submit — confirm autosave-at-10 counter and save behavior match pre-refactor (full flow-by-flow verification is PRD Phase 5, out of scope here, but a quick smoke check here catches obvious wiring mistakes before handing off)
- [ ] Rotate an image and confirm the thumbnail updates immediately (validates the cache-clear coupling survived the split)
- [ ] Press ← / → arrow keys while not focused in a text field and confirm navigation still works (validates the hotkey/button-text coupling survived the split)
- [ ] Open the sidebar, confirm stats/save-all/backup-list/restore all render and function

---

## Acceptance Criteria
- [ ] All 11 tasks completed
- [ ] All validation commands pass
- [ ] No automated tests exist to write (confirmed — not a gap, a repo characteristic)
- [ ] No type errors (no type checker configured; `py_compile` passes)
- [ ] No lint errors (no linter configured)
- [ ] N/A — no UX design change to match

## Completion Checklist
- [ ] Code follows discovered patterns (naming, error handling, session-state access)
- [ ] Error handling matches codebase style (broad try/except + st.error/st.info, unchanged)
- [ ] N/A — no test patterns to follow (none exist)
- [ ] No hardcoded values introduced beyond what already existed
- [ ] `docs/architecture.md` and `CLAUDE.md` updated
- [ ] No unnecessary scope additions (no new abstractions, no dependency injection, no type-hint modernization, no dead-code deletion beyond the app.py move)
- [ ] Self-contained — no questions needed during implementation

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Cache-clear coupling (Task 5) breaks silently if `load_and_resize_image` ends up duplicated or re-imported into two modules | M | High — rotated images show stale thumbnails with no error | Both functions live in one file (`src/image_ops.py`); import smoke test confirms single definition; manual rotate check in Validation Commands |
| Hotkey/button-text coupling (Task 7/8) breaks silently if button labels drift during the move | M | Medium — arrow-key nav stops working with no error, easy to miss without testing | Verbatim move, no relabeling; manual hotkey check in Validation Commands; documented prominently in `docs/architecture.md` |
| Circular imports between `src/annotations.py`, `src/backup.py`, `src/models.py` | L | High — app fails to start entirely | Import direction is fixed one-way (`annotations` depends on `backup`+`models`, neither depends back); import smoke test catches this immediately |
| `wrapper.py`/`pyinst_command.txt` silently break for the next `.exe` build since they still point at the now-archived `app.py` | M | Low for this plan's scope (build isn't run during Phases 1-4) but High if unnoticed later | Explicitly flagged in Task 1 and Task 10 rather than silently fixed or silently ignored — left as documented follow-up, since fixing the PyInstaller path is outside this PRD phase's stated scope |
| Manual regression click-through (PRD Phase 5) is a separate step not covered by this plan | N/A | High if skipped entirely | This plan's own Manual Validation section does a lightweight smoke pass; full click-through remains a required follow-up before calling Track A "done" per the PRD |

## Notes
- Phases 5 (manual regression click-through) is explicitly the next PRD phase after this plan and depends on Phase 3 (Task 9 here) — it is intentionally excluded from this plan's scope per the user's request for "the first 4 phases," but the Risks table above flags it so it isn't forgotten.
- `src/ui/sidebar.py`'s `render_sidebar` function name and signature (`render_sidebar(manager)`) are new — the PRD names this module "newly named — currently inline in `main()`" (PRD Phase 3 scope line), so introducing a name here is expected and within scope, not an unrequested abstraction.
- This plan deliberately does not touch Track B (OCR consensus backend, PRD Phases 6-9) — confirmed no overlap in files touched.
