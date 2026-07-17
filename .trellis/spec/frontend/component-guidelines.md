# Component Guidelines

## Design Direction

The product is a teacher's evidence desk, not a generic SaaS dashboard.

- Palette: paper white `#F6F8F5`, ink blue `#183153`, geometry blue `#2B63A9`, teacher red `#B83A3A`, graphite `#5D6873`, teacher green `#2F6B4F`.
- Typography: system Chinese sans-serif for body and controls; restrained KaiTi/STKaiti for the product mark only; tabular/system monospace for IDs and coordinates.
- Signature element: the source image with precise, numbered question boxes and a compact saved-crop handoff.
- Background may use a subtle squared-paper grid around the image workspace; never place it behind dense reading text.
- Motion is limited to pointer selection and status feedback; respect `prefers-reduced-motion`.

## Composition

Prefer small, named components with one job:

- `ImageRegionSelector`: pointer geometry and accessible selection summary.
- `MultiRegionSelector`: automatic/manual boxes, pointer editing, keyboard selection, and merge behavior.
- `ProblemIntake`: upload/existing-asset orchestration, region save, crop summary, and AI handoff.

Props use explicit `type XxxProps = { ... }`. Pass domain data and callbacks; do not pass whole hook return objects or raw API responses unless the component truly renders the full record.

## Image Selection

- Selection coordinates are derived from the image element's displayed bounding rectangle and stored locally as normalized top-left fractions.
- Clamp pointer coordinates to 0..1 and reject a zero/tiny rectangle before calling the API.
- Render a visible border/fill overlay and a textual summary of x/y/width/height.
- Select against the server-served source image. Keep EXIF-oriented display dimensions in the API record; never crop in the browser as the source of truth.
- For a source overlay, the positioned wrapper must shrink to the image's actual rendered rectangle. A full-width wrapper around a `max-height`/`object-fit` tall image misplaces percentage overlays.
- Prevent default image dragging while selecting and support pointer capture when available.

## Automatic Multi-Region Selection

- Automatic candidates initialize unselected; click or keyboard Enter/Space toggles selection.
- Selected numbering derives from current final bbox order and is not stored separately.
- One active box exposes drag movement, four corner resize handles, exact coordinate inputs, and deletion.
- Manual mode is one-shot: drag on the source to create one selected `manual` box, then exit manual mode.
- Keep machine and teacher state legible: detected boxes use geometry blue; manual boxes use teacher green; the original detection candidate remains immutable on the backend.
- Each Provider candidate initializes as one unselected question box. It is a machine suggestion, not a trusted final question count; never split it from nested OCR/detail metadata or silently regroup adjacent candidates in the browser.
- Selecting two or more Provider boxes enables `合并为一题`; replace them with one selected bbox union and preserve all candidate IDs in stable order.
- Label composites as `一道题（合并 N 个识别框）`. The logical selected-question count decreases after merge while the Provider source-box lineage remains intact.
- After deleting a local candidate or composite, show the retained/original Provider source-box count separately.

## AI Handoff Intake

- The Skill-generated `/intake/[assetId]` route loads the existing asset, starts with manual drawing active, and never reuploads it.
- Keep explicit automatic detection, select-all, clear, merge, manual add, move, resize, numeric editing, and deletion available. Detection is optional and never runs merely because the route opened.
- Saving a batch calls the region API once and stops. The browser must not invoke OCR, revision, publication, or Base operations.
- Reopening `/intake/[assetId]` reads the source-scoped problem collection, renders persisted boxes as a locked overlay, and displays saved crops plus public IDs. It may offer a deliberate “continue framing” action.
- The completed state offers `返回框题，继续补选`. Continuing starts an add-only pass: persisted boxes stay visible and read-only, only newly selected regions are submitted, and the next completion result contains the accumulated saved collection.
- Show only public `problem_*` IDs in the copyable AI handoff. Never copy storage keys, absolute paths, raw Provider responses, attachment URLs, Base record IDs, or credentials.
- The standalone `/` route is also manual-first. Its primary submit action uploads the image and immediately activates manual drawing without calling region detection.
- Keep automatic candidates as an explicit secondary compatibility path (`上传并自动检测` or `自动检测本页`). Product copy and tests must make clear that detection is optional, and a detection failure must return the canvas to active manual drawing without losing the uploaded asset.

## Forms and Copy

- Every input has a visible Chinese label and help/error text linked with `aria-describedby`.
- Buttons use the exact resulting action: `上传并手动框题`, `上传并自动框题`, `自动框题`, `手动框题`, and `完成选题 N 道`.
- Disable actions while the same request is pending and show a stable progress label.
- Preserve the uploaded source and teacher-adjusted boxes when detection or region saving fails.
- Do not use toasts as the only error/success channel; keep status next to the owning action.

## Styling

- Use one global CSS file plus semantic component classes; no CSS-in-JS or utility framework in Phase 1.
- Use CSS custom properties for the palette, type scale, spacing, radius, shadows, and focus ring.
- Keep content width/readability intentional; the image workspace may be wider than text panels.
- Responsive layouts collapse in source canvas → selected regions → saved crops order.

## Accessibility

- All interactive elements are native buttons/inputs/textareas where possible.
- Focus rings meet contrast requirements; status changes use an appropriate `aria-live` region.
- Images have contextual alt text, not filenames alone.
- Region selection also exposes numeric coordinates; pointer-only precision is not the sole evidence of selection.
