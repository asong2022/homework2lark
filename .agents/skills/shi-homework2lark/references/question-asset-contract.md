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
