# Frontend Quality Guidelines

## Required Patterns

- Strict TypeScript and Next.js App Router.
- Server components by default; add `"use client"` only to interactive feature boundaries.
- One typed API client, stable error display, and explicit pending/disabled states.
- Responsive layouts, visible keyboard focus, semantic labels/headings, and `aria-live` for async status.
- Teacher-facing copy describes framing, completion, and AI handoff in plain Chinese.

## Forbidden Patterns

- Direct `fetch` calls in components, `any`, hidden errors in console only, or guessed handoff IDs.
- Browser-generated crops treated as persisted evidence.
- Large UI/state/form libraries for the three-page MVP.
- Decorative dashboards, metrics, gradients, animated backgrounds, or generic card grids unrelated to the evidence workflow.
- Logging OCR/corrected text or image data to the browser console.

## Tests

- Component test: normalized rectangle calculation, clamping, and selection callback.
- API client test: success and stable error-envelope decoding.
- Route/component test: detection failure keeps the source and manual framing available.
- Component test: saving regions does not call OCR and returns only server-created public IDs.
- Playwright: upload PNG → manual/automatic framing → complete selection → verify crop/ID handoff and no review UI.

## Generated Route Types

After deleting App Router pages, regenerate route types with `next typegen`. If `tsc` still points only to deleted modules under `.next/dev/types/validator.ts`, restart the development server (or remove the generated `.next` cache) before diagnosing source code; the development validator is refreshed by `next dev`, not always by a production build alone.

## Review Checklist

- Can a teacher tell automatic candidates from manual boxes?
- Does every failed action explain how to recover without losing prior work?
- Are source image, editable overlays, selected count, saved crops, and public IDs visible at the required stage?
- Does the browser stop after selection instead of starting downstream AI work?
- Does the workflow remain usable at narrow desktop/tablet widths and with keyboard focus?
- Do lint, typecheck, unit tests, build, and Playwright pass?
