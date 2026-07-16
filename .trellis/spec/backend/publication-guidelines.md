# Reviewed Problem Publication Guidelines

## Scenario: Explicit Lark Base Publication

### 1. Scope / Trigger

Use this contract when a teacher explicitly publishes a reviewed local problem to the existing Lark Base. Local immutable evidence remains authoritative; Lark is the reusable teacher/Agent work catalog. Publishing is never an implicit side effect of review.

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
        reviewed_at: datetime,
        ocr_provider: str,
        ...,
    )
) -> ProblemPublicationResult
```

Database table: `problem_publications`, unique on `reviewed_problem_id`, with `pending / succeeded / failed` current workflow state.

### 3. Contracts

- Eligibility: `ReviewStatus.REVIEWED`, non-null current revision/reviewed time, non-empty corrected text, and valid source/region/OCR lineage.
- Environment: `PROBLEM_PUBLISHER=fake|lark_cli`, `LARK_BASE_TITLE`, `LARK_CLI_COMMAND`, `LARK_PUBLISH_TIMEOUT_SECONDS`. Tokens remain in lark-cli user auth, never application settings.
- Target tables are `错题页面` and `错题题目`. During the migration window the adapter may resolve legacy aliases `pages` and `questions`, but writes use the schema actually resolved at runtime.
- Hidden business keys are `SourceAsset.id -> 错题页面.系统页面ID`, `SourceAsset.file_hash -> 错题页面.源文件哈希`, and `ReviewedProblem.id -> 错题题目.系统题目ID`. They remain machine-stable while teachers see readable titles.
- One physical source image is one `错题页面` row. Resolve by exact `系统页面ID` first; if absent, resolve by exact SHA-256 `源文件哈希`. A unique hash match is reused without overwriting its title, attachment, page metadata, or original system page ID. More than one hash match is a safe duplicate error.
- Teacher-visible primary fields are text `错题页面.页面名称` and `错题题目.题目名称`. A newly published row receives a safe `待整理页面·…` / `待整理题目·…` title until AI catalog enrichment replaces it with a concise semantic name. These titles are never sync keys.
- Publisher-owned page fields: `系统页面ID`, `源文件哈希`, `页面名称`, and `原始页面图片`. The cancelled `图片名` and legacy `序号` fields are compatibility-only and must not be recreated.
- Publisher-owned question fields: `系统题目ID`, `题目名称`, `所属错题页面`, `图片题目`, `题干文本`, `OCR Provider`, `本地修订版本`, `已审核时间`. The local reviewed-problem rule is the publication gate; Base does not duplicate it as `审核状态` or `是否待复核` columns.
- Do not clear teacher-owned unit/topic/type/knowledge/answer fields or future generated fields.
- `lark-cli base +record-upsert` is create-or-update by record ID, not business-key upsert. Always exact-filter by the stable text field before create.
- Stable-key lookup must use an exact Base-side filter with a duplicate limit; do not scan a fixed first page or use the readable title for identity.
- Current CLI record reads and create responses are columnar: `fields`, `data`, and `record_id_list`. A create ID may be at `data.record.record_id_list[0]`; do not assume `record.record_id`.
- Attachment upload appends. Search/project the attachment field first and skip upload when immutable source/crop attachment already exists.

### 4. Validation & Error Matrix

| Condition | Safe application code | Retryable |
|---|---|---|
| problem not reviewed/current revision invalid | `problem_not_publishable` | no |
| CLI missing, auth missing, Base/table/field type mismatch | `lark_publisher_configuration_error` | no |
| network/timeout/upstream failure | `lark_publisher_unavailable` | yes |
| malformed/unsupported successful envelope | `lark_publisher_invalid_response` | no |
| more than one exact stable-ID or source-hash match | `lark_publisher_invalid_response` | no; repair duplicate rows |
| an existing `系统页面ID` carries a different non-empty source hash | `lark_publisher_invalid_response` | no; inspect corrupted page lineage |
| required readable primary field missing or wrong type | `lark_publisher_configuration_error` | no; repair Base schema |

Never expose CLI stderr, Base token, absolute temp path, OCR/revision text or attachment bytes.

### 5. Good / Base / Bad Cases

- Good: first publish creates page/question, links them, uploads both attachments and stores remote IDs locally.
- Base: question creation succeeds but attachment upload fails. Local state becomes failed; retry finds the same stable-ID row, skips the existing page attachment and appends only the missing crop.
- Bad: retry calls create without exact lookup, or blindly uploads both attachments. This produces duplicate rows/attachments and breaks idempotency.

### 6. Tests Required

- Service: unreviewed rejection, pending-to-success, pending-to-failed, retry reuses one local state, review eligibility remains unchanged on failure.
- Adapter contract: target and legacy table aliases without Base review columns, hidden-ID-first/source-hash-second page lookup, unique hash reuse and duplicate-hash rejection, readable placeholder titles with legacy fallback, controlled-field payload containing local revision/review time but not `审核状态` or `是否待复核`, columnar create response, existing attachment skip, relative temp file path, and safe error mapping.
- Migration: fresh up/down/up and ORM table parity.
- API/OpenAPI/frontend: nullable publication projection, decoder validation, disabled reviewed gate, safe retry message.
- E2E: Fake Publisher publish, reload, and same-row resync action. The Playwright API server environment must explicitly set `PROBLEM_PUBLISHER=fake`; never rely on the default because a developer's root `.env` may intentionally select `lark_cli`.
- One approved anonymous real smoke: verify page image, crop, page link, local revision number and reviewed time by readback without logging their values.

### 7. Wrong vs Correct

Wrong:

```python
# `record-upsert` does not search by this field, and attachment upload appends.
create_record({"题目名称": "1"})
upload_attachment(crop)
```

Correct:

```python
page = exact_filter("系统页面ID", source_asset_id, limit=2)
if not page:
    page = exact_filter("源文件哈希", source_file_hash, limit=2)
page_record_id = reuse_unique(page) if page else create_page()

matches = exact_filter("系统题目ID", problem_id, limit=2)
record_id = update(matches[0]) if len(matches) == 1 else create({"题目名称": readable_placeholder})
if not attachment_cell_has_value(record_id, "图片题目"):
    upload_attachment(record_id, crop)
```
