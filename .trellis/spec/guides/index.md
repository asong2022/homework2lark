# Shared Thinking Guides

Read these guides before any cross-layer Phase 1 work.

| Guide | Use when |
|---|---|
| [Cross-Layer Thinking](./cross-layer-thinking-guide.md) | A field or behavior crosses browser, API, service, repository, database, storage, or Provider |
| [Code Reuse Thinking](./code-reuse-thinking-guide.md) | Adding contracts, status values, IDs, coordinate helpers, API calls, or adapter normalization |

## Minimum Questions

- Which layer owns validation and which layers merely display/transport the result?
- Which immutable evidence ID links the next stage back to its source?
- What remains durable if this stage fails?
- Is a new abstraction required by the current vertical slice or only by a Roadmap idea?
- Is there already one owner for this contract/status/coordinate/error value?
