# ADR-0003: Frontend and backend are two fully independent services

**Date**: 2026-08-18 (backfilled — date of the commit adding the OCR-consensus backend alongside the pre-existing frontend, plus the docker/tests commit that formalized the two-service split)
**Status**: accepted
**Deciders**: Vladislav Ershov

## Context

The labeling UI (`frontend/`) needs to run on any machine with lightweight dependencies (Streamlit, Pillow, requests) and package into a standalone `.exe`. The OCR-consensus engine (`backend/`) needs heavy ML dependencies (PaddleOCR, SuryaOCR, system Tesseract) that are neither installable inside a PyInstaller-bundled exe in a reasonable way nor desirable for users who only want manual labeling.

## Decision

Keep `frontend/` and `backend/` as two independent Python services with entirely separate `requirements.txt` files, no shared code, no shared process, and no direct import between them. They communicate only over HTTP (frontend calls backend via `CONSENSUS_BACKEND_URL`), and only when the user opts into "Авторазметка" (generation) mode. The backend is fully optional — manual labeling mode works without it running at all.

## Alternatives Considered

### Alternative 1: Single monolithic app (Streamlit process directly calls OCR engines)
- **Pros**: no HTTP layer, no job-polling UI, simpler for a user who only wants generation mode
- **Cons**: bundles PaddleOCR/SuryaOCR/Tesseract into the same process and dependency set as the labeling UI, defeating the ability to ship a lightweight standalone `.exe` for manual-only users; blocks the Streamlit UI thread during long-running OCR jobs unless significant async work is added
- **Why not**: the PyInstaller `.exe` packaging goal and the desire to keep manual-only usage dependency-light outweigh the simplicity of a single process

### Alternative 2: Shared library package imported by both services
- **Pros**: could deduplicate the `ImageRecord`-shaped output format between backend's `good.txt` writer and frontend's `AnnotationManager` reader
- **Cons**: introduces a versioning/packaging problem between two services deployed and updated independently (e.g., in separate Docker containers)
- **Why not**: the shared contract is small enough (a two-column text file format) that a shared package would add more process than it removes; the coupling is documented instead (see `docs/architecture.md`)

## Consequences

### Positive
- Frontend can be packaged as a standalone `.exe` without dragging in ML dependencies
- Manual labeling mode has zero dependency on the backend being installed, running, or even existing on the machine
- Each service can be developed, tested, and deployed on its own cadence (separate Dockerfiles, separate test suites)

### Negative
- Any change to the backend's output file format (`good.txt`/`needs_review.txt`) must be manually kept in sync with the frontend's `_build_manager_from_output` parser — no compiler or shared type catches drift (see ADR-0001)
- Running full generation-mode functionality requires the user to have both services running, which is one more moving part than a monolith

### Risks
- **Silent format drift between the two services** — mitigated only by documentation (`docs/architecture.md`, `docs/CODEMAPS/data.md`); no automated contract test exists across the service boundary today
