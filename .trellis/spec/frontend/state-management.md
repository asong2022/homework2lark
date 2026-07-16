# State Management

## Categories

| State | Owner | Examples |
|---|---|---|
| Ephemeral UI | Component | drag start, current pointer, expanded raw response |
| Workflow | Feature hook/component | uploaded asset, selected bbox, region/problem IDs, pending/error states |
| Server record | API response | source asset, detection candidates, saved regions/crops/problem IDs |
| Navigation | URL | optional existing-source `assetId` |

Use React local state/reducer and URL state only. Do not add Redux, Zustand, Context-based global stores, or a server-state library in Phase 1.

## Intake State Machine

```text
empty → uploading/source_loading → source_ready → selecting → saving → completed
                                           └→ detecting → selecting
completed → supplement_selecting → saving → completed
```

An earlier successful stage is never erased by a later failure. Selecting a new file intentionally resets all later stages.
The `completed → supplement_selecting` transition preserves the server collection, shows its boxes read-only, and keeps only new editable boxes in the next batch request.

## Source-Page Restoration

```text
asset_loading -> source_ready + problem_collection_ready
  -> persisted_regions_readonly -> copy public IDs | continue framing
```

The canonical recovery key is public `assetId`. Reload `/intake/[assetId]` from `GET /assets/{assetId}/problems`; do not serialize crop URLs or private content into navigation state.

## Derived State

Compute save/detect/edit availability from authoritative IDs, request states, and current boxes. Do not maintain duplicate booleans that can drift.

## Privacy

Do not store image bytes, crop URLs, or problem IDs in `localStorage`, analytics, or URL query parameters. A page refresh reloads the source-page collection by `assetId`.
