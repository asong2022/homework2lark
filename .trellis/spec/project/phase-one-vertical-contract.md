# Phase 1 Vertical Contract

## 1. Scope / Trigger

This contract applies whenever a change touches the Phase 1 path across Web, HTTP, database, local storage, or Provider configuration. The backend path remains one image → teacher-confirmed manual/detected regions → append-only OCR attempts → immutable human revision → explicit review → reopen by problem ID or source asset ID. The browser owns only the first two stages: it persists regions/crops, returns public problem IDs, and leaves OCR/revision/review/publication to the Agent or another API client.

## 2. Signatures

HTTP signatures:

```text
POST /api/v1/assets
POST /api/v1/assets/{assetId}/detection-runs
POST /api/v1/assets/{assetId}/regions
POST /api/v1/assets/{assetId}/regions/batch
GET  /api/v1/assets/{assetId}/problems
POST /api/v1/regions/{regionId}/ocr-runs
POST /api/v1/regions/{regionId}/revisions
POST /api/v1/problems/{problemId}/review
GET  /api/v1/problems/{problemId}
```

Port signatures:

```python
StorageAdapter.write/read/delete/exists
ProblemRegionDetectionProvider.detect(RegionDetectionInput) -> RegionDetectionResult
OCRProvider.recognize(OCRInput) -> OCRResult
```

Migration `0001_phase_one` owns the six original evidence tables. Migration `0002_region_detection` adds immutable detection runs/candidates and primary selection lineage. Migration `0003_multi_candidate_lineage` allows multiple Provider candidate boxes to contribute to one logical problem; none of these migrations add student, class, tagging, generation, or queue tables.

## 3. Contracts

- Region request uses `coordinateSystem = normalized_top_left`, finite `x/y/width/height` in 0..1; persistence stores displayed-source `pixel_top_left` integers.
- Batch detected selections carry one or more `detectionCandidateIds`; manual selections carry none. Multiple Provider boxes confirmed as one question produce one crop, one region, and one problem ID.
- `NormalizedProblemRecord.ocr` is the current revision's baseline, or the latest successful run when no revision exists; `latestOcrRun` is the newest attempt and may be failed.
- Every OCR request appends one run. Every teacher save appends one revision. Review requires an explicit revision ID.
- `GET /assets/{assetId}/problems` returns all normalized records in stable bbox order with `no-store`; a missing asset is 404 while an existing page with no regions is an empty collection.
- Web framing ends after the batch region response. It does not call OCR, revision, review, publication, or Base endpoints; those backend operations remain available to Agent clients.
- `futureReuseEligible` is server-derived and true only for a reviewed problem with a current revision.
- Environment: `DATABASE_URL`, `STORAGE_ROOT`, `OCR_PROVIDER`, `OCR_TIMEOUT_SECONDS`, local-Paddle `PADDLEOCR_LANGUAGE` / `PADDLEOCR_MODEL_NAME`, hosted-VL `PADDLEOCR_ACCESS_TOKEN` / `PADDLEOCR_API_JOB_URL` / `PADDLEOCR_VL_MODEL` / request-poll settings, and browser `NEXT_PUBLIC_API_BASE_URL`.
- FastAPI OpenAPI is authoritative; export to `packages/contracts/openapi.json`, then generate `apps/web/src/lib/generated-api.ts`.

## 4. Validation & Error Matrix

| Condition | HTTP/code | Persistence |
|---|---|---|
| corrupt/unsupported image | 415/422 | no usable asset |
| oversized image | 413 `asset_too_large` | no usable asset |
| invalid region | 422 `invalid_region` | source retained |
| storage failure | 500 `storage_unavailable` | compensate only current new key |
| Provider invalid/unavailable/timeout | 502/503/504 | failed run plus source/region/crop retained |
| invalid revision baseline | 422 `ocr_run_invalid` | prior evidence retained |
| review without same-problem revision | 409 `review_revision_required` | status unchanged |
| malformed frontend 2xx payload | client `invalid_response` | no optimistic domain state |

Every JSON error uses `ErrorEnvelope` with safe Chinese message, `requestId`, `retryable`, and non-sensitive details.

## 5. Good / Base / Bad Cases

- Good: teacher uploads a tall PNG, reverse-drags a region, receives Fake OCR, saves a different correction, reviews it, then reloads the detail and sees source/crop/OCR/revision/status lineage.
- Base: hosted PaddleOCR-VL is unavailable; the failed OCRRun, source, region, and crop remain retryable. Fake and local Paddle are explicit configuration choices, never silent fallbacks.
- Bad: failed latest OCR replaces the OCR baseline of an existing revision, or a revision from another region is reviewed. Both violate causal lineage and must be rejected/represented separately.

## 6. Tests Required

- Backend full flow and failure durability: `apps/api/tests/integration/test_full_flow.py`.
- Image/EXIF/coordinate rules: `apps/api/tests/unit/test_images.py`.
- Provider/raw/timing contract: `apps/api/tests/contract/test_ocr_providers.py` and `test_paddleocr_vl_api_provider.py`.
- Log privacy: `apps/api/tests/integration/test_error_privacy.py`.
- OpenAPI error schemas/drift: `apps/api/tests/contract/test_openapi.py`.
- Frontend geometry/detection/recovery/runtime decode: colocated `*.test.ts(x)` files under `apps/web/src`.
- Browser proof: `apps/web/e2e/one-problem-flow.spec.ts` asserts upload, manual/automatic framing, merge, batch save, saved crop/public-ID handoff, restoration, and responsive layout.

## 7. Wrong vs Correct

Wrong:

```python
# OCR text is overwritten by the teacher and the latest failed attempt becomes current.
run.extracted_text = corrected_text
record.ocr = record.latest_ocr_run
```

Correct:

```python
# Append a revision and keep its explicit successful OCR baseline.
revision = ProblemRevision(based_on_ocr_run_id=run.id, corrected_text=corrected_text)
record.ocr = run
record.latest_ocr_run = latest_attempt
```

The separation preserves machine evidence, human authorship, retry history, and future review eligibility.
