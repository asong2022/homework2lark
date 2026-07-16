# Frontend Development Guidelines

These rules govern the Next.js teacher-selected question framing tool in `apps/web`.

## Pre-Development Checklist

Read, in order:

1. `docs/bootstrap-assumptions.md` and the active task's `prd.md`, `design.md`, and `implement.md`.
2. [Directory Structure](./directory-structure.md) for route/feature ownership.
3. [Component Guidelines](./component-guidelines.md) for the selection and evidence UI.
4. [Hook Guidelines](./hook-guidelines.md) and [State Management](./state-management.md) for request/workflow state.
5. [Type Safety](./type-safety.md) for OpenAPI-facing contracts.
6. [Quality Guidelines](./quality-guidelines.md) before implementation and review.
7. `.trellis/spec/guides/cross-layer-thinking-guide.md` for end-to-end changes.

## Guides

| Guide | Owns |
|---|---|
| [Directory Structure](./directory-structure.md) | App Router and feature layout |
| [Component Guidelines](./component-guidelines.md) | Components, styling, accessibility |
| [Hook Guidelines](./hook-guidelines.md) | Async workflow hooks and effects |
| [State Management](./state-management.md) | Local/server/URL state boundaries |
| [Type Safety](./type-safety.md) | API contracts and runtime error decoding |
| [Quality Guidelines](./quality-guidelines.md) | Lint, tests, build, and UX gates |

## Quality Check

- Run `npm run lint --workspace @mistake-notebook/web`.
- Run `npm run typecheck --workspace @mistake-notebook/web`.
- Run `npm run test --workspace @mistake-notebook/web`.
- Run `npm run build --workspace @mistake-notebook/web`.
- Run the Playwright framing flow with the API configured to `fake`.
- Verify keyboard focus, visible labels, responsive layouts, detection recovery, and the AI handoff result.

Documentation under `.trellis/spec/` is English; teacher-facing UI copy is concise Chinese.
