# Source Routing

## Purpose

The public Skill accepts images, PDF, Word, teacher descriptions and baseline-new Quark wrongbook items, while the local FastAPI upload endpoint still accepts only JPG/JPEG/PNG. Normalize every material into visual page evidence before creating problem regions.

## Routes

| Input | Structure extraction | Visual evidence | Next step |
|---|---|---|---|
| one-question JPG/PNG | optional AI/OCR | original image | `single` |
| full-page JPG/PNG | Yescan or AI preview | original page | `chat` or `manual` + `frame` |
| PDF | optional AI/OCR/structure parser | locally render every selected PDF page to PNG | page-by-page `chat`/`manual` |
| DOC/DOCX | doc render and optional MinerU | render to PDF, then page PNG | page-by-page `chat`/`manual` |
| Quark wrongbook new item | private catalog sync; no OCR yet | authorized pending `original_image_url` downloaded temporarily | `quark_wrongbook.py collect-new` or selected `import` -> existing `single` |
| teacher description only | teacher text | none | preserve the description; request a question image before publishing a source-backed asset |

Quark wrongbook first use is special: `baseline` records every currently existing question ID as excluded and downloads nothing. Only IDs first seen later may become pending. A teacher request to “新增/收录今天或本次新增题” authorizes all pending through `collect-new` without a second item-by-item choice; “查看/列出新增” remains `sync/status` only, while explicit partial selection still uses `import`. Load `quark-wrongbook.md` before using this route.
## Blank Template Plus Corrected Copies

When one blank worksheet/test is paired with many corrected copies, treat the blank page as the unique printed-question source:

1. render each blank template page once;
2. call Yescan AI Agent `scene=question-ocr` at most once per blank page when structured complete-question text is useful;
3. have AI/teacher align the returned structure with the visual page and confirm question numbers, complete boundaries, text choices and embedded visuals; if the response lacks reliable bbox data, confirm regions visually once rather than inventing coordinates;
4. register each corrected page to the blank template and reuse those regions;
5. inspect only handwriting, red marks and mathematical correctness on the corrected copies;
6. record observed responses before suggesting causes and grouping students.

Do not OCR the same printed stem once per student. For optional identity assistance, crop only the handwritten name-and-number area, add a local page label, tile readable crops into one or a few high-resolution contact sheets, and compare the result with the teacher-provided class roster. Never shrink dozens of full homework pages into one contact sheet.

Local rendering and AI visual reading do not require MinerU, Yescan or PaddleOCR credentials. Consult onboarding capabilities before promising PDF/Word input support. If a renderer is unavailable, use an available document Skill or ask for page images; the source planner itself does not render documents. Optional cloud parsing follows the configured service and existing authorization. When using MinerU, follow its own Skill for current limits and mode; explain that contents leave the device before the first remote upload.

For Word, preserve the original file and render it rather than relying only on paragraph extraction. Tables, formulas, page breaks and embedded images may change the meaning of a question.

## SourceBundle

Agent workspace manifests may use:

```json
{
  "schemaVersion": 1,
  "sourceType": "pdf",
  "originalFileName": "作业.pdf",
  "privacyNoticeShown": true,
  "pages": [
    {
      "pageNumber": 1,
      "pageImagePath": "session/pages/page-001.png",
      "structuredTextPath": "session/mineru/page-001.md"
    }
  ]
}
```

Use only relative session paths in manifests. Do not include keys, tokens, image bytes, student identities, remote attachment URLs or local absolute paths.

## Selection Rules

- The visual page is the source of truth for layout and diagrams; structured text assists reading.
- A Yescan group is one candidate whole question. Do not split its nested detail blocks.
- Respect the chosen collection mode: teacher-selected questions, observed corrected-work mistakes, or authorized new Quark wrongbook items. Do not ask for redundant item-by-item selection when the scope is already explicit.
- When a candidate includes adjacent text and a diagram, preserve both inside one crop even if OCR exposes separate blocks.
- A `question-ocr` result is still a machine candidate. Preserve one logical question even when its text and visual are returned as separate blocks.
- If the crop is uncertain, ask the teacher for a one-question screenshot rather than guessing.
- For 1–20 images that already fit `single` or explicitly configured `chat`, use `intake_batch.py` and `batch-intake.md` to persist progress per image. Manual full-page selection continues through `manual + frame`; the batch wrapper does not enable detection implicitly.

## Failure Recovery

- MinerU fails: retain the original and try visual page rendering; do not claim extracted text.
- PDF render fails: stop the PDF route and request page images.
- Word render differs visibly: request PDF export from the teacher.
- Candidate detection fails: keep the page image and switch to `manual + frame`.
- No OCR token: use `recognitionSource=ai_vision` or `teacher` for a real non-empty revision; do not invent an OCR run.
- Quark private interface fails: keep the versioned local baseline/pending state and do not reclassify old items or silently import history.
