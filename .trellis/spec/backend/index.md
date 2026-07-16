# Backend Development Guidelines

These rules govern the FastAPI application in `apps/api`. They are the L1 source of truth for Phase 1 backend changes.

## Pre-Development Checklist

Read, in order:

1. `docs/bootstrap-assumptions.md` and the active task's `prd.md`, `design.md`, and `implement.md`.
2. [Directory Structure](./directory-structure.md) for layer ownership.
3. [Database Guidelines](./database-guidelines.md) before changing entities, repositories, or migrations.
4. [Adapter Guidelines](./adapter-guidelines.md) before changing OCR or file storage.
5. [Publication Guidelines](./publication-guidelines.md) before publishing reviewed problems to an external catalog.
6. [Error Handling](./error-handling.md) and [Logging Guidelines](./logging-guidelines.md) for every API or Provider path.
7. [Quality Guidelines](./quality-guidelines.md) before implementation and review.
8. `.trellis/spec/guides/cross-layer-thinking-guide.md` for changes that touch API, service, storage, and UI.

## Guides

| Guide | Owns |
|---|---|
| [Directory Structure](./directory-structure.md) | Package layout and dependency direction |
| [Database Guidelines](./database-guidelines.md) | SQLAlchemy, migrations, lineage, transactions |
| [Adapter Guidelines](./adapter-guidelines.md) | OCR and storage ports/adapters |
| [Publication Guidelines](./publication-guidelines.md) | Reviewed-problem publication state and Lark CLI adapter |
| [Error Handling](./error-handling.md) | Domain errors and stable API envelopes |
| [Logging Guidelines](./logging-guidelines.md) | Privacy-safe structured events |
| [Quality Guidelines](./quality-guidelines.md) | Types, tests, lint, and review gates |

## Quality Check

- Run `uv run --directory apps/api ruff check .`.
- Run `uv run --directory apps/api ruff format --check .`.
- Run `uv run --directory apps/api mypy src`.
- Run `uv run --directory apps/api pytest`.
- Run `uv run --directory apps/api alembic upgrade head` against a fresh SQLite database.
- Verify OCR runs and revisions are appended, never updated in place.
- Verify only a reviewed problem with a valid current revision is `futureReuseEligible`.
- Verify failures do not remove the source asset or problem region.

Documentation under `.trellis/spec/` is written in English so future development agents receive concise, stable instructions. Product documentation may be Chinese.
