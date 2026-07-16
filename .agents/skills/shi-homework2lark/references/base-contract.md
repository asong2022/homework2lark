# Base Contract

## Purpose

The local mistake notebook keeps immutable source, OCR, revision, and review evidence. The Feishu Base `小学数学错题学习库` is the teacher and Agent reuse catalog. This Skill reads reviewed originals from `错题题目`; every generated variant is a separate row in `变式题` linked back to exactly one original. Legacy same-row variant fields have been migrated and deleted.

## Required Source Fields

| Field | Type | Rule |
|---|---|---|
| `系统题目ID` | text | Stable local `ReviewedProblem.id`; hidden exact business key. Legacy alias: `题目唯一ID` |
| `题目名称` | text | Teacher-readable one-sentence primary name; never used as the sync key. A numeric/`待整理题目·…` placeholder may be replaced by AI enrichment |
| `收录序号` | auto_number | Read-only stable insertion order. Existing and future rows are numbered automatically; sort ascending to restore collection order |
| `图片题目` | attachment | Original reviewed crop; optional only when text is complete |
| `题干文本` | text | Teacher-corrected original text, including textual choices; excludes the outer printed label stored in `题号` |
| `题干图片` | attachment | Optional non-text visual inside the question: table, diagram, number line, chart or image choices; never a second question |
| `标准答案` | text | Optional context |
| `核心素养` | multi-select | Single editable source of truth with the 11 agreed curriculum options |
| `对应知识点` | text | Optional context |
| `设计意图` | text | What mathematical relation, ability or representation the original is designed to reveal |
| `所属错题页面` | link | Exactly one physical source page; multiple questions may link to the same page row |
| `时间` | lookup | Read-only date selected from `错题页面.时间` through `所属错题页面` |
| `年级` | lookup | Read-only grade selected from `错题页面.年级` through `所属错题页面` |
| `页码` | lookup | Read-only value selected from `错题页面.页码` through `所属错题页面` |
| `错题来源` | lookup | Read-only value selected from `错题页面.错题来源` through `所属错题页面` |
| `本地修订版本` | number | Positive integer identifying the reviewed local revision projected by the publisher |
| `已审核时间` | datetime | Non-empty timestamp projected from the local reviewed problem |
| `需人工处理` | checkbox | The single Base exception flag. Normal catalog and generated content use `false`; only incomplete, contradictory or unresolved records use `true` |
| `典型错例` | lookup | Read-only raw-value lookup of all linked `错题记录.典型错例` values |
| `错误表现` | lookup | Read-only raw-value lookup of all linked `错题记录.错误表现` values |
| `错误原因` | text | Current readable cause-and-count summary projected from grouped records |

The variant-generation workflow may read these grouped-evidence projections for targeted teaching context but never writes them. The separate catalog-enrichment command writes only the approved empty metadata fields below.

## AI Catalog Enrichment

After an original is published, the Agent may fill these empty catalog fields through `base_metadata.py`:

- page: `页面名称`, `时间`, `年级`, `页码`, `单元`, `课题名`, `错题来源`, `页面主知识点`;
- question: `题号`, `题目名称`, `分区标题`, `题型`, `核心素养`, `对应知识点`, `图表说明`, `标准答案`, `答案备注`, `设计意图`.

Catalog enrichment never writes `典型错例`, `错误表现`, or `错误原因`. Without teacher-confirmed grouped evidence, the two lookups remain empty; the Skill must not fabricate a student response merely to populate them.

`错题来源` is restricted to `教材 / 作业本 / 试卷 / 其他`; `年级` is restricted to `一年级 / 二年级 / 三年级 / 四年级 / 五年级 / 六年级`. `题型` is restricted to `选择题 / 填空题 / 判断题 / 计算题 / 解答题 / 操作题 / 应用题 / 开放题 / 其他`. `核心素养` is restricted to `数感 / 量感 / 符号意识 / 运算能力 / 几何直观 / 空间观念 / 推理意识 / 数据意识 / 模型意识 / 应用意识 / 创新意识`. The Skill must not create new select options as a side effect of enrichment. Question-side `时间`, `年级`, `页码`, `错题来源` and all downstream `核心素养` fields are calculated lookups and must never be included in a downstream patch. Page/record `备注` remains an optional teacher escape hatch and is never AI-filled by default.

`preview` is read-only and exposes field names rather than cell contents or remote IDs. `apply` rejects the entire plan when any proposed field differs from a non-empty Base value. Empty values are filled and equal values are idempotent. A normal successful enrichment is immediately usable and does not create another review state. There is no broad overwrite flag. The Agent must independently solve before proposing `标准答案`, and may leave semantically inapplicable fields empty.

The local reviewed original remains the quality gate before Base publication. The publisher rejects an unreviewed problem before any Base write, then projects its stable problem ID, reviewed revision number and reviewed time. Inside Base, normal catalog enrichment and complete variants do not require repeated approval columns. Eligibility depends on that local review evidence, actual content completeness and the single `需人工处理` exception flag. The redundant Base fields `审核状态`, `是否待复核`, `AI整理状态`, and `举一反三状态` are not part of the schema.

## Variant Catalog

`错题题目` uses the reverse relation `关联变式题`; no separate selection checkbox is stored. A reviewed original with an empty relation is a candidate for new variants. Canonical generated assets live in `变式题`:

The Base contract owns storage and idempotency; pedagogical generation quality is owned by [题生变式生成协议](variant-generation-prompt.md). The Agent completes that fact card, variation design and independent quality gate before creating the JSON accepted by `variant_catalog.py`.

| Field | Type | Rule |
|---|---|---|
| `变式题名称` | primary text | Teacher-readable `原题名称｜变式题N` |
| `收录序号` | auto_number | Stable insertion order such as `V-001` |
| `来源错题` | bidirectional link | Exactly one `错题题目`; reverse field `关联变式题` |
| `变式序号` | number | Positive integer within the source original |
| `题干文本` | text | Required reusable question, including textual choices |
| `题干图片` | attachment | Optional visual that belongs to the same question |
| `答案解析` | text | Optional teacher aid; absence never blocks student use |
| `设计意图` | text | Required explanation of the variation axis and intended learning opportunity |
| `核心素养` | lookup | Read-only unique lookup from the linked original |
| `生成时间` | datetime | Creation time |
| `系统变式ID` | text | Hidden idempotency key derived from source stable ID plus normalized question text |

The question is the reusable asset and answer analysis is optional. A question-only row is valid and immediately reusable. A diagram is optional; text-only originals default to text-only variants, while a stem-image original gets a new diagram only when the variant still depends on a visual. The checked image is attached directly to the same row; no duplicate description or review-status column is stored.

Attachment upload uses `base +record-upload-attachment`; it is not an ordinary record CellValue. The row is created, its optional checked PNG is uploaded and read back, and the whole write fails if the declared local image cannot be materialized. Existing rows are never silently overwritten: an identical stable key is reused, an empty design intent may be filled, a conflicting stable key fails, and new content appends another row. Questions in one write request must also be unique after whitespace normalization; duplicate payload keys fail before any Base call, and an already-duplicated catalog stops instead of silently collapsing rows.

The old `错题题目.变式题1～5` groups were verified against the independent table and deleted. `variant_catalog.py migrate-inline` now stops with `legacy_schema_removed` so an old Agent cannot recreate the retired workflow.

## Retry Feedback Fields

- `掌握状态` (select): `未开始 / 练习中 / 需再练 / 已掌握`;
- `最近再练时间` (datetime).

Repeated retry events remain append-only local JSONL entries keyed by `系统题目ID` and optional variant reference. Question-level Base only keeps compact mastery/time projection; teacher-confirmed student-specific feedback updates the matching `错题记录.再练反馈` group instead. A Base current projection advances only when the incoming observation time is strictly newer; older or equal events remain in local history without regressing the current mastery/time. There is no independent student table and no duplicate question-level feedback summary.

## Grouped Student Mistake Records

The approved third table is `错题记录`. It is a teacher-facing grouped projection, not one row per student:

```text
one row = one reviewed question + one assignment date
        + one shared error cause + multiple selected students
```

Required schema:

| Field | Type | Contract |
| --- | --- | --- |
| `记录名称` | primary text | Human-readable `日期｜题目名称｜错因摘要`; never contains student names |
| `对应学生` | multi-select | Exact roster names only in identified mode; options follow numeric student-number order while numbers stay private |
| `对应错题` | bidirectional link | Exactly one `错题题目`; reverse field `学生错题记录` |
| `题干图片` | lookup | Read-only lookup of `错题题目.题干图片` through `对应错题`; never duplicates the attachment |
| `核心素养` | lookup | Read-only lookup of `错题题目.核心素养` through `对应错题` |
| `作业日期` | datetime | Assignment/observation date |
| `错误分类` | single select | One approved category |
| `典型错例` | text | One or a few representative real responses from this group, without student names; written before cause inference and never fabricated as fact |
| `错误表现` | text | Common observable error |
| `错误原因` | text | Shared inferred cause proposed by AI and confirmed or corrected by the teacher before write |
| `本组人数` | number | Count of unique values in `对应学生`; integer display with precision 0 |
| `掌握状态` | single select | `未开始 / 练习中 / 需再练 / 已掌握` |
| `再练反馈` | text | Current group feedback summary |
| `最近再练时间` | datetime | Latest group retry time |
| `系统记录ID` | text | Agent idempotency key without plaintext student names |
| `备注` | text | Optional teacher note; AI leaves it empty unless the teacher provides an essential note |

`错误分类` is restricted to `审题与信息提取 / 概念理解 / 方法与策略 / 运算与计算 / 图形与表征 / 推理与表达 / 作答规范 / 其他/待判断`. AI clusters are proposals only. Before the external write, the teacher sees the linked question, observed real-response summary, suggested cause, category, group count, selected-student list and evidence source. Confirmation authorizes the write itself; no second persistent `审核状态` column is created afterward. Rejected candidates are not written.

There is no `学生` table. The same student may appear in multiple group rows, and one question may have several group rows for different causes. Personal mistake sets are Base filters on the `对应学生` multi-select field.

Identity policy:

- when the teacher supplies a class roster, match page identity by student number plus name and treat the roster as authoritative;
- write only the exact verified roster name to Base and order options by student number; keep the number-to-name map and confidence in private ignored evidence, never in stable IDs or logs;
- if a roster contains duplicate names, stop because a name-only Base value cannot distinguish them;
- without a roster, AI visual reading may form a provisional private mapping. Low-confidence entries remain explicitly marked for later roster validation;
- optional Yescan assistance batches only numbered `姓名 + 学号` crops into one or a few readable contact sheets. Never shrink dozens of full homework pages into a contact sheet.

Question projection fields are read-only lookups `典型错例` and `错误表现`, plus writable summaries `统计批次`, `批改样本人数`, `错误人数合计`, `错误率`, `错误原因`, `是否高频错题`, and `高频判定方式`. `错误原因` formats each confirmed cause with its unique student count. `批改样本人数` and `错误人数合计` use integer display with precision 0. `错误人数合计` is the unique union of students across causes, not a sum that double-counts overlap. `错误率` stores a ratio in `0..1` and uses Base percentage display with precision 1; for example `8/37` is stored as approximately `0.2162` and shown as `21.6%`. For corrected-work batches, high frequency is strictly `错误人数合计 / 批改样本人数 > 35%`. When a grouped write has no `sampleSize`, it explicitly clears the previous sample size, rate, high-frequency flag and method so a new count can never be displayed with an old denominator; a later explicit teacher judgment is a separate write.

`mistake_groups.py` validates the live schema and prepares a deterministic `系统记录ID` from question record, assignment date, category and normalized error cause without student names. `prepare-write` never mutates Base. After explicit teacher confirmation, `write` asks Base to filter by that exact stable key instead of scanning a fixed first page. It creates only when absent; otherwise it updates only `对应学生` and `本组人数` with newly confirmed options and preserves all teacher text. It then rebuilds the question projection from all groups for the same question/date, reads back both group and question fields, and returns `no_change` for an unchanged rerun. Write failures are not blindly retried.

All JSON `--input` arguments accept standard input (`-`) or any readable relative/absolute path, including a file outside the current repository. The loader does not impose a working-directory boundary; unreadable files return `input_unreadable`, and malformed JSON returns `invalid_payload`.

On Windows, private JSON containing Chinese student work is read directly as UTF-8 or handed off through a structured UTF-8 file. Do not round-trip such content through Python stdout captured by PowerShell without an explicit shared encoding. Live mutation must read back all changed text and fail if U+FFFD or other replacement mojibake is present.

## Views

| Table | View | Required behavior |
|---|---|---|
| `错题页面` | `全部页面` | One source-page view with readable page metadata and related questions |
| `错题题目` | `错题库` / `错题图片` | Collection-order browsing; gallery keeps the complete question crop |
| `错题题目` | explicit term-and-grade priority view | High-frequency questions inside one named grade/date scope, error rate descending; never rank the lifelong archive without bounds |
| `错题题目` | `待生成变式` | `关联变式题` empty and `需人工处理=false` |
| `错题题目` | `已有变式` | `关联变式题` non-empty and `需人工处理=false` |
| `错题题目` | `需人工处理` | `需人工处理=true` only |
| `错题记录` | `错误分组` / `共性问题` / `按学生查询` / `再练跟踪` | Group causes, rank impact, filter by student and follow unresolved mastery respectively |
| `变式题` | `全部变式题` | Teacher-readable catalog, `收录序号` ascending |
| `变式题` | `可组卷` | `题干文本` non-empty |

Filters may return field IDs or names. Resolve IDs through the current field list before comparison; never hardcode them.

All teacher-facing question views keep `收录序号` visible immediately after the primary field and sort it ascending by default. A temporary interactive sort never changes this stable value.

## State Machine

```text
原题 `关联变式题` empty
  -> Agent preview (no Base write)
  -> explicit write: append one row per variant
  -> question-only or question-plus-answer row: immediately available
  -> declared diagram: upload/readback the checked image on the same row
  -> identical rerun: reuse same 系统变式ID, create zero rows
```

The exception queue is not a second approval stage. New generation is append-only; editing or deleting an existing catalog row remains a separate explicitly approved maintenance action.

## Atomic Write Boundary

One approved generation writes all new variant rows in a single batch-create call. Each row contains the source relation, variant number, required question, optional answer, required design intent, creation time and stable key. Diagram attachments remain separate guarded writes. Source relations update automatically through the bidirectional link.

After writing, the Skill re-lists the catalog and verifies every requested stable key, source relation, question, optional answer and design intent. A rerun produces `created=0` and reuses the existing rows.

## Lark CLI Compatibility

- Use only `lark-cli base +... --as user`; never shell-concatenate arguments.
- Resolve the Base by title and tables/fields/views from live responses on each process run; cache only in memory. Feishu may return both a direct Base and an app wrapper with the same title, so inspect every exact-title candidate and select the unique one whose live tables satisfy the current contract; never assume `title-resolve` returns a top-level `base_token`.
- Current record list/get envelopes are columnar: `data.fields`, `data.data`, and `data.record_id_list`. Validate equal row/ID counts before mapping.
- `+record-list --json` is an output-format shorthand, but `+record-get --json` is an input body flag. Use `+record-get --format json`; otherwise the local CLI returns `validation/invalid_argument` before reaching Base.
- `+record-upsert` updates only when `--record-id` is supplied; it does not search by business key.
- Error `800070003` means a mutation produced no change. Treat it as a no-op only after readback proves the target state already matches.
- Error `9499` or `1254291` is retryable. Automatically retry read-only commands with a short bounded delay; do not blindly retry writes.
- Before creating a lookup field, read the installed `lark-base/references/lookup-field-guide.md` and pass `--i-have-read-guide`. If the guide is missing, restore the official package with `lark-cli update --force`; do not bypass the CLI guard or guess the nested lookup condition payload.

## Privacy And Safety

- Never store tokens, API keys, Base tokens, field IDs, record IDs, or absolute user paths in the Skill source.
- Do not log full original/variant text, attachment URLs, or lark-cli stderr.
- Do not process the whole library without an explicit user scope.
- Ordinary intake, enrichment, generation and feedback commands do not delete records, fields, views, attachments, or original content. A separately authorized schema-maintenance task may remove a field only after exact dependency audit, dry-run and readback.
