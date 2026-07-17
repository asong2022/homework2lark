# Frontend Directory Structure

## Canonical Layout

```text
apps/web/src/
├── app/
│   ├── layout.tsx
│   ├── icon.tsx                         # Generated product favicon
│   ├── page.tsx                         # Teacher-selected upload + framing
│   └── intake/[assetId]/page.tsx        # AI handoff: existing-asset framing
├── features/problems/
│   ├── components/                      # Framing canvas and selection result
│   └── hooks/                           # Upload/detection/region-save state
├── lib/
│   ├── api-client.ts                    # Only HTTP boundary
│   └── contracts.ts                     # Shared API-facing types
└── test/
```

## Ownership

- `app/` files compose routes and own metadata; keep interactive workflow code in feature components marked `"use client"`.
- `features/problems/` owns upload, region selection, saved-crop summary, and public-ID handoff.
- `lib/api-client.ts` owns base URL joining, JSON/error decoding, multipart requests, and endpoint functions. Components must not call `fetch` directly.
- Keep component tests next to the feature or under `test/`; Playwright scenarios live in `apps/web/e2e`.

## Routes

- `/`: manual-first standalone upload workbench. The primary action starts manual boxing; an explicit secondary action can request automatic candidates.
- `/intake/[assetId]`: load an already uploaded `SourceAsset`, start with manual drawing active, optionally request automatic candidates, save one or more regions, and return public problem IDs to the AI conversation. It never reuploads the source.
- Both routes stop after region persistence. OCR, revision, publication, and Base work belong to the Agent conversation and FastAPI, not browser routes.

Do not add review/detail, library/list, dashboard, student, login, settings, or admin routes.

## Naming

- React component files and exported components use `PascalCase`.
- Hooks use `useXxx`; non-component modules and CSS classes use `kebab-case` filenames/names where practical.
- API JSON fields remain camelCase. Do not mirror database `snake_case` names in UI code.
- Event handlers state the action (`handleSaveRevision`) rather than DOM event (`handleClick`).

## Avoid

- A generic `components/` directory at repository root.
- Route files that combine upload, pointer geometry, HTTP calls, and rendering.
- Client-side Next route handlers used as a second backend; the browser talks directly to FastAPI through the typed API client.
