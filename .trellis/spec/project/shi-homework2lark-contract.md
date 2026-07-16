# shi-homework2lark Contract

## Scenario A: Agent-Assisted Mistake Intake

### 1. Scope / Trigger

Use this contract when Codex, Hermes, or another compatible Agent receives an image, PDF, Word document or teacher description and helps turn selected questions into reviewed local problem assets and explicitly publish them to Lark Base. PDF/Word are normalized to visual page images before entering the image-only FastAPI; the primary experience starts in the Agent conversation and Web is an optional precision tool.

When collection begins, the user—not the Agent—must first choose one of three collection modes: `teacher_selected`, `anonymous_corrected`, or `identified_corrected`. If the conversation does not already contain an explicit user choice, the Agent presents exactly those three options and stops without inspecting attachments, calling OCR/Web/Base, or persisting a default. `scripts/workflow.py` records the chosen mode with `decidedBy=user`; the five learning stages remain an internal orchestration model and are not substitutes for this choice.

There are three entry experiences but one business core:

- `web`: upload once, open the existing asset in `/intake/{assetId}`, and let the teacher use manual boxes or explicit automatic candidates before returning public problem IDs.
- `chat`: call the configured Yescan detection adapter, present group-level candidates in the conversation, and create only the candidates the teacher selects.
- `single`: treat a teacher-provided one-question image as one full-image region.

For one blank template plus many corrected copies, the blank page is the unique printed-question source. The Agent may call Yescan AI Agent `scene=question-ocr` once per blank page, confirms the complete questions, then locally registers corrected pages to those regions. It does not repeat printed-stem OCR for every student copy.

All three image modes use the FastAPI domain workflow for `SourceAsset -> ProblemRegion -> OCRRun -> ProblemRevision -> ReviewedProblem -> publication`. The Skill never writes those tables directly. PDF/Word first use MinerU plus PDF/doc page rendering; extracted text assists reading but never replaces visual page evidence.

### 2. Signatures

```text
python scripts/intake.py [--api-url URL] [--web-url URL] [--allow-fake] health
python scripts/intake.py start --file <image> --mode web|chat|single --output <manifest.json>
python scripts/intake.py select --session <json-path> --candidate-id <id>... --output <selection.json>
python scripts/intake.py ocr --problem-id problem_xxx
python scripts/intake.py get --problem-id problem_xxx
python scripts/intake.py save-revision --problem-id problem_xxx --input <json-path|->
python scripts/intake.py review --problem-id problem_xxx [--revision-id revision_xxx]
python scripts/intake.py publish --problem-id problem_xxx
python scripts/intake.py download-evidence --problem-id problem_xxx --output-dir <dir>
python scripts/intake.py validate-metadata --input <json-path|->
python scripts/base_metadata.py preview --input <json-path|->
python scripts/base_metadata.py apply --input <json-path|->
```

Web route:

```text
GET /intake/{assetId}
```

Backend operations remain the existing typed HTTP API; the Skill is a client/orchestrator, not a second backend.

### 3. Contracts

- Runtime configuration: `SHI_HOMEWORK2LARK_API_URL` defaults to the local API; `SHI_HOMEWORK2LARK_WEB_URL` defaults to `http://localhost:3000`. The current real OCR path is the hosted PaddleOCR Job API with model `PaddleOCR-VL-1.6`. Neither source nor manifests contain Provider keys, Lark tokens, Base IDs, or model keys.
- Existing JSON inputs and session manifests may be read from any readable relative or absolute path. New session, selection and evidence outputs remain explicit relative destinations under the current working directory.
- `web` uploads the source exactly once and returns the existing-asset route. That route starts in manual mode, does not invoke detection on load, and exposes an explicit automatic-framing action.
- `chat` requires a real configured detection Provider unless `--allow-fake` is explicitly used for tests. It persists Provider evidence through the API and emits only safe candidate IDs, reading order, and normalized bbox data.
- One Yescan group-level `StructureInfo` is one candidate. The Skill never splits nested text/choice/formula/table/illustration details and never silently merges separate groups. Text and an embedded diagram in one group remain one complete question asset.
- `single` creates a normalized full-image bbox without detection. OCR, revision, review, and publication gates are unchanged.
- After a Web batch save, the browser shows saved crops and public problem IDs, then stops. It must not call OCR, revision, review, publication, or Base operations.
- The existing-asset route restores every persisted region from the source-scoped problem collection and returns the same public IDs to the Agent. The teacher may deliberately continue framing on the same source.
- `get` and `ocr` return curated fields. Provider raw response, storage keys, absolute paths, image Base64, attachment URLs, remote record IDs, CLI stderr, and credentials never appear in normal output or manifests.
- The Agent may propose corrected text and teaching metadata only after inspecting the crop and OCR. The teacher must see the evidence and proposed value before mutation.
- Revision, review, and publication are distinct durable transitions. A single explicit teacher confirmation may authorize the ordered sequence, but a later failure never rolls back earlier evidence.
- Publishing uses `POST /api/v1/problems/{problemId}/publications/lark`. It requires server-confirmed reviewed eligibility. Questions are idempotent by hidden system ID; pages first use `系统页面ID` and then exact `源文件哈希`, so repeated uploads of the same bytes reuse one page row.
- Approved metadata keys are limited to:
  - page: `页面名称`, `时间`, `年级`, `页码`, `单元`, `课题名`, `错题来源`, `页面主知识点`, `备注`;
  - question: `题号`, `题目名称`, `分区标题`, `题型`, `对应知识点`, `图表说明`, `标准答案`, `答案备注`.
- `错题题目.典型错例` and `错题题目.错误表现` are read-only raw-value lookups from all linked `错题记录` groups. Metadata enrichment never writes them or fabricates a student response when grouped evidence is absent.
- `错题来源` and `题型` must match the existing agreed Base option sets; enrichment never creates a new select option as a side effect.
- `错题页面` is one row per physical source page. Multiple questions from one page link to that row through `所属错题页面`; question-side `时间`, `年级`, `页码` and `错题来源` are read-only lookups from the linked page and never appear in metadata write payloads.
- After publication, metadata enrichment is a required normal completion step. The Agent fills every reliably derivable field but leaves inapplicable or uncertain values empty.
- `base_metadata.py preview` performs no write and returns field names only. `apply` fills empty cells, treats equal values as idempotent, rejects any different non-empty value, and reads back both the question and linked page. It has no broad overwrite switch and does not create a second Base review task.
- The reviewed local original remains the publication gate. Legacy Base review fields may stay hidden during migration, but normal metadata enrichment is usable immediately; only genuine content conflicts enter the single `需人工处理` exception queue.
- Metadata never overwrites OCR, revision, review evidence, images, stable IDs, or generated variants. `题干文本` includes textual choices; `图片题目` remains one complete text-plus-image crop; `题干图片` is only an optional extracted non-text visual and never a second question. Numeric/`待整理…` title placeholders may be replaced with readable `页面名称`/`题目名称`; other non-empty titles remain conflicts.

Target Base projection:

| Table | Visible primary | Hidden stable key | Link |
|---|---|---|---|
| `错题页面` | text `页面名称` | `系统页面ID`, `源文件哈希` | reverse `关联题目` |
| `错题题目` | text `题目名称` | `系统题目ID` | `所属错题页面` |
| `错题记录` | text `记录名称` | `系统记录ID` | exactly one `对应错题`; reverse `学生错题记录` |

`错题页面.时间`, `错题页面.年级`, `错题页面.页码` and `错题页面.错题来源` are authoritative. `错题题目` exposes the same names as lookup fields selected through `所属错题页面`.

Teaching priority is a scoped view, not a durable question attribute. Every priority view declares a concrete grade and date window before applying `是否高频错题` and sorting by `错误率`. The current `2025学年下·三年级优先` view contains only Grade 3 pages dated from 2026-02-01 through 2026-08-31, excludes real exceptions, and sorts by error rate descending, date descending, then collection order. The lifelong archive remains available in `错题库`; a later term or grade must use an explicitly renamed/rescoped view rather than silently reusing this definition.
`错题记录` is a grouped teaching projection: one row represents one reviewed question, one assignment date and one shared error cause with multiple selected students. It is not one row per student and does not require a `学生` table.

### 4. Validation & Error Matrix

| Condition | Safe result | Durable state |
|---|---|---|
| unsupported file/failed upload | API validation/safe upload error | no partial asset, or committed immutable asset if upload completed |
| absolute JSON input outside repository but readable | accepted and parsed as UTF-8 | no mutation until the requested command's normal confirmation gate |
| JSON input missing/unreadable or malformed | `input_unreadable` / `invalid_payload` | none |
| PDF/Word passed directly to image CLI | `source_requires_page_images` | public Skill normalizes to page images first; no hidden direct upload |
| Web asset missing | `asset_not_found` | no detection or replacement upload |
| chat mode with Fake Provider unintentionally active | local configuration rejection | source is not described as truly detected |
| Yescan unavailable/timeout/empty | safe Provider category; retry or switch to Web manual mode | source retained; failed run evidence retained when created |
| unknown/duplicate candidate selection | local validation/API selection error | detection evidence retained; no guessed region |
| OCR failure/empty text | safe OCR code plus problem ID | source, region, crop, failed run retained |
| revision text empty | validation rejection | OCR and earlier revisions retained |
| review without valid revision | `review_requires_revision` | draft/needs-review remains |
| publish before reviewed | `problem_not_publishable` | local evidence remains; no Base mutation |
| metadata unknown key/non-object | `invalid_metadata` | no Base mutation |
| metadata conflicts with non-empty cell | conflict preview | no overwrite without a new confirmation |
| metadata apply repeated with equal values | `no_change` | no duplicate row and no extra mutation |
| confirmed AI catalog receives a changed proposal | conflict preview | remains confirmed and unchanged |

### 5. Good / Base / Bad Cases

- Good: the Agent uploads `image1.png`, returns a Web URL, the teacher uses automatic candidates plus one manual correction, clicks complete, and public problem IDs return to the conversation; the Agent then performs OCR, correction, the local quality gate, and explicit Base publication.
- Base: the Agent receives `image2.png` in chat mode; Yescan returns whole-question candidates, the teacher selects one, hosted PaddleOCR-VL-1.6 recognizes it, and the teacher corrects the flattened table text before review.
- Bad: run detection merely by opening the Web route, call OCR/review/publication from the browser, treat nested Yescan details as separate questions, silently review AI text, or write directly to Base before the local review gate.

### 6. Tests Required

- CLI unit: health, Web/chat/single manifests, candidate selection, safe HTTP errors, Fake rejection, OCR retry IDs, revision/review gates, safe projections, and metadata whitelist.
- Metadata unit: typical-error lookup immutability, absolute input paths inside/outside the repository, empty-field apply, idempotent readback, non-empty conflict, and preview output without full private text.
- Frontend unit: existing-asset load, manual mode by default, explicit optional detection, batch save without OCR, restoration, and copyable public IDs.
- Backend: Provider contracts, immutable retry history, review eligibility, hidden-ID plus source-hash page idempotency, readable sequence allocation, and privacy-safe errors.
- E2E Web: manual/automatic selected regions -> batch save -> saved crops/public IDs -> reopen without review routes.
- Real smoke: `image1.png` loads in the existing-asset Web route without automatic detection on open, explicit automatic framing remains available, and the selected crop IDs return to the Agent; `image2.png` yields Yescan whole-question candidates; one selected crop succeeds with hosted PaddleOCR-VL-1.6; after teacher-authorized Agent processing/publication, AI-derived catalog fields are previewed, applied and read back while test data remains in the private Base.

### 7. Wrong vs Correct

Wrong:

```text
upload -> force auto-detect -> write OCR text directly to Base -> mark reviewed
```

Correct:

```text
upload once -> (manual/automatic Web boxes | teacher-selected chat candidate | full-image single)
-> Web returns public IDs -> Agent runs OCR evidence -> teacher-visible correction -> append revision -> explicit review
-> explicit idempotent Base publication
```

## Scenario B: Agent-Assisted Variant Reuse Through Lark Base

### 1. Scope / Trigger

Use this contract after publication, when Codex/Hermes selects reviewed elementary-math originals from `错题题目`, generates numbered variants, and appends one linked record per variant to the separate `变式题` table. This is the order: reviewed original enters Base first; Base selection then drives generation. Complete variants are immediately reusable; only genuine exceptions require manual handling.

The workflow is a Skill/CLI capability, not a backend LLM Provider, queue, student workflow, or evidence-store replacement.

### 2. Signatures

```text
python scripts/homework2lark.py schema-check
python scripts/homework2lark.py list-selected
python scripts/homework2lark.py get (--question-id problem_xxx | --record-id rec_xxx)
python scripts/variant_catalog.py schema-check
python scripts/variant_catalog.py validate --input <json-path-or->
python scripts/variant_catalog.py write --input <json-path-or->
python scripts/variant_catalog.py list-available
python scripts/variant_catalog.py download-images --variant-id variant:v1:xxx --output-dir <relative-dir>
python scripts/practice_sheet.py --manifest <manifest.json> --output <daily-practice.docx>
```

Canonical `变式题` fields:

```text
变式题名称                        primary text (teacher-readable)
收录序号                          auto_number (read-only collection order)
来源错题                          bidirectional link -> 错题题目
变式序号                          number
题干文本                          text (required)
题干图片                          attachment (optional)
答案解析                          text (optional)
设计意图                          text (required)
核心素养                          lookup -> 错题题目.核心素养
生成时间                          datetime
系统变式ID                        text (hidden idempotency key)
```

`错题题目.核心素养` is the only editable core-literacy source and uses the agreed 11 options. `错题页面`、`错题记录` and `变式题` expose read-only lookups. `错题题目` uses `关联变式题` as the reverse relation; an empty relation defines `待生成变式`. The former `需要生成变式题` checkbox and legacy `变式题1～5` groups have been deleted after lossless migration verification.

### 3. Contracts

Generated input:

```json
{
  "questionId": "problem_xxx",
  "variants": [
    {"question": "...", "answerAnalysis": "可选", "designIntent": "说明变化轴与学习机会"},
    {"question": "只有题干也有效", "designIntent": "说明为什么这样设计"}
  ]
}
```

- Resolve every exact-title Base candidate, list its live tables, and select the unique candidate satisfying the current table contract. Feishu may return a direct Base and an app wrapper under the same title; never assume `title-resolve.data.base_token` is present. Legacy `pages/questions` aliases are accepted only during the compatibility window. Stable lookup uses `系统题目ID`; `题目名称` is teacher-facing only and must not be used as a sync key. `收录序号` is a read-only auto number; teacher-facing question views keep it after the primary field and sort ascending by default.
- `variants` contains 1-5 questions per generation request; default is 3. Each becomes a separate catalog row with the next positive `变式序号`. `question` is required and `answerAnalysis` is optional teacher support. Read both `questionImageCount` (complete crop) and `questionStemImageCount` (`题干图片`). Text-only originals default to text-only variants; a new diagram is generated only when the variant still needs a visual or the teacher explicitly asks to change representation. This is not a write-time prohibition. An item may contain a `diagram` object with reviewed relative HTML/PNG paths and a mathematical-relation description. Do not add category columns: consolidation, new representation, application, literacy, and challenge are all variation angles under the same variant concept.
- Original eligibility requires a stable `系统题目ID`, positive `本地修订版本`, non-empty `已审核时间`, `需人工处理=false`, and complete text and/or image evidence. The backend publisher still rejects every locally unreviewed problem before it can create this Base projection; Base does not duplicate `审核状态` or `是否待复核`.
- Standard answer, knowledge point, linked page number, mistake source, grouped `典型错例` / `错误表现` lookups, and the `错误原因` count summary are optional context. The Agent independently solves and verifies the original when absent and never invents observed student evidence.
- Pedagogical generation is owned by `references/variant-generation-prompt.md`. Before drafting, the Agent builds a fact card from grade/semester, the complete source, embedded visuals, mathematical essence, teacher intent, verified typical responses, visible error patterns, teacher diagnosis and latest retry feedback. Unknown facts stay unknown. If grade or an ambiguous source relation would materially change suitability, the Agent may preview an explicit assumption but must not write.
- The default style follows common Zhejiang elementary-mathematics end-of-term assessment characteristics: authentic context, concise grade-appropriate language, plausible quantities, necessary and sufficient conditions, and meaningful mathematical reasoning. Without supplied real samples, the Agent must not claim to have consulted a specific historical exam. A default three-item set uses at least two substantive variation axes unless the teacher explicitly requests tightly isomorphic practice; it never creates category fields.
- Every generated item is independently solved and checked for mathematical correctness, condition completeness, answer uniqueness or explicit openness, grade suitability, difficulty, units/data, source-essence relation and text-diagram consistency. Optional `answerAnalysis` does not waive this check. Any failed item is rewritten before it can enter a validate/write payload.
- Preview/validate is read-only. `write` requires explicit teacher approval because it mutates Base. It batch-creates new rows, verifies stable key/content/design-intent/source readback, and uploads declared diagrams. The source relation updates automatically; no selection or variant-review field is written.
- `系统变式ID` is derived from the stable source problem ID and normalized question text. An identical rerun returns `created=0` and reuses existing rows; a conflicting row with the same stable key fails. One payload may not contain the same normalized question twice, and this is enforced both by input validation and again before the first Base call. Existing duplicate stable keys stop the write instead of being collapsed by a dictionary. New content appends rows and never clears, shifts or overwrites older variants.
- `list-available` and paper assembly read separate rows with non-empty `题干文本`; missing answer analysis is returned as `null` and does not block use. The old same-row commands stop with `independent_variant_catalog_required`.
- A new `practice-sheet-v2` manifest contains exactly `batchCode`, `manifestVersion`, and continuous `items`. It freezes sequential `R01...` item codes, exact original `questionId`, and exact `variantId` where applicable, but does not predict physical pages. New batch codes match `YYYYMMDD-NN` with a valid calendar date and daily sequence `01..99`; the renderer derives the first-page `M月D日练习纸` title and a repeated-header code prefix from it. A Word `PAGE` field completes the actual `batchCode-P{pageNumber}` identifier in one fixed borderless upper-right text box on every rendered page; the footer contains only the page-number field. It contains no student identity, Base token or remote IDs. Returned scans use AI/OCR on this high-contrast text; no QR field, image, generator or decoder is part of the active contract.
- Each manifest item contains required `itemCode`, `question`, `answerLines`, and `source`, with optional `stemImage`. Item codes are globally consecutive even though the student paper displays simple numeric question numbers. `answerLines` accepts `0..8`. `source.type` is `original` or `variant`; every source has `questionId`, and a variant also has `variantId`. `stemImage` contains a readable JPG/JPEG/PNG path and non-empty description; relative paths resolve from the manifest directory and absolute readable paths are also allowed.
- The DOCX uses one A4 section. V2 items flow continuously without estimated or teacher-inserted hard page breaks; Word moves a complete question block only when the current page actually lacks space. A question block is ordered as text, optional left-aligned proportional stem image, then optional answer lines; keep-with-next/keep-together prevents the block from splitting across pages. Image bounds are 145 mm by 65 mm, and an absent image creates no placeholder. V1 manifests remain readable only for old sample compatibility.
- Runtime configuration may set `SHI_HOMEWORK2LARK_BASE_TITLE` and `LARK_CLI_COMMAND`. Tokens and remote IDs are never source configuration.
- Resolve the executable with `shutil.which`; never enable `shell=True`. Map columnar `fields`/`data`/`record_id_list` strictly and reject unequal lengths.
- `record-list --json` selects JSON output; `record-get` requires `--format json`. Treat upstream `800070003` as a no-op only when readback proves desired state. Retry bounded read-only `9499/1254291`; do not blindly retry writes.

### 4. Validation & Error Matrix

| Condition | Safe code | Mutation |
|---|---|---|
| local review evidence absent / manually flagged | `source_review_evidence_missing` / `source_needs_attention` | none |
| zero or multiple title candidates satisfy the table contract | `schema_mismatch` | none |
| original text and image both absent | `source_incomplete` | none |
| 0 or >5 questions, missing question, extra category | `invalid_payload` | none |
| source problem does not resolve uniquely | `record_not_found` | none |
| same stable variant key has conflicting content/source | `variant_conflict` | none |
| write fails / rate limited | safe Lark category; retryable flag | stop and preserve source/previous rows |
| batch write cannot be read back | `write_incomplete` | stop; do not claim success |
| missing stable key, question or unique source relation | `variant_invalid` | not available |
| declared diagram local artifact missing or upload readback fails | `diagram_incomplete` | stop; do not claim success |
| invalid batch date/sequence, non-continuous page/item number, unknown legacy/layout field, unreadable/unsupported stem image, invalid source relation or answer-line count | `ManifestError` | no Word output |

Do not expose lark-cli stderr, tokens, attachment URLs, absolute paths, or complete problem/variant text in error logs.

### 5. Good / Base / Bad Cases

- Good: `title-resolve` returns a direct Base plus an empty app wrapper; live table inspection uniquely selects the direct Base. A reviewed original receives three linked variant rows, two with answer analysis and one without; all immediately appear in `变式题/可组卷` because their required content is complete.
- Base: a complete original has no answer/tag metadata. The Agent independently solves it, validates a local preview, and waits for write approval.
- Bad: take the first same-title token without reading its tables, generate before the original enters Base, keep adding numbered columns to the original table, omit the source relation, hide an incomplete diagram from the exception queue, or create duplicate rows on an identical rerun.

### 6. Tests Required

- Payload: 1-5 required questions, optional answer analysis, ID format, unknown/category field rejection, and length limits.
- Prompt contract: the main Skill routes generation to the dedicated reference; the reference includes the fact card, Zhejiang-style boundary, non-mechanical variation rule, student-evidence honesty, independent solve/check gate, diagram delegation, stop conditions and exact `variant_catalog.py` JSON shape.
- Generation evals: a Grade 5 promotion problem targets the observed grouping error with at least two variation axes; an incomplete grade/source case stops before write; a visual problem declares a diagram only when the new conditions depend on it and verifies text-image consistency.
- Workflow: separate-row first write, append-only numbering, idempotent identical rerun, stable-key conflict, diagram exception/clear, source checkbox recovery on failure, legacy migration without deletion, and no dependency on deleted Base review columns.
- Availability: a stable source question ID plus positive local revision and reviewed time are required; question-only rows are immediately listed with `answerAnalysis: null`, while missing-source, missing-question or incomplete-diagram rows are excluded.
- Adapter: Fake runner for target/legacy schema, duplicate-title direct Base plus empty app wrapper, hidden stable ID, columnar mapping, argv lists, Windows executable resolution, and `record-get --format json` regression.
- Live readback: required fields/views, absence of all retired review states, selected count before write, separate-row count/source relation after write, idempotent second migration, and exception count for incomplete diagrams.
- Word: exact manifest shape, source/image/answer-space validation, derived title/page-code assertions, one-section natural-flow structure without generated hard page breaks, upper-right text-box position, footer page field, image-below-text ordering, question-block keep rules, editable DOCX generation, and no QR dependency.
- Package: UTF-8 quick validation, unit tests, companion `wumu-jihe-html` validation, `.skill` creation, and shared-root discovery.

### 7. Wrong vs Correct

Wrong:

```text
title-resolve -> use first token
OCR result -> generate variants -> create Base row
PATCH 变式题1 -> PATCH 答案 -> keep adding columns
```

Correct:

```text
title-resolve -> inspect every exact-title candidate -> unique table-contract match
reviewed original -> explicit Base publication -> Base selection
-> stable problem ID + local revision + reviewed time
-> local preview -> teacher-approved batch-create of linked variant rows
-> complete: available for assembly
-> incomplete/conflicting: do not write until repaired
```

## Scenario C: Diagram, Assembly And Retry Feedback

### 1. Scope

Use this contract after a reviewed original is in Base. A diagram-bearing variant delegates mathematical drawing to `wumu-jihe-html` (“这道题画张图”), keeps editable HTML locally, and writes only after the checked PNG is ready for the same `变式题` row. Practice assembly freezes exact source IDs in a batch manifest. Returned scans are observed by the Agent/`shi-ocr`; `retry_batch.py` maps page code plus visible item number back to the exact immutable source and prepares append-only events plus conservative Base projections.

Base title resolution is schema-aware. When Feishu returns a direct Base and an app wrapper under the same visible title, the Skill enumerates exact-title candidates and selects the unique candidate containing the required live tables. A top-level `base_token` remains supported only for older CLI response compatibility.

### 2. Signatures

```text
python scripts/variant_catalog.py write --input <generated.json>
python scripts/variant_catalog.py download-images --variant-id variant:v1:xxx --output-dir <relative-dir>
python scripts/practice_sheet.py --manifest <manifest.json> --output <daily-practice.docx>
python scripts/learning_feedback.py schema-check
python scripts/learning_feedback.py validate --input <relative-json|->
python scripts/learning_feedback.py preview --record-id rec_xxx --input <relative-json|->
python scripts/learning_feedback.py record --record-id rec_xxx --input <relative-json|-> --event-store <relative-jsonl>
python scripts/retry_batch.py prepare --manifest <manifest-or-class-batch> --input <observations.json> --output <plan.json>
python scripts/retry_batch.py validate --plan <plan.json>
python scripts/retry_batch.py commit --plan <plan.json> --event-store <events.jsonl>
```

Feedback Base fields:

```text
掌握状态        select: 未开始 / 练习中 / 需再练 / 已掌握
最近再练时间    datetime
```

### 3. Contracts

- Diagram work derives mathematical objects and constraints before coordinates; ambiguity that changes the answer returns to the teacher.
- Editable HTML and exported PNG are both retained. Only PNG is the Base/Word student-facing attachment; HTML remains local evidence.
- Diagram text and attachment stay on the same separate `变式题` row and never create a second variant record.
- Retry input separates `observedResponse`, `teacherJudgment`, `result`, `mastery`, `summary`, and timezone-aware `occurredAt`; identity-like unknown fields are rejected.
- Local JSONL uses a deterministic event ID and append-once behavior. A Base failure can be retried without duplicating the event.
- Base question mastery/time, or a matching mistake-group feedback/status/time, may change only after preview and explicit teacher confirmation. The complete summary remains in local events unless projected to a specific group. Grouped-evidence lookups and all source/generation fields remain unchanged.
- Word assembly keeps student questions and optional teacher answer analyses separate. Its immutable manifest carries the exact source `questionId` or `variantId`, batch code, page number and `R01...` item code. Missing analysis never blocks the student section; a requested teacher section may generate/verify it on demand or omit it explicitly.
- The rendered worksheet derives `M月D日练习纸` from the batch date, prints the full `YYYYMMDD-NN-Ppage` identifier once in a fixed upper-right text box, and leaves only the centered page number in the footer. AI/OCR uses that text directly; no QR generation or decode check is required.
- Follow `references/practice-sheet-template.md`: items remain in one A4 section and rely on Word auto-flow rather than estimated hard page breaks; optional stem images sit below their question text and align left, and one text/image/answer block never crosses pages.
- `retry_batch.py` validates `pageCode -> batch/instance/page`, maps visible item numbers to continuous `Rxx`, and then resolves the exact original `questionId` or separate-table `variantId`. A wrong page code, out-of-range number, duplicate item or source conflict fails before event append. Plan validation reconstructs every Base projection and the human-attention count from immutable events; independently edited projections are rejected. A one-off feedback event may append to local history out of order, but Base mastery/time advances only for a strictly newer timestamp.
- One observed correct response defaults to `练习中`, never `已掌握`; partial/incorrect defaults to `需再练`; uncertain/not-observed produces no automatic mastery mutation. Only an explicit teacher mastery judgment may override this rule.
- The script does not perform image recognition itself. Agent/`shi-ocr` observations remain distinct from deterministic manifest mapping, local event append, and Base projection/readback.

### 4. Wrong vs Correct

Wrong:

```text
variant text -> generic image guess -> mark reviewed
retry response -> overwrite grouped 典型错例 -> mark mastered automatically
```

Correct:

```text
variant -> mathematical diagram work item -> editable HTML + reviewed PNG
-> same 变式题 row attachment + readback

Base selection -> immutable batch manifest -> formal practice Word with upper-right page code + visible number mapped to R01...
-> Agent/OCR observes returned scan -> retry_batch locates batch/page/item/source
-> append stable event -> authorized Base projection/readback

observed retry + teacher judgment -> preview -> append local event
-> update Base mastery/time or matching group feedback -> next targeted variation
```

## Scenario D: Teacher-Confirmed Grouped Student Mistake Records

### 1. Scope / Trigger

Use this contract after a reviewed original exists in `错题题目` and the teacher provides corrected-work evidence or a description of which students made which errors. The Agent records observed real responses before inference, then groups students who share the same suggested cause on the same question and assignment date. This is a Base/Skill projection only; it does not add student accounts, a student table, class relations or local FastAPI persistence.

### 2. Signatures

```text
python scripts/mistake_groups.py schema-check
python scripts/mistake_groups.py validate --input <group.json|->
python scripts/mistake_groups.py preview --input <group.json|->
python scripts/mistake_groups.py prepare-write --input <group.json|->
python scripts/mistake_groups.py write --input <group.json|->

```

`preview` and `prepare-write` never mutate Base. The Agent calls `write` only after explicit teacher confirmation. `write` performs an exact Base-side `系统记录ID` filter, creates or merges only the student multi-select, and verifies the result by readback; unchanged reruns return `no_change`. Raw correction evidence stays in the local source/event layer instead of a duplicate Base attachment column.

`--input` accepts standard input (`-`) or any readable relative/absolute JSON file path, including paths outside the current repository. Directory membership is not a validation condition. Missing, inaccessible or non-file paths return `input_unreadable`; malformed JSON returns `invalid_payload`.

### 3. Contracts

Input payload:

```json
{
  "questionRecordId": "rec_xxx",
  "questionLabel": "第2题｜面积单位选择问题",
  "assignmentDate": "2026-07-14",
  "errorCategory": "运算与计算",
  "students": ["学生代号A", "学生代号B"],
  "actualResponseSummary": "两人都把最后一个空填写为70。",
  "errorPattern": "没有进到下一个整十数。",
  "errorCause": "对最接近整十数的方向判断不稳定。",
  "sampleSize": 37
}
```

Base `错题记录` schema:

`错题记录` contains:

```text
记录名称          primary text: 日期｜可读题目名称｜错因摘要; no student names
对应学生          multi-select: exact roster names in identified mode; options ordered by private student number
对应错题          bidirectional link: exactly one 错题题目
题干图片          lookup: read-only 错题题目.题干图片 through 对应错题
核心素养          lookup: read-only 错题题目.核心素养 through 对应错题
作业日期          datetime
错误分类          single select
典型错例          text; one/few observed responses from this group, no student names
错误表现          text
错误原因          text; AI-proposed inference confirmed/corrected by teacher
本组人数          number; unique selected students; precision 0
掌握状态          select: 未开始 / 练习中 / 需再练 / 已掌握
再练反馈          text
最近再练时间      datetime
系统记录ID        text; no plaintext student names
备注              text
```

Question-side grouped-evidence projection:

```text
错题题目.典型错例  lookup: from 错题记录, select 典型错例, aggregate raw_value
错题题目.错误表现  lookup: from 错题记录, select 错误表现, aggregate raw_value
错题题目.错误原因  text: 原因：去重学生人数；原因：去重学生人数
```

Both lookups follow the existing `错题题目.学生错题记录` / `错题记录.对应错题` relation. They are derived cells and must never appear in metadata or group write patches.

`错误分类` is restricted to `审题与信息提取 / 概念理解 / 方法与策略 / 运算与计算 / 图形与表征 / 推理与表达 / 作答规范 / 其他/待判断`. OCR/vision provenance remains in local evidence and is not duplicated as a Base select field.

- One group row links exactly one reviewed question and may select multiple students. Students with the same error cause share a row; different causes create different rows.
- The same student may appear in several rows across questions, dates or distinct causes. Personal mistake sets are Base filters on the multi-select field, not separate physical tables.
- AI vision, PaddleOCR-VL and Yescan handwriting are evidence helpers. They may propose grouping and transcription; the Agent writes only after showing the full group and receiving explicit permission for the external mutation. No persistent second audit column is required afterward.
- Before mutation, show the linked question, date, observed real response, suggested cause, category, group count, complete selected-student list and evidence source. Rejected candidates are not written.
- When a class roster exists, match handwritten student number plus name and treat the roster as authoritative; Base stores the verified name only. Without a roster, AI visual reading is provisional and low-confidence mappings stay in private ignored evidence. Names never enter logs, test fixtures, primary values or deterministic system IDs.
- Optional Yescan identity assistance tiles only numbered name-and-student-number crops into one or a few readable contact sheets; never tile dozens of full homework pages.
- `系统记录ID` derives from question record, date, category and normalized error cause, not student names. The Agent uses an exact Base-side filter before create; an existing group receives a teacher-confirmed student merge instead of a duplicate row. It never relies on scanning only the first 200 rows.
- After group readback, the writer projects `统计批次`, `批改样本人数`, the unique student union as `错误人数合计`, ratio-valued `错误率`, `错误原因` with per-cause counts, high-frequency status and method back to `错题题目`. Base itself projects all linked group `典型错例` and `错误表现` values through read-only lookups. Count fields use precision 0. `错误率` stores `0..1` and the Base field displays a percentage with precision 1. Corrected-work high frequency is strictly greater than 35%. If `sampleSize` is absent, the writer sends explicit nulls for the previous denominator, rate, high-frequency flag and method; it must never leave a new error count paired with stale quantitative fields.
- `错题记录.典型错例` contains one or a few representative real answers but no names. `错误表现` describes the visible pattern; `错误原因` is proposed after the evidence and becomes durable only after teacher confirmation. The matching question lookups are derived views, not separate editable notes.
- Windows orchestration reads private Chinese JSON directly as UTF-8 or via structured UTF-8 files. It never pipes student-answer text through an unspecified Python-stdout/PowerShell encoding boundary, and every live text mutation rejects U+FFFD during readback.
- There is no `学生` table. Adding accounts, a class table, identity merging, permissions or statistics requires a new proposal.

### 4. Validation & Error Matrix

| Condition | Safe result | Mutation |
| --- | --- | --- |
| missing `错题记录`, wrong field type/options, missing reverse link/题干图片 lookup, invalid 典型错例/错误表现 lookup source, or wrong numeric display contract | `schema_mismatch` | none |
| independent `学生` table exists | `unexpected_student_table` | none |
| unknown error category or recognition method | `invalid_mistake_group` | none; no new fixed select option |
| empty/duplicate student selection | `invalid_mistake_group` | none |
| invalid date or question record ID | `invalid_mistake_group` | none |
| input path is missing/unreadable, or JSON is malformed | `input_unreadable` / `invalid_payload` | none; absolute paths outside the repository are otherwise allowed |
| candidate not teacher-confirmed for external write | preview only | no Lark write |
| stable key already exists with same error group | preview student merge | update only after confirmation; no duplicate row |
| stable key exists and teacher-maintained text differs | preserve the existing text | update only newly confirmed student options |
| exact stable-key filter returns multiple rows | `duplicate_system_record_id` | none; repair duplicate rows first |
| create/merge readback does not match the expected student set | `lark_readback_mismatch` | stop; rerun begins with the exact-key lookup |
| write command returns an upstream failure or timeout | safe Lark error | no blind write retry; rerun begins with the exact-key lookup |
| evidence attachment upload fails after row creation | keep confirmed row and report retry command | text/link state retained; attachment retryable |

### 5. Good / Base / Bad Cases

- Good: two students have the same observed calculation error on one reviewed question; the Agent proposes one group row with both students selected, the teacher confirms, and the reverse link shows one group.
- Base: one student has a different strategy cause on the same question; it becomes a second group row because the cause differs.
- Bad: create one duplicate row per student, store names in `典型错例`, write directly into question lookup cells, invent a new category named “粗心”, or mark a visual guess confirmed without teacher review.

### 6. Tests Required

- Payload unit: allowed categories/methods, ISO date, one-to-sixty unique students, exactly one question link, text length limits, and readable absolute input paths both inside and outside the repository.
- Identity unit: primary name and deterministic `系统记录ID` contain no student name; same question/date/category/cause yields the same key regardless of selected students or observed-response wording.
- Schema unit: multi-select students, single-select category, exact fixed options, bidirectional link and reverse field, read-only question-image/典型错例/错误表现 lookups, integer counts, and ratio-based percentage display; reject a `学生` table.
- Workflow unit: preview and prepare-write expose the same durable fields without an audit column; stable-key exact filtering, create/merge/no-change semantics, group-count readback, unique question-level counts, strict high-frequency threshold, and preservation of existing teacher text.
- Live smoke: private Base has exactly the three agreed business tables, final field readback passes `schema-check`, an unchanged rerun creates no duplicate group, and the schema smoke creates no student records.

### 7. Wrong vs Correct

Wrong:

```text
three students share one error -> create three duplicate rows
student names -> append to 典型错例 text
absolute JSON path outside cwd -> reject only because it is outside cwd
AI sees a red mark -> write 已确认 automatically
scan only the first 200 rows -> assume no stable-key match -> create
lookup guide is missing -> bypass the guard and guess nested JSON
```

Correct:

```text
reviewed question + corrected-work evidence
-> parse any readable relative/absolute JSON input; unreadable path -> input_unreadable
-> observed real response
-> AI proposes cause-based groups
-> teacher verifies category and student multi-select
-> exact stable-key filter -> create, merge students, or no_change
-> group and question-projection readback verification
-> reverse link shows the groups under the original question

create lookup -> read lark-base/references/lookup-field-guide.md
-> pass --i-have-read-guide
missing guide -> lark-cli update --force -> read guide -> retry
```

## Scenario E: Single-Student Precision Practice

### 1. Purpose And Boundary

Use this contract when a teacher asks Codex/Hermes to generate one printable practice sheet for one roster-verified student. The feature is a Skill-only projection over the existing `错题记录`, `错题题目`, and `变式题` tables. It must not add a student table, student account or class model; generation remains Base-read-only, while a later returned scan may create append-only retry events and an explicitly authorized current projection.

The private roster is the identity source of truth. Base keeps exact roster names only in `错题记录.对应学生`; the student number never enters Base, but the select-option catalog follows numeric student-number order so teachers can find names predictably. Personal-practice and retry commands resolve a private number to exactly one roster name before querying Base. Duplicate roster names fail closed instead of inventing a concatenated label. A single-student command and a whole-roster/subset batch command share one per-student selection service. Returned scans use `retry_batch.py`; AI/OCR observes evidence, but one correct answer cannot autonomously declare mastery.

### 2. Private Roster And Query

```json
{
  "students": [
    {"studentNumber": "01", "name": "Student A"}
  ]
}
```

- Both values are non-empty and unique. Duplicate numbers or duplicate names fail closed because Base stores names and cannot disambiguate them.
- The command accepts a student number, resolves exactly one roster row, then sends this server-side Base filter:

```json
{"logic":"and","conditions":[["对应学生","intersects",["resolved name"]]]}
```

- Student name, number, question text and attachment URLs must not appear in ordinary stdout or stable IDs.
- The roster, manifest, selection report and generated Word are private local artifacts and must not be committed.

### 3. Selection Contract

Default target count is six and the accepted range is `1..12`.

1. Aggregate all matching grouped mistake records by their single linked source question.
2. Exclude `已掌握` unless the teacher explicitly includes it.
3. Rank mastery as `需再练 > 练习中 > 未开始 > 已掌握`; within a tier prefer the newest assignment/retry evidence.
4. Round-robin across error categories within a tier so one category does not consume the entire sheet.
5. Select at most one original from every source question first.
6. If capacity remains, round-robin through complete, available variants of those same source questions.
7. Never pad with an unrelated question. If fewer eligible assets exist, return the smaller truthful count; if none exist, fail.
8. One question with several mistake rows remains one source candidate. Its highest-priority eligible mastery and newest matching evidence determine ordering.

Only reviewed originals with complete text/visual assets and `需人工处理=false` are eligible. A variant is eligible when it has one unique source relation, a non-empty stem and any declared image has been read back successfully; answer analysis remains optional. Invalid records are skipped and counted in the private selection report.

### 4. Manifest And Rendering

The planning command creates a new directory atomically and refuses to overwrite an existing directory:

```text
manifest.json       personal-practice-v2, flat ordered items, private identity and exact lineage
selection.json      private reason/evidence report for each selected item
images/             only the stem images used by this worksheet
```

New personal manifests contain exactly `batchCode`, `manifestVersion`, `student`, and continuous `items`. `student` contains exactly `name`, `studentNumber`, and `instanceCode`; the instance matches `S\d{3}` and is derived from the private roster order. The repeated header combines `batchCode-instanceCode-P` with Word `PAGE`, so physical pagination remains correct after natural flow.

- Title: `M月D日个人练习纸`.
- First page identity line: prefilled name and student number.
- Visible page code: `YYYYMMDD-NN-Sxxx-Pn`.
- The page code contains no name, student number, Base token, record ID, random suffix, URL, or QR payload.
- `R01...` remains globally continuous and maps to the exact original `questionId` or variant `variantId`.
- Standard `practice-sheet-v2` manifests reject `student`; `personal-practice-v2` manifests require it. V1 forms remain legacy-read compatible and are never emitted by new planning commands.

### 5. Commands

```powershell
python <skill-root>/scripts/personal_practice.py schema-check
python <skill-root>/scripts/personal_practice.py plan --roster <private.json> --student-number <number> --batch-code 20260715-01 --question-count 6 --output-dir <new-directory>
python <skill-root>/scripts/practice_sheet.py --manifest <new-directory>/manifest.json --output <new-directory>/personal-practice.docx
python <skill-root>/scripts/class_practice.py schema-check
python <skill-root>/scripts/class_practice.py build --roster <private.json> --batch-code 20260715-01 --question-count 6 --output-dir <new-class-directory> [--student-number <number> ...]
```

`schema-check`, `plan`, and class `build` are Base-read-only. The class command preserves full-roster `Sxxx` values even for a subset, caches schemas/catalog/assets in-process, and atomically creates one private root containing `batch-summary.json`, a UTF-8 BOM teacher CSV, and `students/Sxxx/{manifest,selection,Sxxx-个人练习纸.docx}`. A student with zero eligible assets receives `no_eligible_items` in the private list and no blank Word. Any technical failure removes the entire new temporary batch. Generating, printing, or sending the Word is a teacher-visible action and does not update mastery.

### 6. Failure Matrix

| Condition | Error | Mutation |
| --- | --- | --- |
| roster unreadable or malformed | `input_unreadable` / `invalid_roster` | none |
| student number missing or duplicated | `student_not_found` / `duplicate_student_number` | none |
| duplicate roster name | `ambiguous_student_name` | none |
| Base schema mismatch | `schema_mismatch` | none |
| no eligible personal questions | `no_eligible_questions` | none |
| output directory exists | `output_exists` | none; old snapshot preserved |
| attachment download fails | `attachment_download_failed` | temporary directory removed |
| manifest validation fails | `invalid_manifest` | temporary directory removed |

### 7. Tests Required

- Roster unit: deterministic `S001...`, duplicate number/name rejection, and exact student-number resolution.
- Query unit: exact `intersects` filter and no client-side full-library scan.
- Selection unit: mastery priority, recent evidence, category coverage, original-first, variant round-robin, no padding, default mastered exclusion, and duplicate-evidence aggregation.
- Output unit: private manifest/report/image materialization, atomic new directory, existing-output protection, anonymized visible page code, prefilled identity, and standard-manifest backward compatibility.
- Live read-only smoke: current Base passes all three table contracts and reports `personalPractice=ready` without creating or changing records.
- Visual smoke: render every sample page and verify title, identity, dynamic page code, question/image order, natural Word page flow, no artificial blank continuation page, and absence of clipping.

## Scenario F: Staged Multi-Page Corrected-Work Intake

### 1. Purpose And Boundary

Use this contract when one assignment produces more corrected pages than one stable Agent/OCR turn should handle. The feature is a private resumable evidence campaign; it does not add a Base table, student/class model, Provider router, automatic grader, cause inference, mastery mutation, or Base write.

One campaign binds exactly one private roster, one assignment code, and one rendered blank template. The blank question structure may be recognized once per template page. Corrected pages are used for handwriting, correction-mark and mathematical-result evidence only.

### 2. Page And Batch Contract

- Template and corrected pages are JPG/JPEG/PNG. PDF/Word must first be rendered through the existing source-routing path.
- Input paths may be readable absolute or relative paths anywhere the teacher authorizes. Campaign copies are immutable and all stored paths are relative.
- Template page numbers are continuous `1..N`. Every student submission must contain exactly the same complete set.
- Page budget defaults to 16 and accepts `4..24`. A student's complete pages are the minimum atomic unit and must never be split between batches.
- Campaign mutations use one cross-process lock for `add` and `complete`. Every writer reloads `campaign.json` only after acquiring that lock, so concurrent batches cannot revert another batch's completed state; lock timeout returns `campaign_busy` without changing campaign data.
- A roster student may appear at most once in one campaign. Each stored page records SHA-256, dimensions, anonymous `Sxxx`, batch `Bxx`, and final relative path.

### 3. State And Commands

```powershell
python <skill-root>/scripts/staged_intake.py start --roster <private.json> --assignment-code 20260715-01 --template <template-pages.json> --max-pages-per-batch 16 --output-dir <new-campaign>
python <skill-root>/scripts/staged_intake.py add --campaign-dir <campaign> --input <batch-pages.json>
python <skill-root>/scripts/staged_intake.py status --campaign-dir <campaign>
python <skill-root>/scripts/staged_intake.py complete --campaign-dir <campaign> --batch-id B01 --input <observations.json>
python <skill-root>/scripts/staged_intake.py export --campaign-dir <campaign> --output <new-export.json>
```

State is `pending -> completed`. Identical completion is `no_change`; a different second result is `batch_result_conflict` and never overwrites the first. `status` and ordinary command output contain counts only.

### 4. Observation Contract

Every batch result contains exactly the batch student set. An all-correct student is present with empty `findings`. Each finding contains only:

- `pageNumber`, `questionId`, `questionNumber`;
- non-empty `observedResponse` (`未作答` is explicit evidence);
- non-empty `markEvidence`;
- `result=incorrect|uncertain`;
- optional-content `note` as a required string field.

The finding payload rejects cause, category, mastery, Base fields and duplicate question IDs. Export may be partial but must report added/completed/remaining coverage, pending batches, and `isComplete=false`; callers must never describe it as full-class evidence.

### 5. Failure Matrix

| Condition | Error | Mutation |
| --- | --- | --- |
| damaged or unsupported page | `invalid_image` | no new campaign/batch |
| missing/mixed page set | `incomplete_student_pages` | no new batch |
| page budget exceeded | `batch_page_budget_exceeded` | no new batch |
| duplicate/unknown student | `duplicate_student` / `student_not_found` | no new batch |
| incomplete result student set | `invalid_batch_result` | batch remains pending |
| conflicting second completion | `batch_result_conflict` | first result preserved |
| export path exists | `output_exists` | old export preserved |

## Scenario G: Product Skill Bundle And Orchestration

### 1. Architecture

`shi-homework2lark` is the only discoverable user entry for the mistake-learning product. Collection, grouped mistake evidence, Base publication, variants, practice assembly and retry feedback are stages of one lineage-bound workflow, not independently triggered child Skills. Splitting them into sibling trigger descriptions would create ambiguous routing and duplicate the same Base/runtime contracts.

The package follows progressive disclosure:

```text
SKILL.md                         thin router, invariants, stage gates
bundle.json                      machine-readable package/dependency contract
references/orchestration-and-handoffs.md
references/*.md                 thick stage contracts loaded on demand
scripts/*.py                    deterministic operations
tests/ + evals/ + agents/       verification and Agent metadata
```

External domains remain external: Base operations use `lark-base` and its `lark-shared` rules; OCR routing uses `shi-ocr` and the selected MinerU/PaddleOCR/Yescan adapter; diagram work uses `wumu-jihe-html`. The package must not copy those Skills, their credentials or their vendor protocols.

### 2. Stage And Handoff Contract

The orchestrator supports five composable stages: `intake`, `mistakes`, `variants`, `practice`, and `feedback`. It first derives a minimal `[homework/task]` block and reads only the references and external Skill required by the selected stage. Cross-turn state is carried in readable blocks:

```text
[homework/task]
[homework/source]
[homework/questions]
[homework/mistakes]
[homework/base]
[homework/variants]
[homework/practice]
[homework/feedback]
```

Blocks carry stable local/business IDs, status, counts and private artifact references where necessary; ordinary chat summaries must not expose credentials, remote IDs, absolute paths or student data outside the teacher's private task context. A stage may resume from an existing valid block instead of restarting upstream work. Mutating stages keep their existing explicit teacher confirmation gates.

### 3. Dependency Doctor

`scripts/doctor.py` reads `bundle.json` and performs local discovery only. It may inspect sibling/global Skill roots, PATH command names and import availability, but it must not read credential values, authenticate, call a Provider, access Base, start Web/API or print discovered filesystem paths.

The report is structured JSON with overall `ready/degraded/blocked`, per-stage readiness and named missing dependencies. Missing an optional diagram or OCR path degrades only the affected stage/fallback; missing Python or the bundle's own required resources blocks the package. `--strict` returns a non-zero exit status unless the overall state is `ready`.

### 4. Build And Distribution

The project-local `.agents/skills/shi-homework2lark` directory is the development source of truth. A deterministic builder validates the manifest, scans text resources for credential/absolute-path leakage, excludes caches and private/runtime artifacts, and writes a standard `.skill` ZIP containing one top-level `shi-homework2lark/` directory. Rebuilding unchanged content yields the same SHA-256.

The 阿松 `shi-*` monorepo copy and user-level Agent/Codex/Claude installations are mirrors. Publishing uses explicit allowed target roots, a staging directory, atomic replacement and post-copy SHA-256 comparison. It never treats a mirror as a competing source and never silently includes unrelated dirty files.

### 5. Tests Required

- routing/reference test: one public entry, five stages, all handoff blocks and external delegation rules;
- doctor unit: ready, degraded and blocked fixtures; no network/credential/path output; strict exit behavior;
- manifest unit: declared internal resources and stage dependencies are valid and unique;
- package unit: deterministic archive hash, one root folder, cache/private/secret exclusion and no absolute machine path;
- mirror integration: project source, 阿松 monorepo mirror and installed copies compare equal by relative-path SHA-256;
- regression: all existing intake/Base/variant/practice/feedback tests continue to pass.
