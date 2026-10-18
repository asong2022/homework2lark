# Local Development Launcher

## 1. Scope / Trigger

Use this contract when changing the Windows double-click launcher, local dependency preparation, port 8000, or the command that starts the FastAPI evidence service. The product has no Web frontend; the launcher prepares and starts only the API required by Agent/Skill intake.

## 2. Signatures

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start-local.ps1 `
  -Mode <bootstrap|api|prepare> `
  [-TimeoutSeconds 10..600]
```

Runtime command:

```text
uv run --directory apps/api uvicorn --app-dir src mistake_notebook_api.main:app --reload --port 8000
```

## 3. Contracts

- `bootstrap` is the teacher-facing path: validate `uv`, preserve or create `.env`, synchronize API dependencies when `uv.lock` changes, migrate the database, start one visible API log window, wait for `/api/v1/health`, and report that the teacher can return to the AI conversation.
- `prepare` performs dependency synchronization and migration without starting a service.
- `api` starts the foreground API process and leaves its log visible.
- Port 8000 is fixed. The launcher never kills an existing listener or silently chooses another port.
- Existing `.env`, SQLite data, storage, uploads and credentials are preserved. A missing `.env` is copied from `.env.example`, whose OCR default is hosted `PaddleOCR-VL-1.6`.
- Dependency preparation is keyed by the SHA-256 of `apps/api/uv.lock` and uses `uv sync --all-groups --inexact`, preserving any installed optional local OCR dependencies; no Node/npm or root JavaScript workspace is installed.

## 4. Validation & Error Matrix

| Condition | Result | Existing data |
|---|---|---|
| `uv` missing | clear install hint | unchanged |
| port 8000 occupied in bootstrap | stop before spawn | unchanged |
| dependency sync fails | non-zero exit with visible reason | `.env`/data retained |
| migration fails | non-zero exit; API not started | database file retained for diagnosis |
| API exits or health times out | identify API failure and log window | data/storage retained |

## 5. Good / Base / Bad Cases

- Good: a first-time user launches bootstrap, dependencies and migrations complete, one API window opens, health passes, and the terminal says to return to the AI conversation.
- Base: an experienced Agent uses `prepare`, then manages the API process itself.
- Bad: require Node/npm, start a browser, recreate `.env`, delete data, start a removed Web service, or silently use a different port.

## 6. Tests Required

- Parse the script with PowerShell and confirm only `bootstrap|api|prepare` are accepted.
- Run `prepare` in a disposable environment and verify the migration reaches head without changing an existing `.env`.
- Start bootstrap in a disposable environment and assert `/api/v1/health` succeeds.
- Run backend quality gates after launcher/config changes.

## 7. Wrong vs Correct

Wrong:

```text
install npm workspace -> start API + removed Web -> open browser
```

Correct:

```text
preserve config/data -> sync API -> migrate -> start API -> return to Agent conversation
```
