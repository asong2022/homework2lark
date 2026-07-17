# Problem Asset Publication Guidelines

## Scenario: Explicit Lark Base Publication

### 1. Scope / Trigger

Use this contract when an Agent explicitly publishes a teacher-confirmed local `ProblemAsset` to the configured Lark Base. Local immutable evidence remains authoritative; Lark is the reusable teacher/Agent catalog. Saving a revision does not implicitly publish it.

### 2. Signatures

```text
POST /api/v1/problems/{problem_id}/publications/lark
```

```python
ProblemPublisher.publish(
    ProblemPublicationRequest(
        source_asset_id: str,
        source_file_hash: str,
        source_image_bytes: bytes,
        problem_id: str,
        crop_image_bytes: bytes,
        revision_id: str,
        revision_number: int,
        corrected_text: str,
        revision_created_at: datetime,
        ocr_provider: str,
        ...,
    )
) -> ProblemPublicationResult
```

Database table: `problem_publications`, unique on `problem_id`, with `pending / succeeded / failed` current workflow state.

### 3. Contracts

- Eligibility: `ProblemAsset.current_revision_id` resolves to a same-region, non-empty `ProblemRevision`; source, region, crop and the revision's OCR baseline all exist.
- No review status, review timestamp, status event or `futureReuseEligible` participates in eligibility.
- Environment: `PROBLEM_PUBLISHER=lark_cli`, `LARK_BASE_TITLE`, `LARK_CLI_COMMAND`, `LARK_PUBLISH_TIMEOUT_SECONDS`. Production has no selectable fake publisher; tests inject a stub directly from `tests/support`. Tokens remain in lark-cli user auth.
- Target tables are `错题页面` and `错题题目`; `pages/questions` aliases are compatibility-only.
- Hidden keys are `SourceAsset.id -> 系统页面ID`, `SourceAsset.file_hash -> 源文件哈希`, and `ProblemAsset.id -> 系统题目ID`.
- Resolve one page by exact system ID first, then unique exact SHA-256. Multiple hash matches fail closed.
- Publisher-owned page fields: `系统页面ID`, `源文件哈希`, `页面名称`, `原始页面图片`.
- Publisher-owned question fields: `系统题目ID`, `题目名称`, `所属错题页面`, `图片题目`, `题干文本`, `本地修订版本`. OCR Provider identity remains local `OCRRun` evidence and is not a teaching-catalog field.
- Never require or write `已审核时间`, `审核状态` or `是否待复核`. Do not clear teacher-owned metadata or variant relations.
- Exact-filter stable keys before create. `record-upsert` by record ID is not business-key upsert.
- Attachment upload appends; read the cell first and skip an already present immutable attachment.

### 4. Validation & Error Matrix

| Condition | Safe application code | Retryable |
| --- | --- | --- |
| current revision absent/empty or lineage incomplete | `problem_not_publishable` | no |
| CLI/auth/Base/table/field mismatch | `lark_publisher_configuration_error` | no |
| network/timeout/upstream failure | `lark_publisher_unavailable` | yes |
| malformed successful envelope | `lark_publisher_invalid_response` | no |
| duplicate exact stable ID/hash | `lark_publisher_invalid_response` | no; repair duplicates |
| existing system page ID has a different non-empty hash | `lark_publisher_invalid_response` | no |

Never expose CLI stderr, Base token, absolute temp path, OCR/revision text or attachment bytes.

### 5. Good / Base / Bad Cases

- Good: first publication creates one page and one question, links them, uploads both attachments, then stores remote IDs locally.
- Base: question row exists but crop upload failed. Retry finds the same stable-ID row and uploads only the missing attachment.
- Bad: require an old review timestamp, create by readable title, or upload attachments blindly on every retry.

### 6. Tests Required

- Service: no-current-revision rejection; valid-current-revision success; source/crop/OCR lineage rejection; pending-to-success/failure; retry reuses local state.
- Adapter: table aliases, hidden-ID/hash lookup, duplicate rejection, readable placeholders, payload with revision number but no retired review or OCR-provider fields, columnar create response, attachment skip and safe error mapping.
- Migration: 0004 sample data upgrades to 0005 with IDs, current revision and publication pointers preserved.
- API/OpenAPI/frontend: publication projection decodes without review fields.
- E2E: framing remains independent and never invokes publication.

### 7. Wrong vs Correct

Wrong:

```python
if problem.review_status != "reviewed":
    reject()
create_record({"题目名称": "1", "已审核时间": problem.reviewed_at})
```

Correct:

```python
revision = require_current_nonempty_revision(problem)
require_source_crop_and_ocr_lineage(revision)
record = exact_filter("系统题目ID", problem.id, limit=2)
publish_revision(record, revision.revision_number)
```
