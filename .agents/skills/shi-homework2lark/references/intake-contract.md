# Intake Contract

## Purpose

The intake side of `shi-homework2lark` is Agent-first and orchestrates the existing local FastAPI plus a selection-only Web tool. The conversation receives images and teacher descriptions, then chooses a chat, single-image, or optional Web handoff. Web owns crop selection only; the Agent owns OCR, revision, quality gates and publication orchestration. FastAPI remains the only writer of local evidence; Lark Base receives only eligible catalog projections.

## Entry Modes

| Mode | Detection | Teacher action | Result |
|---|---|---|---|
| `web` | optional, only after explicit click | Open returned URL and use manual boxes or automatic candidates | Saved crops and public problem IDs copied back to the Agent |
| `chat` | configured real detection Provider | Agent shows numbered candidates; teacher explicitly selects IDs | One ProblemRegion/ProblemAsset shell per selected Provider candidate |
| `single` | none | Treat an already-cropped image as one whole-image problem | One manual full-image region |

The normal experience starts in the Agent conversation. `web` is a precision fallback when the teacher wants to edit the bbox; it is not a mandatory first step.

The Web route is `/intake/{assetId}`. It loads the existing SourceAsset and must not upload a duplicate. It starts manual-first and also offers an explicit automatic-framing action; opening the route alone never calls detection.

One Yescan `StructureInfo`/group remains one candidate. The chat client never splits nested detail blocks or silently combines adjacent candidates. Text, choices and an embedded diagram inside the same group remain one complete question asset. Use Web for bbox editing or deliberate teacher-confirmed split/merge. Clicking `完成选题` saves regions/crops and ends the Web stage; it must not start OCR or navigate to browser review/detail/publication pages.

## Session Files

Session/selection outputs use schema version `1` and contain only:

- mode and public local asset/problem/region/run IDs;
- source file name, media type and dimensions;
- local API evidence paths and Web handoff URL;
- normalized/pixel candidate bboxes, reading order and confidence;
- configured Provider/model names and safe warnings.

They must not contain absolute input paths, image bytes/base64, storage keys, file hashes, Provider raw responses, API keys, Base tokens, attachment URLs/tokens, Lark record/field/table IDs or full CLI stderr.

Input images and existing JSON input/session files may use any readable relative or absolute user path, including paths outside the current repository. Generated session, selection and evidence output paths stay under the current working directory so the Skill does not scatter new artifacts without an explicit destination workflow. `-` is allowed only for JSON stdin.

## Command Contract

```text
health
start --file <jpg|jpeg|png> --mode <web|chat|single> --output <relative-json>
select --session <json-path> --candidate-id <id>... --output <relative-json>
ocr --problem-id <problem_xxx>
get --problem-id <problem_xxx>
save-revision --problem-id <problem_xxx> --input <json-path|->
publish --problem-id <problem_xxx>
download-evidence --problem-id <problem_xxx> --output-dir <relative-dir>
validate-metadata --input <json-path|->
base_metadata.py preview --input <json-path|->
base_metadata.py apply --input <json-path|->
```

`start chat` checks the configured detection Provider before upload. OCR uses the API's configured real Provider; production configuration does not expose a Fake OCR option.

`get` and `ocr` deliberately expose selected OCR/corrected text to the current Agent for teacher confirmation, but omit raw Provider response and private storage fields. `publish` omits remote record/table/field IDs from CLI output.

## Revision And Publication Gate

Revision input contains only:

```json
{
  "questionNumber": "12",
  "correctedText": "教师确认后的完整题目",
  "correctionNote": "可选说明",
  "basedOnOcrRunId": "ocr_xxx"
}
```

`questionNumber` is an optional local normalization hint and is not sent to FastAPI. When present, `save-revision` removes a matching outer prefix such as `12.`, `12、` or `第12题：` from `correctedText`; it never removes a different number or a content-leading quantity such as `24支铅笔`. The same value is written separately through question metadata field `题号`. Agents should provide it whenever the source has a visible outer question number.

`basedOnOcrRunId` may be omitted only when the current normalized record has a latest OCR run. Every save appends a ProblemRevision. It never edits `OCRRun.text`.

Saving the revision makes it the current version immediately. There is no separate review command or review-status transition. Publication remains a separate external write and the API rejects a problem without a valid current revision, source, crop or OCR basis.

## AI Metadata Boundary

The calling Agent may suggest page fields (`页面名称`, `时间`, `年级`, `页码`, `单元`, `课题名`, `错题来源`, `页面主知识点`, `备注`) and question fields (`题号`, `题目名称`, `分区标题`, `题型`, `对应知识点`, `图表说明`, `标准答案`, `答案备注`). Suggestions must be previewed beside the source/crop/corrected text. Question-side `时间`, `年级`, `页码` and `错题来源` are read-only lookups from the single linked page. Text choices remain inside `题干文本`; non-text choices and diagrams use `题干图片`, while `图片题目` keeps the complete crop.

`典型错例` and `错误表现` on the question row are read-only lookups from teacher-confirmed `错题记录` groups. Metadata enrichment never writes them and never fabricates a fallback student response.

When the teacher provides identities for a corrected assignment, prefer matching handwritten student number plus name against the private class roster and store the exact verified roster name only. Base options follow roster-number order, but student numbers remain private. Without a roster, AI visual reading is provisional and uncertain entries stay in a private exception list. After the corrected question exists in Base, the Agent first records visible real responses, then groups students with the same suggested cause and proposes one `错题记录` row per group. `对应学生` is multi-select, and every group requires a teacher-confirmed batch write.

Confirmed enrichment fills empty Base cells only by default. A non-empty cell is a conflict; replacing it requires a separate explicit confirmation. Enrichment failure cannot modify local evidence or undo a successful publication.

The validator accepts only `problemId`, optional `note`, page fields (`页面名称`, `时间`, `年级`, `页码`, `单元`, `课题名`, `错题来源`, `页面主知识点`, `备注`) and question fields (`题号`, `题目名称`, `分区标题`, `题型`, `对应知识点`, `图表说明`, `标准答案`, `答案备注`). It cannot propose system IDs, attachments, corrected text, review state, grouped-evidence lookups, lookup values or variant cells. It may replace only a numeric or `待整理…` primary-title placeholder; other non-empty teacher titles remain conflicts.

`错题来源` must be one of `教材 / 作业本 / 试卷 / 其他`; `题型` must be one of `选择题 / 填空题 / 判断题 / 计算题 / 解答题 / 操作题 / 应用题 / 开放题 / 其他`. Unknown values are rejected instead of silently adding a Base select option.

After successful publication, metadata enrichment is a standard completion step. `base_metadata.py preview` resolves the current question by hidden system ID plus its single linked page and returns only changed/unchanged/conflicting field names. `apply` requires a conflict-free plan, fills empty cells, and performs readback. Equal values are idempotent; different non-empty values block all writes. A normal enrichment is immediately usable and does not create a second persistent review task.

AI should fill every reliably derivable catalog field, but must not fabricate diagrams, textbook editions, answer evidence or knowledge labels. `图片题目` remains the complete text-plus-visual crop; `题干图片` is only an optional separately extracted non-text visual and never a second problem.

For scanned pages with embedded diagrams, PaddleOCR text/layout output and local visual inspection may run in parallel, but their authority differs: OCR supplies text evidence; the original-resolution page supplies visual truth. Crop both attachments from original pixels, mask only clearly foreign neighboring-question areas when unavoidable, preview locally, upload, then download/read back and visually verify both Base attachments.

## Failure Recovery

- Upload failure creates no source; retry the same input.
- Detection failure retains a successfully uploaded SourceAsset when the API returned one; switch to Web/manual if appropriate.
- Region/OCR failure retains source, selected bbox, crop and prior runs. Retry by the same public ID.
- Revision failure retains OCR and earlier revisions.
- Publication rejection retains the revision and reports which required source/revision fact is missing.
- Publication failure retains the corrected local asset. Retry the same problem ID; hidden IDs prevent duplicate questions and exact source-file hashes prevent the same image bytes from creating another page row.
- Direct `intake.py start` returns `source_requires_page_images` for PDF/DOC/DOCX because `/assets` accepts images. The public Skill supports them by first using MinerU plus PDF/doc rendering to produce page images as defined in `source-routing.md`; never pretend the image API directly stored the original document.

## Staged Corrected-Work Campaign

When one assignment has many corrected pages, use `staged_intake.py` and the full [staged intake contract](staged-intake.md). This is a private evidence/progress layer before the existing mistake-group preview and confirmed Base write.

- One campaign freezes one rendered blank template, one private roster snapshot, and one assignment code.
- Default budget is 16 pages, configurable from 4 to 24. One student's complete `1..N` page set is atomic and never split across batches.
- `start/add/status/complete/export` are resumable local operations. Input page paths may be any readable absolute or relative path; campaign files store copied evidence and relative paths only.
- A batch result contains observed response, correction-mark evidence, linked question/page, and `incorrect/uncertain` only. An all-correct student appears with empty findings.
- Error cause, category, mastery, grouping and Base mutation remain later Agent/teacher actions. A completed batch is append-only: identical retry is a no-op and a conflicting retry is rejected.
- Ordinary stdout contains counts only. Roster, names, numbers, paths and responses remain in private campaign/export files.

## Provider Boundary

The Skill never supplies an OCR Provider per request. Provider selection remains process configuration in FastAPI. The current real OCR path is the hosted PaddleOCR Job API with model `PaddleOCR-VL-1.6`; Yescan supplies conversational whole-question candidates. For a blank-template plus many corrected copies, the preferred path makes at most one Yescan AI Agent `scene=question-ocr` call per blank template page and reuses those complete-question regions after local page registration. MinerU is a Skill-level PDF/Word structure path before page images enter FastAPI. No automatic voting, concurrent Provider comparison or silent fallback is allowed.
