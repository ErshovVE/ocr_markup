# ADR-0002: Backend runs without authentication as a local single-user spike

**Date**: 2026-08-18 (backfilled — date of the commit that introduced `backend/main.py` as "OCR consensus backend spike")
**Status**: accepted
**Deciders**: Vladislav Ershov

## Context

`backend/main.py` exposes `POST /run` accepting arbitrary `input_dir`/`output_dir` paths, and `GET /result/{job_id}` etc., with no authentication or path validation. The service is explicitly described as a spike intended to run on `127.0.0.1` for a single local user, not as a hosted multi-tenant service.

## Decision

Ship the backend with no authentication layer and no restriction on which filesystem paths `input_dir`/`output_dir` may point to, on the condition that it only ever binds to `127.0.0.1` (or, in Docker, is only reachable within the compose network) and is never exposed on a shared or multi-user machine.

## Alternatives Considered

### Alternative 1: API key / token auth
- **Pros**: standard mitigation against unauthorized access if the port is ever exposed
- **Cons**: adds a secret to manage for a tool with exactly one user, on one machine, for a spike whose scope may not survive
- **Why not**: no threat model requires it yet — the risk is bind-address exposure, not credential theft, and auth doesn't fix arbitrary-path read/write on its own

### Alternative 2: Restrict `input_dir`/`output_dir` to an allow-listed base directory
- **Pros**: closes the arbitrary filesystem read/write risk even if the port is exposed
- **Cons**: more implementation and config surface for a spike; the labeling workflow needs to point at whatever directory the user's images actually live in, which is unpredictable
- **Why not**: deferred because it constrains the exact workflow this tool exists to support; documented instead as an operational constraint (never run on a shared machine)

## Consequences

### Positive
- Minimal implementation — no auth middleware, no secret management, no config for allowed paths
- Matches the actual deployment shape: `127.0.0.1` binding locally, or Docker Compose with no external network exposure

### Negative
- Any process that can reach the backend's port can read or overwrite arbitrary files the backend process has access to
- Docker Compose's mounted `./data` volume limits blast radius in that deployment mode, but bare `uvicorn` runs have no such boundary

### Risks
- **Accidental exposure on a shared/multi-user machine or network** — mitigated only by documentation (`backend/README.md`, `docs/RUNBOOK.md`) telling operators not to do this; there is no code-level safeguard. If this backend is ever deployed beyond a single local user, this ADR must be revisited alongside ADR-0001.
