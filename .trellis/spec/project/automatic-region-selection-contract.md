# Automatic Region Selection Contract

## 1. Scope / Trigger

Use this contract only when the teacher explicitly chooses the Agent `chat` path with automatic candidates. `manual` and `single` never call detection. Detection remains an optional framing aid and never creates teacher-confirmed or reusable problems by itself.

## 2. Signatures

HTTP:

```text
POST /api/v1/assets/{assetId}/detection-runs
  -> RegionDetectionRunResponse

POST /api/v1/assets/{assetId}/regions/batch
  body: {
    coordinateSystem: "normalized_top_left",
    regions: [{ selectionSource, bbox, detectionCandidateIds }]
  }
  -> BatchRegionCreateResponse
```

Port:

```python
ProblemRegionDetectionProvider.detect(
    RegionDetectionInput
) -> RegionDetectionResult
```

Database migration `0002_region_detection` adds:

```text
region_detection_runs
region_candidates
problem_regions.selection_source
problem_regions.detection_candidate_id
```

Migration `0003_multi_candidate_lineage` adds:

```text
problem_region_candidate_sources
```

## 3. Contracts

- `REGION_DETECTION_PROVIDER` is `manual` or `yescan`; selection happens once at runtime composition, not per request. `manual` never fabricates candidates and returns an explicit configuration category if the optional detection endpoint is called. Test stubs live only under `tests/support` and cannot be selected from production configuration.
- A successful detection stores the complete JSON-safe Provider body under `provider-evidence/region-detections/{assetId}/{runId}.json`. The API never returns the body or its storage key.
- `RegionCandidate` stores one immutable Provider question suggestion. For Yescan this is exactly one group-level `StructureInfo.Position`; nested text, formula, table, and illustration `Detail` entries do not become separate candidates.
- Candidate count is not trusted as the final question count because the Provider may merge two questions or split one question across groups. The Adapter preserves this evidence one-to-one and the teacher decides which candidates are usable.
- Candidates initialize unselected in the Agent session. The teacher sees a numbered, reading-order list and explicitly chooses candidate IDs.
- The public `select` command creates one logical problem per selected candidate and preserves that candidate's original bbox and lineage. A candidate cannot belong to two saved logical problems.
- If one Provider candidate merges questions or several candidates split one complete question, the Agent does not guess a merge. It starts or reuses `manual` intake and records one teacher-confirmed complete bbox instead.
- Manual regions carry an empty `detectionCandidateIds` list. Detected regions carry exactly one candidate ID in the public Skill path. The backend's historical multi-candidate lineage remains readable for older records but is not a new Agent entry behavior.
- The batch API creates crops, problem assets, and initial domain events in one database transaction; the API itself does not start OCR. The Skill stops after this response, shows saved crop/public problem IDs in the conversation, and keeps downstream work explicit.
- Do not infer cross-candidate grouping with local geometry, OCR numbering, or semantic heuristics.

## 4. Validation & Error Matrix

| Condition | HTTP / code | Durable state |
|---|---|---|
| asset missing | 404 `asset_not_found` | no detection or regions |
| Provider timeout | 504 `region_detection_timeout` | failed run plus source retained |
| Provider unavailable/configuration | 503 `region_detection_provider_*` | failed run plus source retained |
| unsafe/mismatched coordinates | 502 `region_detection_invalid_response` | failed run; no candidates |
| successful empty candidate list | 201 plus `no_candidates` warning | success run; manual mode remains |
| empty batch | 422 `validation_error` | no crops or rows |
| duplicate/cross-asset candidate, including duplicates inside one composite | 422 `invalid_region_selection` | no crops or rows |
| any candidate already used by another logical problem | 409 `region_candidate_already_used` | existing problem retained |
| crop/database failure | 500 stable error | delete only new batch crops; keep source/detection evidence |

## 5. Good / Base / Bad Cases

- Good: when the teacher chooses `chat`, Yescan returns seven group-level candidates; the Agent presents them in reading order and persists only two independent questions selected by the teacher.
- Base: the Provider splits one text-plus-image question into two candidate boxes; the Agent rejects those candidates for publication and uses one teacher-confirmed `manual` bbox for the complete question.
- Bad: require automatic detection before manual framing, auto-select every candidate, or infer that adjacent candidates must be one question.

## 6. Tests Required

- Integration: successful/failed detection runs, private raw evidence, same-asset lineage, duplicate/reused candidate rejection, and file compensation.
- Contract: the manual production provider never returns candidates; injected test stubs and Yescan exercise the vendor-neutral result shape; Yescan candidate count equals `StructureInfo` count even when a group contains multiple `Detail` entries.
- Skill: default-unselected candidate list, unknown/duplicate selection rejection, one-candidate-per-problem payload and public-ID handoff.
- Agent path: upload → explicit `chat` detection → teacher selection → save batch → public-ID handoff; a bad split falls back to `manual` instead of inferred merging.
- Real proof: `image2.png` returns seven Yescan group-level candidates; `image1.png` enters `manual` without detection and accepts teacher-confirmed normalized boxes.

## 7. Wrong vs Correct

Wrong:

```python
# Provider suggestions are all persisted before the teacher chooses.
select(candidate_ids=all_candidate_ids)
```

Correct:

```python
persist_detection_evidence(provider_result)
teacher_selected = present_candidates_and_wait(provider_result)
select(candidate_ids=teacher_selected)
# If candidate boundaries are wrong, use one teacher-confirmed manual bbox.
```
