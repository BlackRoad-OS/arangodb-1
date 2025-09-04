# REST vs AQL CRUD Differences (Behavioral Contract for Armadillo)

## 1. Purpose
Define semantic, performance, and edge‑case differences between ArangoDB REST API CRUD operations and equivalent AQL (data-modifying) statements to ensure faithful porting of JS test intent to Python (pytest) without losing coverage of subtle invariants.

---

## 2. Scope
Covers single and batched document operations on:
- Document Collections
- Edge Collections
- System vs User Collections

Operations:
- Create (INSERT)
- Read (GET / FILTER / PRIMARY LOOKUP)
- Update / Patch (UPDATE / REPLACE)
- Delete (REMOVE)

Not in scope: Graph API helpers, Pregel, Foxx endpoints (handled elsewhere).

---

## 3. Conceptual Model Differences

| Aspect | REST API (HTTP endpoints) | AQL Statements |
|--------|---------------------------|---------------|
| Execution Context | Immediate per-request; minimal planner involvement | Planned & optimized execution pipeline |
| Transaction Boundary | Implicit single-op transaction (unless multi-document batch w/ `waitForSync` and error options) | Entire AQL query is one transaction (unless streaming transactions used) |
| Error Reporting | HTTP status + Arango error JSON | Query error mid-execution aborts full transaction (rollback) |
| Batch Handling | Multi-document endpoints (`/_api/document`, array body) partially succeed (error index array) | Bulk operations (`FOR d IN docs INSERT/UPDATE/REMOVE`) are atomic fail-all on first error |
| Return Semantics | Can request `returnNew`, `returnOld` flags | Use `RETURN NEW/OLD` or capture via `LET` variables |
| Revision Control | `_rev` via `if-match` / `ignoreRevs` flags | `_rev` checked if provided unless `OPTIONS { ignoreRevs: true }` |
| Write Concern / Sync | `waitForSync` per-request | `OPTIONS { waitForSync: true }` at statement level |
| Silent Mode | `silent=true` query param suppresses body | `OPTIONS { silent: true }` or omit RETURN (affects result shape) |
| Overwrite Modes | `overwrite=true|false`, `overwriteMode=ignore,replace,update,conflict` | `INSERT ... OPTIONS { overwriteMode: "...", ignoreErrors: ... }` |
| Concurrency Conflict | 412 (precondition failed) for revision mismatch | Query error (1200 / 1202 etc.) aborts entire query |
| Index Utilization | Server internal; no explicit plan visible | Visible in `EXPLAIN` (IndexNode, CollectNode, etc.) |
| Partial Update Semantics | PATCH modifies given attributes only | `UPDATE doc WITH { ... } IN coll` same, `REPLACE` is full document replace |
| Document Keys | Provided or auto-generated per entry | Same; `INSERT { _key: ... }` |
| Edge Constraints | `_from` / `_to` must exist; per-op validation | Same, but validated per produced operation in execution pipeline |
| Quiet Nonexistent Remove | `ignoreRevs` or `ignoreErrors` not for missing docs unless specified | `OPTIONS { ignoreErrors: true }` can skip missing removes |

---

## 4. Error Code Mapping (Representative)

| Scenario | REST Code | AQL Error |
|----------|-----------|-----------|
| Revision mismatch | 412 (1200) | 1200 inside query → abort |
| Unique constraint violation | 409 (1210) | 1210 triggers full rollback |
| Document not found (GET) | 404 (1202) | 1202 (if referenced mid-query) |
| Collection not found | 404 (1203) | 1203 |
| Write-write conflict | 409 (1200/1201 depending) | 1200/1201 abort |
| Edge `_from/_to` missing | 404 (1232) | 1232 |

Testing Implication: REST multi-document creates may partially succeed while equivalent AQL FOR-INSERT atomic block will fully rollback → tests must separately validate both behaviors.

---

## 5. Overwrite Modes Comparison

| Mode | REST Behavior | AQL Behavior | Test Focus |
|------|---------------|--------------|-----------|
| default (no overwrite) | 409 if exists | error if exists | Baseline conflict detection |
| overwrite=true (legacy) | Replace entire doc | `OPTIONS { overwrite: true }` (deprecated form) | Backward compatibility |
| overwriteMode=ignore | Skip existing (returns existing rev) | Same; result count smaller than input | Cardinality difference |
| overwriteMode=replace | Full replacement | Same | Field removal effect |
| overwriteMode=update | Merge (shallow) | Same | Attribute retention |
| overwriteMode=conflict | Like default but explicit | Same | Mode discrimination |

Edge: AQL can combine overwriteMode with RETURN NEW; REST must specify `returnNew=true`.

---

## 6. Partial vs Full Update

| Operation | REST | AQL | Invariant |
|-----------|------|-----|----------|
| PATCH / UPDATE | Only listed fields changed | `UPDATE` merges object fields | Non-specified scalar fields preserved |
| REPLACE | Replaces entire doc | `REPLACE` same | Missing fields removed |
| Nested Merge Depth | Shallow (nested objects replaced) | Same | Test ensures nested object replaced, not deep-merged |

---

## 7. Atomicity & Partial Success

| Pattern | REST Multi-Insert | AQL FOR INSERT |
|---------|-------------------|----------------|
| One invalid among valid | Valid subset committed, errors reported for invalid entries | Entire batch rolled back |
| Test Approach | Verify count == valid subset | Expect 0 inserted |

Need dual test variants when porting generic CRUD suites.

---

## 8. Concurrency & Revision Control

| Scenario | REST (Optimistic) | AQL |
|----------|-------------------|-----|
| Two writers same `_rev` | Second fails 412 | Second triggers 1200 rollback |
| Retry Handling | Client decides per failed doc | Must restart entire query or use transactional retry wrapper |

Python Abstraction: Provide `retry_write_conflicts` helper for AQL operations to mirror REST client manual retry loops used historically.

---

## 9. Performance / Plan Visibility

| Aspect | REST | AQL |
|--------|------|-----|
| Index selection introspection | Not directly exposed (except profiling endpoints) | `EXPLAIN` / `PROFILE` shows nodes |
| Projection optimization | Endpoint returns whole doc unless `fields` param (not broadly available) | AQL explicit projection via `RETURN { subset }` (reduces materialization) |
| Multi-step pipeline | Multiple round trips | Single query reduces latency overhead |

Testing: Performance-sensitive optimizer assertions only meaningful under AQL; REST layer excluded from those scenarios.

---

## 10. Edge Document Semantics
Same uniqueness / creation semantics; REST requires `_from` and `_to` fields per edge create; AQL identical. Bulk difference: partial success semantics again.

Invariant: After failure in one edge create:
- REST: Some edges may exist
- AQL: None inserted

---

## 11. Silent & Return Body Control

| Need | REST Mechanism | AQL Mechanism |
|------|----------------|---------------|
| Suppress body | `silent=true` | `OPTIONS { silent: true }` or omit RETURN |
| Return old doc | `returnOld=true` + method supporting | `UPDATE ... RETURN OLD` |
| Return new doc | `returnNew=true` | `INSERT ... RETURN NEW` |

Test must ensure silent insert does not accidentally produce result rows in AQL port (shape mismatch detection).

---

## 12. Error Aggregation Structure

REST multi-doc endpoint returns:
```
[
  { "_id": "...", "_key": "...", "_rev": "..." },
  { "error": true, "errorMessage": "...", "errorNum": 1210 }
]
```
AQL equivalent: no per-item structure; entire query error.

Python harness must supply synthetic per-item mapping when validating parity (simulate what would have succeeded).

---

## 13. Ignore Errors / Missing Docs Removal

| Case | REST Delete Multi | AQL REMOVE with ignoreErrors |
|------|-------------------|------------------------------|
| Missing doc | Returns error object unless `ignoreRevs` interplay | Skipped with `ignoreErrors: true` |
| Mixed present/missing | Partial success array outcome | Entire loop continues (present removed, missing skipped) |

Test: Validate resulting collection count & absence of missing key side effects.

---

## 14. Transaction Interaction

| Feature | REST | AQL |
|---------|------|-----|
| Multi-collection atomic op | Requires explicit transaction API (`/_api/transaction`) with JavaScript body | Natural inside single AQL query |
| Deadlock handling | Error per request | Query-level exception |
| Lock acquisition ordering | Operation-specific | Planner coordinates upfront |

Tests covering multi-collection consistency should prefer AQL path for atomic invariants; REST variant uses transaction endpoint separately (optional coverage).

---

## 15. Consistency & Visibility

| Scenario | After Insert via REST | After Insert via AQL |
|----------|-----------------------|----------------------|
| Immediate query visibility | Yes (committed) | Yes (after query finishes) |
| Mid-operation visibility | N/A (single op) | Not visible until commit (end of query) |

Concurrency tests must not assume intermediate partial visibility for AQL.

---

## 16. Retry Semantics (Write-Conflict)

| Layer | Typical Strategy |
|-------|------------------|
| REST | Client loop: try → 412 → refetch → retry |
| AQL | Whole query rerun (server does not auto-split) |
| Python Plan | Provide `run_with_retry(fn, max_attempts)` for parity |

---

## 17. Test Translation Mapping

| Legacy JS Intent | Python Armadillo Strategy |
|------------------|---------------------------|
| Validate partial multi-insert success | Separate REST fixture + AQL full rollback expectation test |
| Assert revision precondition failure | Dual test: REST 412 vs AQL rollback error code |
| Ensure overwrite modes semantics | Parameterized test emitting (mode, layer) matrix |
| Check ignore missing remove | Parameterized REMOVE with/without ignoreErrors |
| Concurrency conflict handling | Stress harness issuing parallel REST vs single AQL FOR update |

---

## 18. Risk & Pitfalls

| Risk | Mitigation |
|------|------------|
| Treating partial REST success as full atomic in port | Explicit dual test variants retained |
| Overlooking overwriteMode divergence | Central enumeration constant consumed by both REST & AQL tests |
| Losing per-document error granularity | Build synthetic per-item result list for AQL mirror tests |
| Flaky revision tests due to cache | Force new fetch of `_rev` after each mutation |

---

## 19. Planned Python Abstractions

| Component | Responsibility |
|-----------|----------------|
| `CrudLayer` Enum | Distinguish REST vs AQL variant |
| `BulkResultNormalizer` | Convert REST per-item result -> canonical list; emulate for AQL |
| `OverwriteMode` | Central enumeration & mapping to REST params / AQL OPTIONS |
| `RevisionConflictHarness` | Generate deterministic conflict scenario |
| `PartialSuccessAsserter` | Assert divergence (REST partial vs AQL zero commit) |
| `RetryPolicy` | Configurable retry with backoff for write conflicts |

---

## 20. Traceability (Representative IDs)

| Requirement | ID |
|-------------|----|
| Partial success multi-insert detectable | CRUD-PARTIAL-001 |
| AQL atomic rollback on conflict | CRUD-ATOMIC-002 |
| Overwrite mode parity matrix | CRUD-OVERWRITE-003 |
| Patch vs replace field removal | CRUD-REPLACE-004 |
| Revision mismatch dual behavior | CRUD-REV-005 |
| Ignore missing remove (AQL vs REST) | CRUD-IGNORE-MISS-006 |
| Edge create atomicity difference | CRUD-EDGE-ATOMIC-007 |
| Synthetic per-item error mapping | CRUD-MAPPING-008 |

---

## 21. Open Questions

| Topic | Pending Decision |
|-------|------------------|
| Coverage for transaction JS body (legacy API) | Possibly minimal (focus on AQL) |
| Include Foxx service document mutations? | Out of scope for base CRUD |
| Deep compare of REST vs AQL performance metrics | Deferred (non-functional) |

---

## 22. Summary
REST and AQL CRUD paths intentionally diverge in atomicity, error granularity, and overwrite semantics. The Armadillo framework will preserve both behavioral spaces via parameterized dual-layer tests, ensuring previously validated invariants (partial success vs full rollback, overwrite modes, revision handling) remain guarded against regressions.
