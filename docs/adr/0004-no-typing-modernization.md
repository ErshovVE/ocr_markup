# ADR-0004: Preserve `typing.Dict`/`List`/`Optional` instead of modernizing to `dict`/`list`/`X | None`

**Date**: 2026-08-18 (backfilled — date of the commit that added `pyproject.toml` with `ruff` configured and explicitly excluding the `UP` (pyupgrade) rule set)
**Status**: accepted
**Deciders**: Vladislav Ershov

## Context

Python 3.9+ allows built-in generics (`dict[str, int]`) and 3.10+ allows `X | None` in place of `typing.Optional[X]`. `ruff`'s `UP` (pyupgrade) rule set would auto-flag and could auto-fix the codebase to the modern syntax. The existing codebase (`frontend/src/models.py`, `backend/*.py`, etc.) consistently uses `Dict`/`List`/`Optional` from `typing`, and dataclasses are not marked `frozen=True`.

## Decision

Explicitly exclude the `UP` rule set from `ruff.lint.select` in `pyproject.toml`, and keep writing new code with `typing.Dict`/`List`/`Optional` rather than the modern built-in syntax, and without `frozen=True` on dataclasses.

## Alternatives Considered

### Alternative 1: Enable `UP` and let ruff auto-fix the whole codebase
- **Pros**: shorter, more modern type annotations; matches current Python style guidance
- **Cons**: a repo-wide mechanical rewrite with no functional benefit, touching every annotated function signature
- **Why not**: the project's `pyproject.toml` comment states this exclusion is intentional — the churn isn't judged worth it for a project of this size with no external API consumers who'd benefit from cleaner type hints

### Alternative 2: Modernize incrementally, new code only
- **Pros**: no big-bang rewrite, gradual convergence
- **Cons**: produces an inconsistent codebase mixing old and new annotation styles indefinitely, which is arguably worse than picking one and sticking to it
- **Why not**: consistency was preferred over gradual modernization for a codebase this size

## Consequences

### Positive
- Codebase stays internally consistent — one annotation style throughout, documented in `CLAUDE.md` so new contributors don't "fix" it unprompted
- No risk of a large mechanical diff obscuring real changes in future PRs

### Negative
- New code looks stylistically dated relative to current Python conventions
- Contributors used to modern syntax must consciously downgrade their habitual style when writing here

### Risks
- **Low** — this is a style-only decision with no functional consequence; the main risk is a future contributor unknowingly enabling `UP` and generating unwanted churn. Mitigated by the comment in `pyproject.toml` and the `CLAUDE.md` "Code Style" section.
