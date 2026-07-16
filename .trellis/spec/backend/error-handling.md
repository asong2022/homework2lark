# Error Handling

## Stable Error Contract

All application, routing, and request-validation failures that enter the FastAPI exception chain become this JSON shape. A denied CORS preflight is the deliberate exception: Starlette owns its safe plain-text 400, while the outer request middleware still adds correlation.

```json
{
  "error": {
    "code": "invalid_region",
    "message": "框选区域超出原图范围，请重新框选。",
    "details": {},
    "requestId": "req_...",
    "retryable": false
  }
}
```

The `code` is stable and testable. `message` is safe, teacher-facing Chinese. `details` contains only corrective, non-sensitive values. The request ID links UI feedback to privacy-safe logs.

## Error Ownership

- Domain/application code raises typed `AppError` subclasses or instances with HTTP-neutral codes.
- FastAPI exception handlers map expected errors to status codes and the shared envelope.
- Unexpected errors return `internal_error`; never return stack traces, absolute paths, SQL, Provider tokens, or raw vendor responses.
- Provider adapters translate vendor exceptions into `OCRProviderError` categories: `unavailable`, `timeout`, `invalid_response`, and `configuration_error`.

## Required Cases

| Case | Response | Persistence rule |
|---|---|---|
| Malformed HTTP/multipart body | 400 | No mutation |
| Unsupported/corrupt/oversized image | 413, 415, or 422 | No asset row; compensate any partial file |
| Asset/problem/region missing | 404 | No mutation |
| Invalid/empty/out-of-bounds region | 422 | Source remains unchanged |
| OCR unavailable | 503 | Failed `OCRRun`, source, region, and crop remain |
| OCR timeout | 504 | Failed `OCRRun`, source, region, and crop remain |
| Empty OCR text | 201 with warning | Successful run; an already-reviewed problem remains reviewed, otherwise it stays non-reviewed |
| Invalid revision or missing correction | 422 | Prior OCR/revisions remain |
| Review without valid revision | 409 | Status remains non-reviewed |

## Retry Rules

- Retrying OCR is explicit and creates a new run ID.
- API errors must tell the frontend whether the operation can be retried.
- Never retry automatically inside the business layer in Phase 1; it would obscure run lineage.

## Avoid

- Catching `Exception` and returning a successful response.
- Returning `str(exc)` from third-party or database exceptions.
- Rolling back evidence written by an earlier successful step because a later step failed.
