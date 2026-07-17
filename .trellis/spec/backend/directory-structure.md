# Backend Directory Structure

## Canonical Layout

```text
apps/api/
├── alembic/                         # Versioned schema migrations only
├── src/mistake_notebook_api/
│   ├── api/                         # FastAPI routers, dependencies, middleware
│   ├── application/                 # Workflow services and ports
│   ├── domain/                      # Entities, enums, rules, safe errors
│   ├── infrastructure/
│   │   ├── database/                # SQLAlchemy engine, models, repositories
│   │   ├── ocr/                     # Hosted/local PaddleOCR adapters
│   │   ├── publication/             # Test and lark-cli problem publishers
│   │   ├── yescan/                  # Shared signed API client + Yescan adapters
│   │   └── storage/                 # Local filesystem adapter
│   ├── config.py                    # Environment-backed settings
│   └── main.py                      # Application composition only
└── tests/
    ├── unit/
    ├── integration/
    └── contract/
```

## Dependency Direction

`api -> application -> domain` and `infrastructure -> application/domain`.

- Routers translate HTTP input/output and call application services. They do not crop images, call PaddleOCR, or issue SQL queries.
- Application services own use-case orchestration and transaction boundaries.
- Domain code owns immutable-version rules, current-revision identity, publication prerequisites, and stable domain errors.
- Infrastructure implements Repository, `StorageAdapter`, and `OCRProvider` ports.
- `main.py` composes concrete adapters and registers middleware/routers; it must not contain business rules.

## Feature Placement

- Add a route only when an HTTP operation is required by the active task.
- Add a service method for a complete use case such as upload, create region, run OCR, revise, publish, or read normalized record.
- Keep Provider-specific parsing in `infrastructure/ocr`; never add `rec_texts`, NumPy conversion, tokens, or vendor error names to routers/services.
- Keep vendor-neutral automatic-region contracts in `domain/detection.py`. Yescan signing, request envelopes, and `StructureInfo` parsing stay in `infrastructure/yescan`; machine candidates are not `ProblemRegion` entities until teacher confirmation.
- Keep filesystem paths in the storage adapter. Other layers exchange opaque storage keys or bytes.
- Keep Base tokens, field IDs, CLI envelopes, attachment temp files, and columnar response parsing in `infrastructure/publication`; application code depends only on `ProblemPublisher`.
- Shared API schemas live under `api/schemas.py` (or a small feature schema module once that file becomes hard to navigate); ORM models are never response models.

## Naming

- Python files, functions, table names, and columns use `snake_case`.
- Classes use `PascalCase`; interfaces/ports use descriptive nouns such as `OCRProvider` and `ProblemRepository` without an `I` prefix.
- IDs use semantic prefixes (`asset_`, `region_`, `ocr_`, `revision_`, `problem_`, `publication_`) followed by UUID text.
- UTC helper names must state UTC (`utc_now`); do not use naive `datetime.now()`.

## Avoid

- Generic `utils.py` dumping grounds. Put helpers beside the contract they support.
- A route per database table. Routes represent teacher workflows, not ORM CRUD exposure.
- Importing a concrete OCR/storage/repository adapter from domain code.
- Creating empty modules for Roadmap capabilities.
