# Automatic Region Selection Contract

## 1. Scope / Trigger

Use this contract only when the teacher explicitly requests automatic candidates. Both standalone upload and the Skill-to-Web existing-asset handoff start manual-first; either may call detection as an optional framing aid. Detection never creates reviewed or reusable problems by itself.

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

- `REGION_DETECTION_PROVIDER` is `fake` or `yescan`; selection happens once at runtime composition, not per request.
- A successful detection stores the complete JSON-safe Provider body under `provider-evidence/region-detections/{assetId}/{runId}.json`. The API never returns the body or its storage key.
- `RegionCandidate` stores one immutable Provider question suggestion. For Yescan this is exactly one group-level `StructureInfo.Position`; nested text, formula, table, and illustration `Detail` entries do not become separate candidates.
- Candidate count is not trusted as the final question count because the Provider may merge two questions or split one question across groups. The Adapter preserves this evidence one-to-one and the teacher corrects it explicitly.
- UI candidates initialize unselected. Selection order is derived by final top-to-bottom/left-to-right bbox order.
- Teacher edits only the local final bbox. Batch confirmation stores the final pixel bbox on `ProblemRegion`; every original machine bbox remains unchanged on `RegionCandidate`.
- A detected logical problem requires one or more same-asset `detectionCandidateIds`; a manual region requires an empty list.
- Selecting two or more detected Provider boxes and invoking `合并为一题` creates one local composite region with the bbox union and stable de-duplicated candidate order. Saving it creates one crop, one `ProblemRegion`, and one problem ID.
- `problem_regions.detection_candidate_id` remains the first candidate for backward compatibility. `problem_region_candidate_sources` is the complete lineage owner, and one candidate cannot belong to two saved logical problems.
- The UI may delete a visible candidate, but this only removes it from current local editing state. Detection evidence and database candidates remain immutable. Display visible/original counts separately after deletion.
- The batch API creates crops, draft problems, and initial domain events in one database transaction; the API itself does not start OCR. The Web stops after this response, shows saved crops/public problem IDs, and returns downstream work to the Agent.
- Do not infer cross-candidate grouping with local geometry, OCR numbering, or semantic heuristics. A Provider split is corrected by the teacher through the explicit merge command.

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

- Good: when the teacher explicitly chooses automatic assistance, Yescan returns seven group-level candidates; the teacher selects two independent questions, moves one, adds one manual box, and saves three draft problems.
- Base: the Provider splits one text-plus-image question into two question boxes; the teacher selects both, merges them, and saves one draft problem with two candidate lineage rows.
- Bad: require automatic detection before a teacher can manually box a question, or delete immutable Provider evidence when removing a UI box.

## 6. Tests Required

- Integration: successful/failed detection runs, private raw evidence, one/multiple same-asset lineage, duplicate/reused candidate rejection, and file compensation.
- Contract: Fake and Yescan adapters return the same vendor-neutral result shape; Yescan candidate count equals `StructureInfo` count even when a group contains multiple `Detail` entries.
- Frontend: candidate decoding, default-unselected state, bbox union, explicit merge, manual add, move/resize geometry, delete, and batch payload.
- E2E path: upload → auto detect → correct a Provider split with explicit merge → add manual → save batch → public-ID handoff.
- Existing-asset handoff tests live under the `shi-homework2lark` contract and must prove that opening the route does not call detection, while an explicit teacher action can.
- Real proof: `image2.png` returns seven Yescan group-level candidates; `image1.png` loads through the existing-asset manual route without detection. Desktop and 390 px mobile views keep overlays aligned.

## 7. Wrong vs Correct

Wrong:

```python
# Provider suggestions are persisted directly as problems without teacher confirmation.
for candidate_id in selected_candidate_ids:
    create_region(candidate_ids=[candidate_id])
```

Correct:

```python
persist_detection_evidence(provider_result)
# Later, after the teacher confirms two Provider boxes belong to one question:
create_region(
    bbox=union_bbox(selected_provider_boxes),
    candidate_ids=stable_unique_candidate_ids(selected_provider_boxes),
)
```
