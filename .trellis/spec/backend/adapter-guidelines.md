# Adapter Guidelines

## Ports

Application code may depend on two technology ports:

- `StorageAdapter`: write, read, delete, existence check, and (only when needed by a concrete local adapter) safe path resolution.
- `OCRProvider`: `name`, `model_name`, synchronous `recognize(OCRInput) -> OCRResult`, and required diagnostic `health_check()`.

Ports use domain/Pydantic contracts and opaque storage keys. They never expose FastAPI `UploadFile`, SQLAlchemy sessions, PaddleOCR result classes, or local absolute paths.

## OCR Contract

`OCRInput` includes source/region IDs, image bytes, language, and controlled options. `OCRResult` includes Provider/model/version, normalized text, aggregate confidence, ordered blocks, JSON-safe raw response, warnings, and processing time.

Every `OCRBlock` has `type`, `text`, `bbox`, `confidence`, `reading_order`, and JSON-safe metadata. A bbox is expressed in the cropped image's pixel coordinate system.

## PaddleOCR Adapter

- Dynamically import optional PaddleOCR dependencies so the API runs with the Fake Provider installed.
- Use PaddleOCR 3.x `PaddleOCR(...).predict(image)` behind the adapter.
- On Windows, initialize PaddleOCR with `enable_mkldnn=False`. Paddle 3.x oneDNN/MKLDNN may crash while converting PIR attributes before inference; do not re-enable it without a real Windows regression test.
- Convert `rec_texts`, `rec_scores`, and `rec_boxes`/`rec_polys` into ordered blocks.
- Prefer the SDK result's public `.json()` or `to_dict()` projection before treating it as a generic `Mapping`. PaddleOCR 3.7 result mappings include visualization-only objects such as `Font` that are not JSON serializable, while `.json()` is the vendor-supported evidence projection.
- Convert NumPy arrays/scalars recursively to JSON-safe lists/numbers before returning `raw_response`.
- Preserve the complete JSON-safe SDK result, including fields beside Paddle's nested `res`; parse a separate view for normalization rather than replacing the raw payload.
- Measure `processing_time_ms` from Adapter entry through image decode, lazy model initialization, inference, and normalization.
- Do not log or raise the vendor's raw response.
- Model download or runtime initialization failures become `configuration_error` or `unavailable`.
- The `paddleocr` optional dependency is required for a real run. First startup may download detection/recognition models into the user's Paddle cache; document that delay and never describe Fake output as real OCR.

## PaddleOCR-VL Official API Adapter

- Use the distinct Provider name `paddleocr_vl_api`; never pass `PaddleOCR-VL-1.6` to the local `PaddleOCR(...)` SDK constructor.
- Submit the teacher-confirmed crop as multipart to the HTTPS official Job API with model `PaddleOCR-VL-1.6`, then poll the authenticated job status until `done` or a total deadline.
- Read the Token from `PADDLEOCR_ACCESS_TOKEN` as a secret. Keep it out of object repr, raw response, logs, errors, tests, task artifacts, and frontend bundles.
- The optional payload defaults to `useDocOrientationClassify=false`, `useDocUnwarping=false`, and `useChartRecognition=false`.
- Download the returned HTTPS JSONL without forwarding the bearer Authorization header. Do not download remote Markdown/output images in this slice; the immutable local crop remains the visual source.
- Normalize `result.layoutParsingResults[].markdown.text` in Provider order into `OCRResult.text` and TEXT blocks. Preserve submission, every polled status, and parsed JSONL as JSON-safe private raw evidence.
- Reject non-HTTPS endpoints/results, non-finite JSON numbers, malformed JSON/JSONL, missing job/result fields, and unknown states as safe Provider errors.
- Map 401/403 or missing Token to `configuration_error`; 408/504 and total deadline to `timeout`; 429/5xx or remote `failed` to `unavailable`; malformed payloads to `invalid_response`.
- `health_check()` is configuration-only and network-free. Hosted OCR requires outbound HTTPS and a valid Token, but no local PaddlePaddle, GPU, or model weights.

## Fake Provider

- Must return the same `OCRResult` shape as a real adapter.
- Must be deterministic and require no network/model files.
- Tests may inject a failing fake; production routes must not expose test-only failure switches.

## Provider Selection

Use one configured Provider (`fake`, local `paddleocr`, or hosted `paddleocr_vl_api`) at process composition time. Do not add routing, fallback, voting, or parallel calls in Phase 1.

The application calls the synchronous port through a daemon worker and waits at most `OCR_TIMEOUT_SECONDS`. On timeout, the committed run becomes `failed`/`ocr_timeout`; a late SDK result has no persistence callback and cannot overwrite that terminal run. Do not claim that a Python thread cancels the native inference itself.

## Scenario: Yescan Question Detection

### 1. Scope / Trigger

Use this contract when a source page is sent to Yescan `RecognizeQuestion` to produce machine question-candidate boxes. Detection remains separate from OCR and from teacher-confirmed `ProblemRegion` creation.

### 2. Signatures

```python
ProblemRegionDetectionProvider.detect(
    RegionDetectionInput(
        source_asset_id: str,
        image_bytes: bytes,
        width: int,
        height: int,
        media_type: str,
    )
) -> RegionDetectionResult
```

Yescan standard API request:

```text
POST https://scan-business.quark.cn/vision
serviceOption=structure
inputConfigs={"function_option":"RecognizeQuestion"}
outputConfigs={"need_return_image":"True"}
```

### 3. Contracts

- Environment: `YESCAN_API_KEY_ID` is the `BACK_` client ID; `YESCAN_API_KEY` is a `SecretStr`; `YESCAN_API_BASE_URL` and `YESCAN_TIMEOUT_SECONDS` are non-secret configuration.
- Never use the `AI_` Agent credential for the signed backend API.
- Signature raw value is `clientId + "_vision_SHA3-256_" + nonce + "_" + timestamp + "_" + clientSecret`, encoded as lowercase SHA3-256 hex.
- Every request gets a fresh request ID, nonce, and millisecond timestamp. Image bytes exist as Base64 only inside the outbound request.
- Candidate coordinates come from group-level `StructureInfo.Position`, not individual OCR/detail boxes.
- Normalize exactly one `RegionCandidate` per `StructureInfo` entry. Multiple nested `Detail` entries for text, formulas, tables, or illustrations still belong to that one Provider question candidate.
- Do not split a `StructureInfo` by `Detail.Type`, and do not merge separate `StructureInfo` entries through local geometry, OCR numbering, or semantics. Provider split/merge mistakes stay visible for explicit teacher correction.
- Candidate boxes are displayed-source pixel coordinates. Accept them only when the single returned `ImageInfo` has angle 0 and width/height exactly equal to the source.
- Preserve the complete JSON-safe Provider response as raw evidence, but never log it. `need_return_image=True` is required for verified group coordinates and introduces large Base64 fields; the persistence owner must define storage before exposing a production endpoint.
- Candidate confidence averages only finite detail values inside `[0, 1]`. Ignore out-of-range vendor values and emit `provider_confidence_out_of_range`.

### 4. Validation & Error Matrix

| Condition | Safe category |
|---|---|
| missing/non-`BACK_` credentials or non-HTTPS endpoint | `configuration_error` |
| socket/HTTP 408/504 timeout | `timeout` |
| network/HTTP 5xx, quota or QPS error | `unavailable` |
| documented `A04xx` image rejection | `input_rejected` |
| non-`00000` unknown code or malformed JSON | `invalid_response` |
| missing group position, non-finite/out-of-bounds polygon | `invalid_response` |
| returned angle nonzero or dimensions differ | `invalid_response` |
| successful empty `StructureInfo` | success plus `no_candidates`; manual boxing remains available |

No safe error contains the vendor body, OCR text, absolute path, request Base64, signature, or credential.

### 5. Good / Base / Bad Cases

- Good: an unrotated page returns one group containing text and illustration details; the group becomes one adjustable machine candidate.
- Base: the Provider merges two calculations or splits one text-plus-image question into two groups; preserve the groups one-to-one and let the teacher adjust, supplement, or explicitly merge them.
- Bad: local code turns nested detail boxes into separate questions or silently joins adjacent groups. That changes Provider evidence into unreviewed segmentation guesses.

### 6. Tests Required

- Fixed-vector SHA3 signature assertion.
- Injectable transport assertion for service/function/output configs and absence of request secrets in `raw_response`.
- Success normalization assertion for candidate order, polygon-to-box conversion, confidence filtering, raw response preservation, and candidate count equal to `StructureInfo` count even when one group has multiple details.
- Parameterized vendor/transport error mapping without vendor messages.
- Angle, dimension, missing-position and out-of-bounds rejection.
- Explicit empty-result warning and network-free health check.
- A user-approved anonymous/synthetic real call before declaring a vendor response version supported.

### 7. Wrong vs Correct

Wrong:

```python
# Nested detail boxes are treated as questions or adjacent groups are silently merged.
candidates = [detail["Position"] for group in structures for detail in group["Detail"]]
candidates = auto_merge_adjacent(candidates)
```

Correct:

```python
validate_same_source_geometry(response["ImageInfo"], source_width, source_height)
candidates = [polygon_to_bbox(group["Position"]) for group in response["StructureInfo"]]
```

## Local Storage Adapter

- Resolve every storage key under the configured root and reject traversal.
- Write atomically via a temporary file and rename.
- Use immutable keys under `sources/` and `crops/`; never overwrite a source key with a crop.
- Keep database rows independent of host-specific absolute paths.
- `delete` exists for compensating only the key written by the current failed use case. Aggregate database/file deletion is a future task and is not exposed by Phase 1 HTTP routes.
