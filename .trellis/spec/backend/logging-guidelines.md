# Logging Guidelines

## Format and Context

Use Python `logging` with structured key/value context. Every request log includes `request_id`, method, route template, status code, and elapsed time. Workflow events include only relevant entity IDs, Provider name, safe status, and duration.

## Levels

- `DEBUG`: local diagnostic decisions without user content; disabled by default.
- `INFO`: upload metadata summary, region creation, OCR/revision/review state changes, and request completion.
- `WARNING`: expected invalid input, empty OCR output, or recoverable Provider failure.
- `ERROR`: unexpected infrastructure/application failure with request ID and exception class only. Do not include exception messages or traceback text at this boundary because SQL/SDK exceptions can embed private parameters.

## Never Log

- Image bytes, base64, complete OCR raw responses, or complete recognized/corrected/student-answer text.
- Student name, class, number, face data, or teacher annotation content.
- API keys, access tokens, request authorization headers, `.env` values, database URLs with credentials, or Provider client configuration.
- Absolute local file paths in client-visible responses.

## Safe Examples

Good event fields:

```text
event=ocr_run_finished request_id=req_... region_id=region_... run_id=ocr_...
provider=paddleocr status=succeeded processing_time_ms=842 text_length=36
```

Do not add `text=...`, `raw_response=...`, or `image_path=...`.

## Error Redaction

Provider adapters assign safe error codes. SQLAlchemy engines must use `hide_parameters=True`. The global handler logs only `request_id` and `exception_type`; it never interpolates `str(exception)` or `exc_info`. Keep detailed debugging behind a deliberately privacy-reviewed local mechanism rather than weakening this handler.

Storage compensation failures follow the same rule: log only `key_category` and `exception_type`, never `logger.exception`, the storage key, exception text, or traceback paths.

Regression test: `apps/api/tests/integration/test_error_privacy.py` injects a SQL error containing a sentinel teacher revision and asserts the text, SQL statement, and table/parameter details are absent from captured logs.
