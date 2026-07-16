# Project Bootstrap Contract

## Adopted Trellis Level

- Profile: `llm-app`
- Preset: `standard`
- Adoption: L1 project specs plus L2 task planning
- Product phase: Phase 1 / MVP

## Pre-Development Checklist

1. Read `docs/bootstrap-assumptions.md`.
2. Read the active task artifacts.
3. Confirm the change stays inside one of the current capabilities, including the approved `reviewed-problem-publication` and Base-only `agent-assisted-student-mistake-groups` slices.
4. Read the backend/frontend index for every touched application.
5. If scope crosses a boundary in [Capability Boundaries](./capability-boundaries.md), stop implementation and write a proposal.
6. For the current cross-layer contract, read [Phase 1 Vertical Contract](./phase-one-vertical-contract.md).
7. When changing automatic candidates or batch region confirmation, read [Automatic Region Selection Contract](./automatic-region-selection-contract.md).
8. When publishing reviewed problems, read `../backend/publication-guidelines.md`.
9. When changing Agent-assisted intake, Web handoff, Base publication, variant generation, writeback, review, or assembly reads, read [shi-homework2lark Contract](./shi-homework2lark-contract.md).
10. When changing multi-format Agent intake, complete-question boundaries, variant diagrams, Word assembly, or retry feedback, also read the matching references under `.agents/skills/shi-homework2lark/references/` and keep `wumu-jihe-html` as a separate reusable diagram skill.

## Quality Check

- The shared flow is material normalization → complete-question selection → OCR evidence → AI/teacher revision → explicit review → explicit Base publication → Agent appends linked rows to the separate `变式题` catalog → complete output becomes available or a genuine exception is repaired → immutable batch manifest + Word assembly → retry feedback. Web handoff is manual-first; chat intake may use Yescan group-level candidates.
- In identified mode, only exact private-roster names appear in teacher-confirmed `错题记录.对应学生`; options follow private student-number order, while numbers remain outside Base and duplicate names stop the workflow. No student table/account, class relation/analytics, backend generation, queue, FastAPI PDF pipeline, multi-provider routing, or authorization platform was added.
- Architecture and product docs remain consistent with task contracts and executable tests.
