# Architecture Decision Records

| ADR | Title | Status | Date |
|-----|-------|--------|------|
| [0001](0001-flat-files-over-database.md) | Flat files over a database for annotation and job state | accepted | 2026-08-18 |
| [0002](0002-backend-no-auth-local-spike.md) | Backend runs without authentication as a local single-user spike | accepted | 2026-08-18 |
| [0003](0003-two-independent-services.md) | Frontend and backend are two fully independent services | accepted | 2026-08-18 |
| [0004](0004-no-typing-modernization.md) | Preserve `typing.Dict`/`List`/`Optional` instead of modernizing | accepted | 2026-08-18 |
| [0005](0005-configurable-engine-consensus-scheme.md) | Configurable engine/consensus scheme instead of hardcoded 3-engine majority vote | accepted | 2026-08-23 |
| [0006](0006-drop-surya-multiline-merged-boxes.md) | Drop lines where the Surya line detector appears to have merged multiple text lines | accepted | 2026-08-23 |

ADRs 0001–0004 were backfilled on 2026-08-19 from decisions already documented
in `CLAUDE.md`, `docs/architecture.md`, and `backend/README.md`; dates reflect
the git commit that introduced each decision, not the ADR authoring date.
Use `template.md` for new ADRs going forward.
