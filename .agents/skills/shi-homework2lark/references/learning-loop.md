# Learning Loop

## Assembly

Only separate `变式题` rows with non-empty `题干文本`, a valid source relation and a non-empty `设计意图` are eligible. Answer analysis is optional and never blocks a student-facing practice item. Use `variant_catalog.py list-available`; old same-row fields and the legacy `list-reviewed` alias are gone. Select explicit Base rows and never traverse the entire library by default.

Before creating a new row, follow [题生变式生成协议](variant-generation-prompt.md). The next generation uses the latest observed retry response and teacher judgment as targeted evidence, while keeping them distinct from the original problem and from unverified AI inference. A retry failure should change the next variation axis or trigger condition, not merely produce another set of substituted numbers.

For Word output:

- student section: numbered question text plus matching diagram;
- teacher section or separate file: same numbering with stored answer analysis where available; when explicitly requested, generate and verify missing answers on demand or clearly omit them;
- first freeze a local manifest containing a human-readable batch code, continuous page numbers, `R01...` item codes, source `questionId`, and exact `variantId` when applicable;
- new batch codes use `YYYYMMDD-NN`. The renderer derives the first-page title as `M月D日练习纸` and each visible page code as `YYYYMMDD-NN-Ppage`, for example `20260715-01-P1`. The page code appears once in a fixed borderless text box at the upper right; the footer contains only the page number. It is not a URL and carries no prefix, random suffix, template version, student identity, Base token or remote record ID. Template version remains in the local manifest. Agent/OCR reads the visible code directly; no QR image or decoder is required;
- follow [正式练习纸模板](practice-sheet-template.md): question text comes first, an optional stem image is placed below it and left-aligned, answer space follows, and Word auto-flow moves a whole question block only when the current page is actually full; do not pre-insert hard page breaks;
- do not write the assembled document back as a new original mistake question.

The renderer supports a common worksheet and personal precision worksheets. Personal selection follows [学生个人精准练习](personal-practice.md): a private roster resolves student number to one name, Base is filtered by that name, original mistakes are selected before related variants, and unrelated questions never pad the target count. `class_practice.py` reuses that exact service for a whole roster or an explicit subset, keeps `Sxxx` stable from full-roster order, caches repeated Base assets, and creates no blank worksheet for a student without eligible evidence. A returned scan is located in two stages: the printed upper-right page code identifies the immutable manifest and page, then the visible sequential question number maps to the manifest's `R01...` item and exact original or variant. Personal page codes add an anonymous `Sxxx` instance; only the private manifest maps it to name and student number. Keep the code high-contrast and inside the printable page margin. The template does not generate or depend on QR codes.

## Retry Feedback

Feedback distinguishes:

- `observedResponse`: what the child actually wrote/said/did;
- `teacherJudgment`: the teacher's diagnosis or uncertainty;
- `result`: correct / partial / incorrect / not_observed;
- `mastery`: 未开始 / 练习中 / 需再练 / 已掌握;
- `summary`: short teacher-facing Base summary.

The anonymous `learning_feedback.py` payload still rejects student name, class and ID. Question-level `典型错例` and `错误表现` remain read-only grouped-evidence lookups, and anonymous retry events append locally without rewriting them.

When the teacher deliberately identifies a student group, use the matching `错题记录` row instead: `对应学生` is a multi-select of exact roster names, while `再练反馈`, `掌握状态` and `最近再练时间` describe the current group result. Preview the full group and require confirmation before update. Do not create one row per student or an independent student table.

Example:

```json
{
  "questionId": "problem_xxx",
  "variantNumber": 2,
  "observedResponse": "把135°判断成锐角，并画成小于90°",
  "teacherJudgment": "角的大小与两边张开程度的表象仍混淆",
  "result": "incorrect",
  "mastery": "需再练",
  "summary": "变式2仍将135°判断为锐角；后续需加入直角参照与角度估测。"
}
```

Flow:

```text
validate -> preview (read-only) -> teacher confirms
-> append local event idempotently -> update mastery/time or the matching group feedback -> read back
```

For a returned image/PDF or a whole class batch, follow [再练回收自动定位与反馈](retry-feedback.md). The Agent/`shi-ocr` observes the page code, visible number, real response and correction evidence; `retry_batch.py` maps them to the exact manifest `questionId/variantId`, prepares conservative mastery projections and appends stable local events idempotently. `learning_feedback.py` remains the one-off teacher-described compatibility path. If Base projection fails after a local append, retry only the same stable event's projection.

## Next Generation

The next variant request may read the latest feedback. It should target the unresolved mathematical relation, not merely change numbers. AI-simulated evidence may inspire examples but cannot change mastery state without observed teacher feedback.
