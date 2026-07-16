# Database Guidelines

## Baseline

- SQLAlchemy 2.x declarative mappings are the persistence model.
- Alembic is the only schema-change mechanism. Application startup must not call `metadata.create_all()` outside tests.
- SQLite is the Phase 1 development database. Keep SQLAlchemy types and queries portable to PostgreSQL.
- Enable SQLite foreign keys for every connection.

## Current Aggregate and Lineage

The first migration contains only:

- `source_assets`
- `problem_regions`
- `ocr_runs`
- `problem_revisions`
- `reviewed_problems`
- `review_status_events`

Do not create `students`, `classes`, `mistake_occurrences`, tagging, generation, queue, or analytics tables in Phase 1.

Migration `0002_region_detection` additionally owns `region_detection_runs`, `region_candidates`, and additive selection lineage columns on `problem_regions`. Machine candidates are immutable evidence; UI deletion never deletes candidate rows.

Migration `0003_multi_candidate_lineage` owns `problem_region_candidate_sources`. One logical `ProblemRegion` may reference multiple ordered Provider candidate boxes, while every candidate remains globally unique to one saved logical problem. Keep `problem_regions.detection_candidate_id` as the first candidate for compatibility; never treat it as the complete lineage after `0003`.

Migration `0004_problem_publications` owns one mutable current publication state per reviewed problem. `problem_publications` is retry/remote-pointer workflow state, not OCR or human evidence: retries update the same row, while `published_revision_id` records which immutable revision was attempted or published.

Every downstream record keeps an explicit foreign key to its source. Deleting a source later must be an intentional aggregate operation; do not rely on accidental filesystem or database cascades.

## Immutable Evidence

- Treat `SourceAsset` bytes and metadata as immutable after creation.
- Treat completed `OCRRun` rows as append-only. A retry creates another run.
- Treat `ProblemRevision` rows as append-only. New text creates the next monotonically increasing `revision_number` per region.
- Saving a revision updates `ReviewedProblem.current_revision_id` to that immutable revision. If it was reviewed, clear `reviewed_at` and transition to `needs_review`.
- Updating `ReviewedProblem.current_revision_id`, status, and timestamps is allowed; append a `ReviewStatusEvent` whenever its status changes and reference the causal `ocr_run_id`/`revision_id` when present.
- Do not copy corrected text into `OCRRun.extracted_text`.

## Transactions

- A use case owns its commit/rollback boundary.
- Persist an OCR attempt in `running` state before invoking the Provider, then finish the same row as `succeeded` or `failed`. A Provider failure must still leave a durable attempt record.
- Compensate a newly written file if its matching database transaction fails. Never delete an existing source/crop during an OCR or review failure.
- Batch region confirmation validates every selection before file writes, writes all crops, then creates regions/problems/events in one transaction. On failure, compensate every crop written by that batch and keep the source plus detection evidence.
- Lock-free revision numbering is acceptable for the single-teacher SQLite MVP. Before multi-user adoption, replace `max + 1` with a concurrency-safe mechanism.

## Queries and Loading

- Repository implementations use `select()` and explicit eager loading for the normalized record; do not trigger uncontrolled N+1 lazy loads during serialization.
- Query by public string ID, never expose SQLite row IDs.
- Index all foreign keys used in lineage reads, `source_assets.file_hash`, and `(problem_region_id, revision_number)`.
- Store Provider raw output as JSON. Normalize NumPy values before persistence so reads do not depend on PaddleOCR types.

## Migration Rules

- Migration filenames begin with an ordered revision identifier and a concise purpose.
- Both `upgrade()` and `downgrade()` are required.
- Test `upgrade head` on a fresh database and compare tables/constraints to ORM mappings.
- Never edit an applied migration after it is shared; add a new migration.

## Avoid

- SQLite-only SQL, implicit autocommit, database paths hard-coded in source, or absolute storage paths in rows.
- JSON blobs that replace modeled lineage relationships.
- A single mutable “problem” row containing OCR text, corrected text, and student occurrence data.
