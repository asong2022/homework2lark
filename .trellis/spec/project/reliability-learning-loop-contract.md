# Reliability and Learning Loop

## 1. Scope / Trigger

Use for first-use readiness, optional OCR, Base republishing/enrichment, private retry evidence and canonical packaging. Keep the Agent-only interface and four Base tables. No student table, Web client, automatic marking or cloud upload is implied.

## 2. Signatures

```text
POST /regions/{regionId}/revisions
  {recognitionSource: ocr|ai_vision|teacher, basedOnOcrRunId: string|null, correctedText: string}
POST /problems/{problemId}/publications/lark
GET /health -> status, database, runtimeId, configured providers
onboarding.py --repo-root . prepare|check|verify
personal_practice.py plan ... [--event-store class-private.jsonl]
class_practice.py build ... [--event-store class-private.jsonl]
retry_evidence.py context|summary --event-store ... --output ...
```

Migration: `0006_recognition_source`. Current feedback plan: `retry-feedback-plan-v2`; existing v1 plans and event IDs remain readable.

## 3. Contracts

- Recognition source defaults to OCR for old clients. OCR requires a same-region succeeded run; AI/teacher may have no run. Any explicit reference is validated. Never fabricate an OCR attempt. Historical OCR is not the selected baseline for an unrelated current AI revision.
- Migration preserves existing IDs/pointers and marks old revisions OCR. Downgrade refuses non-OCR evidence rather than losing it.
- Before any remote mutation, publisher compares question text, integer revision marker and source relation. Only known prior/current content may advance. Adopt a Base edit as a new local immutable revision before resync; matching text requires only marker advancement. Never overwrite teacher metadata/attachments blindly. These checks are not a remote transaction/CAS guarantee.
- Metadata apply captures and rechecks touched cells before each write. Report partial completion honestly if a later table conflicts.
- `prepare` migrates and starts only this repository's runtime, hidden on Windows. `check/verify` require migration head and healthy API with matching repository/database identity. Never kill an unknown listener. Missing OCR credentials do not block image intake. Report actual image/PDF/Word-input/Word-output capabilities separately.
- Match retry events to a class-scoped private roster by both name and number, never by `Sxxx` alone. Anonymous events do not personalize. Preserve all active error contexts for each original, and do not apply one student's result to a multi-student group.
- Individual planning consumes latest actionable feedback not older than assignment evidence; uncertain/unobserved observations remain context only. A single correct result does not imply mastered.
- Counts are attempts unless explicitly identified as unique students. Accuracy denominator is only correct+partial+incorrect; unknown/unobserved are separate. Category summaries reflect selection targets, not new diagnoses; overlapping category subtotals are not additive headcounts.
- Public `main` history is canonical. Private history is preserved separately, not rebased into public releases. Packages/install copies derive from the same checked source version; never maintain different code under the same version string.

## 4. Validation & Error Matrix

| Condition | Result | Preserved |
| --- | --- | --- |
| missing OCR baseline on OCR source | 422 | source/crop/prior revisions |
| AI/teacher with no OCR | revision saved, publication eligible | honest null baseline |
| unknown Base text/version/relation | 409 `lark_content_conflict`, no remote mutation | teacher edit + local revision |
| metadata changed since plan | `metadata_changed_before_write` | newly edited cells; prior partial result reported |
| absent/behind migration | readiness blocked; prepare action | existing data; read-only check creates no DB |
| occupied wrong runtime port | explicit runtime error | unrelated process untouched |
| no PDF/Word input renderer | capability requires renderer, not false ready | original material |
| one student feedback | private-only projection | other students/group state |
| uncertain/unobserved | append history, no mastery/time change | observation + previous valid result |

## 5. Good / Base / Bad Cases

- Good: no OCR Token, prepare a fresh local database, upload a question, save `ai_vision`, publish explicitly.
- Base: teacher changes Base text; republish stops, Agent adopts the edit locally, then syncs only the new marker.
- Bad: declare ready after checking a Token/file, run old code on the same port, infer student identity from S001, or mark 10 unreadable answers wrong.

## 6. Tests Required

- Recognition API roundtrip, invalid/cross-region references, old OCR preservation and safe downgrade refusal.
- Publisher no-op, known predecessor, teacher conflict with zero remote mutations, explicit adoption; metadata race check.
- Real isolated empty-DB prepare + healthy HTTP image/revision flow, repeated prepare reuse, unrelated-port protection.
- Same original/multiple causes, per-student isolation, stale vs actionable retry, uncertain/no-observation denominator, v1-to-v2 plan normalization and stable event IDs.
- Full backend/Skill checks, generated OpenAPI drift, package build/verify and tracked-artifact privacy scan. Isolated checks are not live Base/cloud OCR acceptance.

## 7. Wrong vs Correct

```python
# Wrong: fake provenance and leakage of an individual's outcome to the whole group.
revision = save(text, based_on_ocr_run_id="pretend")
group.mastery = individual_retry.mastery

# Correct: honest provenance; a class-scoped private event informs only that student.
revision = save(text, recognition_source="ai_vision", based_on_ocr_run_id=None)
events = load_private_class_events()
personal_plan = select(roster_student, all_error_contexts, events)
```
