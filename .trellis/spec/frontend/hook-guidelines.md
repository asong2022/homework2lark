# Hook Guidelines

## Scope

Create a custom hook only when it owns reusable stateful workflow logic. Phase 1 should need at most focused hooks such as `useProblemIntake` and `useProblemRecord`; do not wrap every API call in a hook.

## Async Workflow Pattern

Each mutation tracks a discriminated state such as `idle | pending | success | error` and a teacher-facing `ApiError`. Do not represent unrelated upload, detection, and region-save operations with one boolean.

```ts
type RequestState<T> =
  | { status: "idle" }
  | { status: "pending" }
  | { status: "success"; data: T }
  | { status: "error"; error: ApiError };
```

Keep successfully created IDs in state across a later collection-refresh or clipboard failure.

## Data Fetching

- Phase 1 uses the typed API client and `useEffect` for one record load; no React Query/SWR dependency until cache sharing is a demonstrated need.
- Abort in-flight record reads on unmount or ID change.
- Mutations are user-triggered, not effects.
- After region save, use the returned batch or refetch the source collection explicitly; do not guess problem IDs.

## Dependencies and Cleanup

- Exhaustive hook dependencies are required.
- Stable callbacks use `useCallback` only when identity matters to a child/effect; do not add memoization by habit.
- Pointer listeners belong to React handlers or an effect with complete cleanup.

## Avoid

- Calling hooks conditionally.
- Swallowing `AbortError` and real API errors together.
- Running detection automatically in an effect merely because an existing-asset route opened.
- Calling OCR, revision, publication, or Base endpoints from the framing hook.
