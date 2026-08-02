# FastAPI Contract Snapshot

`openapi.json` is the committed public HTTP contract for the local FastAPI evidence service. It is
generated from application code and checked for drift by the backend contract tests.

```powershell
uv run --directory apps/api python scripts/export_openapi.py
```

Do not edit `openapi.json` by hand.
