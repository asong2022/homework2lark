# Complete Question Asset Contract

## Identity

One logical elementary-math question becomes one `ProblemAsset`. Text and visual representation are components of the same asset, not separate questions.

```text
CompleteQuestion
  ├─ corrected question text
  ├─ options (when applicable)
  ├─ complete crop
  ├─ embedded visual fragments (optional derived assets)
  ├─ student response evidence (optional)
  └─ teacher diagnosis (optional)
```

The complete crop must retain every condition needed to solve the question: number lines, tables, geometry figures, statistical charts, grids, objects, answer blanks and labels. `题干图片` may provide a clean reusable visual, but never replaces `图片题目`.

## Detection And OCR

- Yescan `StructureInfo`/group is a candidate boundary, not an audited question.
- PaddleOCR-VL layout blocks and MinerU blocks are machine evidence. Never map each block to a separate problem row.
- Text, option and image blocks inside one candidate are assembled into one teacher-visible draft.
- Two independent numbered questions must not be merged merely because their boxes touch.
- Any split/merge that changes logical question identity requires teacher confirmation.

OCR supplies text and layout evidence; it does not have final authority over visual boundaries. For a dense full-page scan, keep the original-resolution page as visual truth and determine each complete-question and embedded-visual crop by direct inspection of source pixels.

## Deterministic Visual Extraction

1. Crop `图片题目` directly from the original-resolution page so it contains the complete stem, choices and every solving condition.
2. Extract `题干图片` separately from the same source pixels only when the problem has a reusable non-text visual. Do not redraw, regenerate or substitute an OCR-rendered approximation when the original is readable.
3. When the smallest complete rectangle necessarily overlaps a neighboring question, mask only the clearly foreign area with a plain background. Preserve every original line, label, long-division step, answer blank and image choice belonging to the selected question.
4. Inspect both assets locally at readable scale before upload. Reject clipped labels, missing conditions, neighboring-question text and accidental blank output.
5. After upload, download/read back both Base attachments and inspect them again. A successful API response alone is not visual verification.

The complete crop and stem image have different jobs: `图片题目` is the traceable original question, while `题干图片` is the clean non-text fragment used for reuse and layout. Neither may be inferred only from PaddleOCR block boxes.

## Complex Tables

A table remains inside the same `ProblemAsset`; rows, columns or OCR cells never become separate questions.

1. Keep the complete original crop as visual truth. When table layout itself is a solving condition, also keep the original table pixels in `题干图片`.
2. Put every reliably readable title, header, row/column label, unit, value and footnote into the teacher-confirmed text. Use a readable Markdown table when possible.
3. Preserve an original blank answer cell as `____`; do not silently remove it as OCR whitespace.
4. Represent merged or multilevel headers by repeating the parent label or using consecutive header rows. Keep the actual parent text: if `售出数量` spans `第一周 / 第二周 / 合计`, use `售出数量·第一周 / 售出数量·第二周 / 售出数量·合计`, or explicitly state that all three columns belong to `售出数量`. This is a readable approximation, never permission to omit or invent a relationship.
5. Distinguish a printed value, an intentional answer blank (`____`), and an unreadable cell (`[?]`). Mark an unreadable solving-critical cell as `[?]`, identify its row and column beside that source crop, and stop publication and variant generation until reliable evidence supplies the value. Decorative lines may be omitted from text, but grouping relationships may not.
6. With multiple photos, assess each photo before reconciling them. A clearer image of the same question may supply a missing value, but name that source; never describe an obscured cell as readable merely because another photo reveals its value. If only the obscured source exists, do not solve or publish using a guessed value.

Example:

```text
单位：千克
| 水果 | 第一箱 | 第二箱 | 合计 |
|---|---:|---:|---:|
| 苹果 | 12 | ____ | 30 |
```

Merged-header preview:

```text
题号：12
题干文本：水果店两周售出水果的情况如下，请补全表格。
单位：千克
| 水果 | 售出数量·第一周 | 售出数量·第二周 | 售出数量·合计 |
|---|---:|---:|---:|
| 苹果 | 12 | ____ | [?] |
说明：空白格填写苹果第二周售出的质量。
不确定项：苹果行的合计看不清，无法唯一确定第二周质量。
下一步：请提供合计值或清晰裁图；暂不发布、不生成变式。
```

The field preview keeps the outer number in `题号`; the reusable `题干文本` starts with the actual stem, not `12.`.

## Teacher Confirmation View

Show together:

1. source page with the selected region;
2. complete crop;
3. OCR raw/normalized text;
4. proposed corrected text, including choices;
5. embedded visual description;
6. optional student response and teacher diagnosis with source labels.

Teacher confirmation applies to the whole asset, not OCR text alone. Saving the confirmed correction makes it current; no separate review status is persisted.

## Base Projection

- one question row per ProblemAsset;
- `题目名称` is a short teacher-readable summary, not a numeric index or stable key;
- `题号` contains the outer printed question number;
- `题干文本` contains corrected text and all textual choices, but never repeats the outer printed question label such as `12.` or `第12题`;
- `图片题目` contains the complete crop;
- `题干图片` contains optional non-text visuals or image choices from inside the complete crop; it never creates another question row;
- `图表说明` describes the embedded visual without pretending it is the visual itself;
- `典型错例` and `错误表现` are read-only projections of grouped real evidence, not editable question metadata or retry history.

## Wrong / Correct

Wrong:

```text
text block -> question row A
diagram block -> question row B
```

Correct:

```text
text + options + diagram -> one complete crop -> one corrected question row
```

Also correct:

```text
题号 = 12
题干文本 = 学校把52本科普书平均分给4个班级……
```
