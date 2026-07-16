# Capability Boundaries

## Current Capabilities

### `problem-intake`

Owns validated JPG/JPEG/PNG upload, immutable source storage, metadata/hash, manual-first teacher region selection, one optional configured automatic detection Provider, correction/editing of manual or multi-candidate detected regions, batch-confirmed canonical crops, and OCR per saved logical problem.

### `problem-review-and-correction`

Owns evidence display, append-only human revisions, review state transitions, current revision selection, and teacher-facing retry/error states.

### `mistake-record-storage`

Owns relational lineage, immutable machine/human versions, normalized record reconstruction, and future reuse eligibility.

### `reviewed-problem-publication`

Owns explicit publication of `futureReuseEligible` problems to the approved Lark Base projection, local retry status, stable-ID idempotency, and safe failure recovery. It does not own AI generation or make Base the evidence source.

### `agent-assisted-variant-reuse`

Owns the approved `shi-homework2lark` Skill/CLI flow: explicit Base selection, Agent-generated numbered variants, preview, append-only rows in the separate `变式题` table, a single genuine-exception queue, and available-only assembly reads. The original problem still passes local teacher review before Base publication; complete Base variants do not create a second routine approval state. It does not add an LLM Provider to the Web/API backend.

### `agent-assisted-problem-intake`

Owns the approved `shi-homework2lark` intake orchestration: images use Web manual handoff, chat Yescan candidate selection or one-question full-image intake; PDF/Word use Agent-level MinerU plus page rendering before entering the image-only FastAPI. It also owns OCR/revision/review commands, explicit publication, complete-question boundaries and teacher-confirmed Base metadata suggestions. It does not bypass FastAPI domain rules, claim direct PDF/Word API upload, make automatic detection mandatory, or store Provider/Lark/model credentials.

### `agent-assisted-learning-loop`

Owns optional variant diagrams on the same `变式题` row, delegation to the reusable `wumu-jihe-html` Skill, immutable Word assembly manifests with batch/page/item markers, user-selected collection-mode state, returned-scan page/item localization, append-only local retry events, and Base current feedback projection. AI/OCR may observe answers and teacher marks, but deterministic scripts only validate and map those observations. It does not add a backend image/LLM Provider, infer mastery from one correct answer, or add class analytics.

### `agent-assisted-student-mistake-groups`

Owns the approved `错题记录` Base projection. One row groups multiple teacher-selected students who share the same error category/pattern for one reviewed question and assignment date. In identified mode, `对应学生` contains exact names from the private roster and its options follow private student-number order; numbers stay outside Base and duplicate names stop. Anonymous or unresolved identity evidence remains private and is not written as a Base option. There is no `学生` table, account, class relation or local student database. The Agent may propose grouping, but it writes only after showing the full student selection, linked question, error category, observed-answer summary, diagnosis and evidence source for teacher confirmation.

### `agent-assisted-personal-practice`

Owns the approved teacher-side `shi-homework2lark` personal-practice slice: resolve one student from a private local roster, read that verified name's grouped `错题记录`, aggregate duplicate causes by source question, select a bounded explainable set of unresolved originals and available variants, and generate a local personalized Word manifest and worksheet. It does not create a student/class table, account, permission model, Base write, mastery decision, automatic grading, or class analytics. Personal identity remains in the private roster/manifest and printed sheet; only a batch-local anonymous `Sxxx` instance code appears in the page identifier.

### `agent-assisted-class-practice`

Owns the approved teacher-side batch wrapper around personal practice: iterate a private roster or an explicit student-number subset, reuse the exact per-student selection service, cache read-only Base assets, and atomically create one private batch directory with per-student manifests and Word worksheets. It does not create empty worksheets for students without eligible evidence, write selection results to Base, or add student/class persistence.

### `agent-assisted-staged-intake`

Owns a private, resumable intake campaign for one assignment: copy one rendered blank-page template once, add corrected student page sets in bounded batches without splitting a student, record hashes and batch status, and export completed observed-response findings for the existing teacher-confirmed mistake-group flow. It does not perform automatic grading, infer error causes as facts, write Base records, or accept incomplete/mixed page sets for one student.

## Hard Rules

- `ReviewedProblem` and student mistake facts are different concepts. The Base `错题记录` is a teacher-friendly grouping of multiple conceptual occurrences, never the question asset itself.
- OCR is input assistance; it cannot produce a reviewed/reusable problem.
- Original visual evidence is retained even when text exists.
- AI/Provider output must pass a teacher review gate before future reuse.

## Proposal Triggers

Automatic segmentation was authorized through the `intake-multi-ocr-lark-proposal` parent and is limited to one optional configured detection Provider plus teacher confirmation. Agent-level PDF/Word normalization and `wumu-jihe-html` diagram generation are authorized only by the current Skill task. Student labels are authorized only in the grouped `错题记录.对应学生` multi-select. Stop and create a proposal before adding a second active OCR Provider, multi-detection routing/voting, full PDF parsing inside FastAPI, a student/account/class table, class analytics, bulk/unreviewed AI classification, backend AI/image generation, vector search, queues, multi-tenancy/permissions, or a broad architecture rewrite.

A proposal records the problem, why it exceeds Phase 1, recommendation, data/stack impact, estimated cost, and target phase. It is not implementation authorization.

The `reviewed-problem-lark-reuse-loop` proposal was approved on 2026-07-13. Its publication child is limited to one configured `ProblemPublisher` (`fake` or `lark_cli`); its generation child remains Skill/Base-based and cannot add a backend LLM Provider, queue, or student workflow.

The `student-mistake-occurrence-expansion` proposal was partially approved on 2026-07-14 as a smaller Base-only slice: add one grouped `错题记录` table, use a multi-select `对应学生`, and do not add `学生`, `Submission`, local `MistakeOccurrence` persistence, accounts or class analytics.

The `student-personal-precision-practice` proposal was approved by the user's explicit development request on 2026-07-15. It is limited to one-teacher, read-only Base selection plus private local roster/manifest and Word output.

The `class-batch-practice-and-staged-intake` proposal was approved by the user's explicit request to continue development on 2026-07-15. It authorizes batch-wide generation and resumable, page-budgeted intake.

The `fully-automated-skill-intake-and-retry` proposal was approved by the user's explicit request on 2026-07-15. It authorizes a user-selected three-way collection entry and returned-scan page/item localization plus append-only retry events and Base current projection. It does not authorize student/class tables, autonomous mastery claims, a backend LLM Provider or broad analytics.
