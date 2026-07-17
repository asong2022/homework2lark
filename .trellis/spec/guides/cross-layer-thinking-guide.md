# Cross-Layer Thinking Guide

## Phase 1 Flow

```text
Teacher
  → Next.js feature state
  → typed API client
  → FastAPI schema/router
  → application service
  → Repository + Storage/OCR ports
  → SQLite + local files/Provider
  → normalized problem record
  → teacher evidence UI
```

For every changed field, trace both write and read directions through this whole path.

## Boundary Owners

| Boundary | Owner | Rule |
|---|---|---|
| File bytes → valid image metadata | upload application service | Decode bytes; never trust filename/MIME alone |
| Display rectangle → canonical crop | region service | Browser sends normalized coordinates; server validates and converts to source pixels |
| Vendor result → OCR contract | OCR adapter | Preserve raw JSON-safe output and expose normalized text/blocks |
| Database rows → public record | normalized-record assembler | Frontend never infers joins or current versions |
| Error → teacher message | API error mapper | Stable code and safe Chinese message; no vendor/path/secret leakage |
| Current revision → publication eligibility | publication service | Require a same-region non-empty revision plus complete source/crop/OCR lineage |

## Failure Walkthrough

At each arrow ask:

1. What has already been durably saved?
2. What is safe to compensate/delete?
3. Which IDs must remain so the teacher can retry?
4. What stable error reaches the UI?
5. What private content must stay out of logs?

Examples:

- Crop failure: keep source; create no region/problem row; delete only a newly partial crop.
- OCR failure: keep source, region, crop, and a failed OCR attempt; allow another run.
- Revision failure: keep all OCR runs and earlier revisions.
- Publication rejection: keep the current revision and explain the missing revision or lineage.

## Contract Change Checklist

- Update Pydantic schema/OpenAPI.
- Update `packages/contracts` and TypeScript projection.
- Update service/repository mapping.
- Update normalized-record example/spec if public shape changed.
- Update frontend rendering and error handling.
- Add round-trip test plus any relevant component/Playwright assertion.

Do not use local casts or duplicate transformations at consumers to “fix” a mismatched contract.
