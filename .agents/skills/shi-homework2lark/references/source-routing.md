# Source Routing

## Purpose

The public Skill accepts images, PDF, Word and teacher descriptions, while the local FastAPI upload endpoint still accepts only JPG/JPEG/PNG. Normalize every material into visual page evidence before creating problem regions.

## Routes

| Input | Structure extraction | Visual evidence | Next step |
|---|---|---|---|
| one-question JPG/PNG | optional AI/OCR | original image | `single` |
| full-page JPG/PNG | Yescan or AI preview | original page | `chat` or `web` |
| PDF | MinerU Markdown/JSON | render every selected PDF page to PNG | page-by-page `chat`/`web` |
| DOC/DOCX | doc render and optional MinerU | render to PDF, then page PNG | page-by-page `chat`/`web` |
| teacher description only | none | none | allow catalog draft only; request a question image before claiming visual completeness |
## Blank Template Plus Corrected Copies

When one blank worksheet/test is paired with many corrected copies, treat the blank page as the unique printed-question source:

1. render each blank template page once;
2. call Yescan AI Agent `scene=question-ocr` at most once per blank page when structured complete-question text is useful;
3. have AI/teacher align the returned structure with the visual page and confirm question numbers, complete boundaries, text choices and embedded visuals; if the response lacks reliable bbox data, confirm regions visually once rather than inventing coordinates;
4. register each corrected page to the blank template and reuse those regions;
5. inspect only handwriting, red marks and mathematical correctness on the corrected copies;
6. record observed responses before suggesting causes and grouping students.

Do not OCR the same printed stem once per student. For optional identity assistance, crop only the handwritten name-and-number area, add a local page label, tile readable crops into one or a few high-resolution contact sheets, and compare the result with the teacher-provided class roster. Never shrink dozens of full homework pages into one contact sheet.

For MinerU, default to `flash-extract` for files under its current limit; use authenticated precision extraction only when needed. Both are remote processing paths. Tell the teacher that document contents will be sent to MinerU before calling it.

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
- The teacher explicitly chooses which candidates are mistakes.
- When a candidate includes adjacent text and a diagram, preserve both inside one crop even if OCR exposes separate blocks.
- A `question-ocr` result is still a machine candidate. Preserve one logical question even when its text and visual are returned as separate blocks.
- If the crop is uncertain, use Web manual boxing or ask for a one-question screenshot.

## Failure Recovery

- MinerU fails: retain the original and try visual page rendering; do not claim extracted text.
- PDF render fails: stop the PDF route and request page images.
- Word render differs visibly: request PDF export from the teacher.
- Candidate detection fails: keep the page image and switch to Web/manual.
