# ADR-0001: Flat files over a database for annotation and job state

**Date**: 2026-08-18 (backfilled — original decision predates ADR tracking; date is the commit that split `app1.py` into the current `frontend/src/` package and established the file-based data model)
**Status**: accepted
**Deciders**: Vladislav Ershov

## Context

The frontend is a single-user Streamlit labeling tool; the backend is a local, single-user OCR-consensus spike. Both need to persist annotation records, marked/reviewed status, and backup history, but there is no multi-user access, no concurrent-write requirement, and no deployment target beyond a local machine or a single Docker container with a mounted volume.

## Decision

Persist all state as flat files on disk: `rec.txt`/`status_cache.txt`/`handwritten.txt`/`.backups/metadata.json` on the frontend side, `good.txt`/`needs_review.txt`/`crops/*.webp` on the backend side. No database of any kind is used anywhere in the project.

## Alternatives Considered

### Alternative 1: SQLite
- **Pros**: transactional writes, queryable, still zero-infrastructure
- **Cons**: adds a schema/migration surface, a new dependency, and a binary file format that's harder to inspect/edit by hand than the current plain-text formats
- **Why not**: single-user, low-volume labeling workflow doesn't need transactions or queries; plain text is easier to diff, hand-edit, and reason about for this use case

### Alternative 2: Full RDBMS (Postgres/MySQL)
- **Pros**: robust, supports future multi-user access
- **Cons**: requires running a server process, connection config, and ORM/migration tooling for a tool that runs as a standalone local app or single container
- **Why not**: massive operational overkill for a local labeling tool with no concurrent users

## Consequences

### Positive
- Zero infrastructure — the app runs by just having Python installed, no DB server to provision
- Data files are human-readable and can be inspected/edited/diffed directly
- Trivial to back up (`BackupManager` just copies files) and trivial to hand off between frontend and backend (backend writes `good.txt`/`needs_review.txt`, frontend reads them directly)

### Negative
- No transactional guarantees — a crash mid-write can leave a file in an inconsistent state
- No schema enforcement — malformed rows are silently skipped or mis-parsed rather than rejected
- Formats are coupled by convention, not by a shared schema — see `docs/architecture.md` "Известные хрупкие места" for the coupling risks this creates

### Risks
- **Multi-user or concurrent-write scenario would break this model** — mitigated by keeping the tool explicitly single-user/local; if that ever changes, this decision should be revisited (see ADR-0002 for the related no-auth decision)
