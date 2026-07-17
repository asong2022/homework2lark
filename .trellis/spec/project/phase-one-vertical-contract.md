# Phase 1 Vertical Contract

## 1. Scope / Trigger

This contract applies whenever a change crosses Web, HTTP, database, local storage or OCR configuration. The current path is one image -> teacher-confirmed regions -> append-only OCR attempts -> immutable teacher-confirmed revision -> optional explicit Lark publication. Web owns upload and framing only; Agent/API clients own OCR, revision and publication.

## 2. Signatures

```text
POST /api/v1/assets
POST /api/v1/assets/{assetId}/detection-runs
POST /api/v1/assets/{assetId}/regions
POST /api/v1/assets/{assetId}/regions/batch
GET  /api/v1/assets/{assetId}/problems
POST /api/v1/regions/{regionId}/ocr-runs
POST /api/v1/regions/{regionId}/revisions
GET  /api/v1/problems/{problemId}
POST /api/v1/problems/{problemId}/publications/lark
```

```python
StorageAdapter.write/read/delete/exists
ProblemRegionDetectionProvider.detect(RegionDetectionInput) -> RegionDetectionResult
OCRProvider.recognize(OCRInput) -> OCRResult
```

Current database lineage:

```text
SourceAsset -> ProblemRegion -> OCRRun -> ProblemRevision
            -> ProblemAsset.current_revision_id -> ProblemPublication
```

## 3. Contracts

- Region requests use `coordinateSystem=normalized_top_left`; persistence stores displayed-source integer `pixel_top_left` boxes.
- Batch detected selections carry ordered `detectionCandidateIds`; manual selections carry none. Several provider boxes may form one logical problem.
- Every OCR request appends one run. Every teacher save appends one revision and immediately updates `ProblemAsset.current_revision_id`.
- `NormalizedProblemRecord.ocr` is the current revision's baseline, or the latest successful run when no revision exists. `latestOcrRun` is the newest attempt and may be failed.
- The public record contains no review status, review event, reviewed timestamp or future-reuse boolean.
- Publication requires a non-empty current revision plus valid source/region/crop/OCR lineage. It remains an explicit external mutation.
- `GET /assets/{assetId}/problems` returns stable bbox order with `no-store`; an existing empty page returns an empty collection.
- Web stops after region persistence and public-ID handoff. It never calls OCR, revision or publication.
- Default OCR is hosted `paddleocr_vl_api` / `PaddleOCR-VL-1.6`; the only other production OCR option is local `paddleocr`.
- FastAPI OpenAPI is authoritative; export it and regenerate TypeScript in the same change.

## 4. Validation & Error Matrix

| Condition | HTTP/code | Persistence |
| --- | --- | --- |
| corrupt/unsupported image | 415/422 | no usable asset |
| oversized image | 413 `asset_too_large` | no usable asset |
| invalid region | 422 `invalid_region` | source retained |
| storage failure | 500 `storage_unavailable` | compensate only current new key |
| OCR invalid/unavailable/timeout | 502/503/504 | failed run plus source/region/crop retained |
| invalid revision baseline/text | 422 | prior evidence retained |
| publication without valid current revision/lineage | 409 `problem_not_publishable` | local evidence retained |
| malformed frontend 2xx | client `invalid_response` | no optimistic domain state |

Every JSON error uses the safe `ErrorEnvelope` and request ID.

## 5. Good / Base / Bad Cases

- Good: teacher frames a question, Agent runs PaddleOCR-VL, teacher confirms corrected content, revision becomes current, and explicit publication succeeds.
- Base: hosted OCR is unavailable; a failed run remains retryable and an earlier current revision is unchanged.
- Bad: OCR text overwrites teacher text, the newest failed OCR becomes the selected baseline, or a second review status is reintroduced.

## 6. Tests Required

- Backend full flow and failure durability: `apps/api/tests/integration/test_full_flow.py`.
- 0004 -> 0005 sample-data preservation and fresh up/down/up migration.
- OCR transport/normalization plus opt-in live hosted smoke.
- OpenAPI drift and runtime frontend decoding.
- Web geometry, manual/detection recovery and Playwright public-ID handoff without downstream calls.
- Skill intake regression: save revision -> publish, with no review command.

## 7. Wrong vs Correct

Wrong:

```python
revision = create_revision(...)
problem.status = "needs_review"
review(problem, revision.id)
```

Correct:

```python
revision = append_revision(...)
problem = update_current_revision(problem.id, revision.id)
publish(problem.id)  # separate, explicit, lineage-validated mutation
```
