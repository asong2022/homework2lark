# Code Reuse Thinking Guide

## Single Owners

Keep one owner for each cross-cutting concept:

- OCR and publication status values: backend domain enums; decoded once by the Skill client. Do not add a replacement review/readiness enum.
- Public ID generation: one backend ID helper.
- UTC creation/serialization: one backend time helper.
- Normalized-to-pixel conversion: one tested backend function; the Skill only produces normalized values.
- API base URL, JSON/error decoding, and endpoints: `.agents/skills/shi-homework2lark/scripts/intake.py`.
- Provider raw-to-normalized conversion: the concrete OCR adapter.
- Storage traversal protection and atomic writes: the storage adapter.
- Publication eligibility: one application service rule based on the current revision and complete lineage; it is not serialized as a boolean.

## Before Creating a Helper

Search with `rg` for the concept and its field names. Extract only when:

- the same invariant appears in two places,
- a boundary needs a single decoder/normalizer, or
- a focused helper materially improves unit testing.

Do not create generic `utils`, base repositories, service superclasses, Provider registries, or UI design systems for hypothetical future reuse.

## Contract Consistency

When adding/changing a public field, search backend schemas, normalized-record assembly, OpenAPI/contracts, Skill decoders and tests. A field is not complete if only one layer knows it.

When adding a new enum value, update every explicit Python match/branch. Fallback branches must reject unknown values rather than silently treating them as an existing status.

## Duplication That Is Acceptable

- A small Skill-side projection of fields needed for teacher-facing output is acceptable when checked by contract tests and kept at the HTTP boundary.
- Separate teacher-facing labels from backend enum values; conversational presentation belongs to the Agent layer.
- Test fixtures may repeat small valid records when it keeps the behavior under test obvious.

The goal is one owner per invariant, not abstraction for its own sake.
