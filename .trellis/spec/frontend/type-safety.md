# Type Safety

## Contract Source

FastAPI OpenAPI and `packages/contracts` describe the public API. `apps/web/src/lib/contracts.ts` contains the TypeScript projection used by the UI. Frontend types model API JSON, not SQLAlchemy/database fields.

## Required Types

- Branded or template-literal-friendly string aliases for public IDs where useful.
- Discriminated unions for request state and OCR/publication status.
- Exact `NormalizedProblemRecord`, OCR block/run, revision, publication, lineage, asset, region, and error envelope shapes.
- `unknown` for untrusted JSON until decoded by the API client.

## Runtime Boundary

- `api-client.ts` checks response status and decodes the stable error envelope.
- Optional/nullable fields remain explicit; do not coerce absent OCR/revision data to empty objects.
- Date strings stay ISO strings in contracts and are formatted at render time.
- Raw Provider response is `unknown`/JSON value and may only be rendered in a guarded diagnostic view.
- A generated TypeScript declaration is not runtime validation. Success decoders must validate nested region bbox/media URLs, lineage IDs, OCR/revision histories, publication and timestamps before a component receives the record. A malformed 2xx becomes `invalid_response`, not a render crash.

## Forbidden Patterns

- `any`, double assertions (`as unknown as X`), non-null assertions used to bypass workflow state, or local casts of raw `fetch().json()`.
- Reintroducing product review-status strings or accepting retired review fields from a malformed payload.
- Importing generated/server-internal Python/database names into frontend concepts.

## Verification

Run `tsc --noEmit` and contract-focused tests. When the OpenAPI schema changes, update the TypeScript projection and full-flow test in the same task.

Contract sync command: `npm run contracts`. `apps/api/tests/contract/test_openapi.py` rejects a stale committed snapshot; `apps/web/src/lib/api-client.test.ts` rejects malformed nested success payloads.
