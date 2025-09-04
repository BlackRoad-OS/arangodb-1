# aql-graph-traversal-generic-tests.js Documentation

## 1. Purpose & Scope
This suite exercises *all* traversal and path-finding semantics in ArangoDB AQL across:
- Traversal option Cartesian space (order, uniqueness, weighting)
- Optimizer rules and plan shape expectations
- Pruning, filtering, projection & memory optimizations
- K_PATHS / K_SHORTEST_PATHS semantics (weighted & unweighted)
- Parallel traversal execution and concurrency correctness
- Edge / corner cases (empty graphs, disconnected vertices, invalid starts)
- Cluster vs SingleServer behavioral divergences
- Failpoint-driven validation of internal execution behaviors

Its intent: guarantee correctness, stability, and performance characteristics of traversal-related query execution while detecting resource / semantic regressions early.

---

## 2. Conceptual Dimensions

### 2.1 Traversal Order
| Dimension | Values | Notes |
|----------|--------|-------|
| Order | `dfs`, `bfs`, `ws` (weighted BFS) | Weighted search uses cost ordering with tie-breaking by natural expansion sequence |

### 2.2 Vertex Uniqueness
| Setting | Meaning |
|---------|---------|
| `none` | Vertices may repeat freely |
| `path` | Per-path uniqueness enforced (no repetition inside single returned path) |
| `global` | Global uniqueness (no vertex appears in more than one produced path) |

### 2.3 Edge Uniqueness
| Setting | Meaning |
|---------|---------|
| `none` | Edges may repeat |
| `path` | No edge reused inside a single path |

### 2.4 Weight Semantics
- `weightAttribute`: attribute consulted per traversed edge (numeric)
- `indexedAttribute`: alternative attribute leveraged via index for optimizer rule interactions
- Weighted expansions produce ascending non-decreasing path cost sequence
- Tie-breaking: deterministic expansion order (implementation detail) still validated via multiset membership checks

### 2.5 Depth Ranges
- Inclusive ranges (e.g. `0..n`, `1..n`)
- Depth 0 semantics: path containing only start vertex
- Range filters used with optimizer pushdown tests

---

## 3. Graph Archetypes

| Archetype | Structural Intent | Usage Focus |
|-----------|-------------------|-------------|
| `openDiamond` | Branch + reconverge | Path multiplicity / uniqueness |
| `smallCircle` | Simple cycle | Cycle detection / uniqueness boundaries |
| `completeGraph` | Dense connectivity | Combinatorial explosion control, pruning |
| `easyPath` | Linear chain | Baseline expectation |
| `advancedPath` | Mixed branching with alternates | Label forwarding, pruning |
| `largeBinTree` | Binary tree depth 8 | Stress enumeration + performance |
| `unconnectedGraph` | Multiple isolated components | Empty result verification |
| `emptyGraph` | No edges / vertices beyond seed | Degenerate base cases |

Archetype factory functions prepare collections + edges; teardown invariants handled elsewhere (SUT checkers).

---

## 4. Validator / Helper Abstractions

### 4.1 Rose Tree Representation
`Node` structure models expected DFS enumeration. Converted into:
- Path list expansions
- Expected order sequences
- Multisets for BFS/weighted validations

### 4.2 Core Validator Families
| Validator | Validates | Strategy |
|-----------|-----------|----------|
| `checkResIsValidDfsOf` | DFS ordering | Recursive pre-order comparison |
| `checkResIsValidStackBasedTraversalOfFunc` -> `checkResIsValidBfsOf` / `checkResIsValidWsOf` | BFS / Weighted BFS ordering | Level / cost layer grouping |
| `checkResIsValidGlobalBfsOfFunc` -> `checkResIsValidGlobalBfsOf` / `checkResIsValidGlobalWsOf` | Global uniqueness BFS / weighted BFS | Global seen-set + ordering |
| `assertResIsContainedInPathList` | Subset membership | All returned paths present in expected superset |
| `assertResIsEqualInPathList` | Exact equality of path set | Sorted canonical form comparison |
| `checkResIsValidKShortestPathListWeightFunc` (weight/no-weight variants) | Ordered k-shortest correctness | Non-decreasing cost, uniqueness, membership |

### 4.3 Path Normalization & Canonicalization
Paths transformed into arrays-of-vertex-ids (or objects with weight accumulation) to enable:
- Multiset comparisons
- Order-insensitive equality (when appropriate)
- Cost monotonicity checks

### 4.4 Failure Diagnostics
Validators produce rich assert messages (original suite uses `assertEqual`, `assertTrue`, etc.). Python translation maps to `assert` + helper functions with structured diffs.

---

## 5. Uniqueness Semantics Details

| Mode | Enforcement Level | Implications for Enumeration |
|------|-------------------|------------------------------|
| `path` (vertices) | Only within same path | Duplicate vertices across different returned paths allowed |
| `global` (vertices) | Across all emitted paths | Enumeration halts expansion through already-seen vertex |
| `path` (edges) | Edge reuse blocked within single path | Prevents trivial cycles; still global reuse permitted |
| Combined | Vertex + edge path uniqueness enforce both simultaneously | Reduces branching factor |

Global uniqueness validators ensure no vertex appears twice globally; path uniqueness validators ignore cross-path duplicate vertices.

---

## 6. Weighted Traversal Semantics

- Cost accumulation = sum of per-edge `weightAttribute` (or fallback)
- Validation asserts:
  - Non-negative monotonic ascending output ordering
  - Ties produce deterministic vertex sets (validated via membership, not strict order if unspecified)
  - Weighted BFS vs unweighted BFS difference flagged where path counts diverge
- Indexed attribute tests confirm optimizer still accesses attribute via index without altering semantics.

---

## 7. K_PATHS / K_SHORTEST_PATHS

| Feature | Checked Properties |
|---------|--------------------|
| `K_PATHS` | Enumeration completeness subject to depth/limit |
| `K_SHORTEST_PATHS` | Cost ordering strict, duplicates excluded |
| Directional variants | OUTBOUND / INBOUND / ANY produce correct directional adherence |
| Range limits | Depth interval filters applied pre- or post-path materialization appropriately |
| Weighted vs Unweighted | Weighted variant respects cost-sorted ascending sequence |

Validators:
- Ensure each returned path is subset of expected enumerations
- Confirm returned count respects LIMIT clauses
- For weighted variant: strictly increasing (or equal under tie rules) cumulative cost

---

## 8. Optimizer Rule Interactions

Primary rule under scrutiny: `remove-redundant-path-var`
Scenarios:
- If traversal path variable not referenced later (only vertices used) rule SHOULD remove redundant materialization.
- If path variable referenced (e.g. length, vertex iteration, projection) rule MUST NOT trigger.
- Tests:
  - Plan inspection: presence/absence of traversal path var
  - Filter pushdown:
    - Early filter elimination of `FilterNode` when condition embedded inside `TraversalNode`
    - Ensures projection memory usage minimized
- Projection memory optimization:
  - Peak memory usage captured with and without projection forms
  - Expect decreased memory when unused attributes not materialized

Python translation will:
1. Collect execution plan (AQL explain)
2. Assert rule either present or absent per scenario matrix
3. Capture runtime stats (peak memory) via profiling API

---

## 9. Pruning Semantics

- Uses `PRUNE` clause with label variable forwarding
- `NOOPT` employed to prevent constant folding eliminating variable dependencies
- Validates that:
  - Pruning reduces output path multiplicity
  - Label variable properly forwarded into PRUNE predicate
  - Range-limited early termination yields smaller TraversalBlock item counts

---

## 10. Parallel & Concurrency Tests

Focus Areas:
- `parallelism` option producing expected multiplicity scaling
- Failpoint: `MutexExecutor::distributeBlock` ensures concurrency path exercised
- Multi-traversal / subquery / LIMIT / SORT interactions:
  - Ensure no duplication or lost paths due to concurrency
  - Validate determinism where guaranteed
- Harness executes repeated queries, comparing:
  - Result sets stable across runs
  - Execution stats (e.g., scanned index entries) within expected bands

Python adaptation:
- Parallel harness capturing (result_hash, stats.signature)
- Optional tolerance windows for volatile metrics
- Failpoint activation via server endpoint before query execution

---

## 11. Memory / Projection Optimization

- Captures `peakMemoryUsage` (JS accumulates from profiling)
- Test pairs:
  - With projection rule
  - Without (forcing full path materialization)
- Assertion: projected form uses <= memory threshold of unoptimized case

Python approach:
- Profiling API integration (inspect executor memory metrics if available)
- Fallback: external measurement wrapper (RSS delta) with noise margin

---

## 12. Early Filter Termination

- TraversalBlock instrumentation: item counts (produced vs filtered)
- Validates:
  - Filter pushdown reduces items pulled from upstream
  - Without pushdown more intermediate candidates
- Python translation:
  - Extract block stats (EXPLAIN / PROFILE)
  - Assert ratio improvement in optimized scenario

---

## 13. Edge & Degenerate Cases

| Case | Expected Behavior |
|------|-------------------|
| Start vertex absent | Empty result, no error |
| Unconnected graph | Empty traversal for non-existing edges |
| Empty graph | Only depth 0 paths if allowed by range |
| Depth 0 range | Single vertex path enumeration |
| Invalid direction spec | Compile-time error (covered elsewhere, not central here) |
| Cycle presence + global uniqueness | Termination without infinite expansion |

---

## 14. Cluster vs SingleServer Divergences

| Aspect | SingleServer | Cluster |
|--------|--------------|---------|
| Error codes (invalid start) | Specific code for missing vertex | May differ if shard lookup fails |
| Smart/Disjoint/Satellite graphs | Not applicable or simpler path | Additional shard mapping semantics |
| Shard-local index usage | Direct | Coordinator orchestrated; plan shape differences validated |

Tests assert presence/absence of certain error codes or plan nodes depending on deployment mode.

---

## 15. Failpoints / Instrumentation

| Failpoint | Purpose |
|-----------|---------|
| `MutexExecutor::distributeBlock` | Force concurrency scheduling path |
| `RocksDBEdgeIndex::disableHasExtra` | Validate index behavior fallback |
| Others (implicit) | Potential extension for latency injection |

Python integration: enable via HTTP debug API before scenario, ensure cleared in teardown (SUT checker will detect residual failpoints).

---

## 16. Mapping to Python Abstractions

| JS Concept | Python Planned Abstraction |
|------------|----------------------------|
| Node (rose tree) | `armadillo.graph.validators.RoseNode` |
| checkResIsValidDfsOf | `DFSOrderValidator` |
| BFS / Weighted validators | `BFSValidator`, `WeightedBFSValidator` |
| Global uniqueness validators | `GlobalUniquenessValidator` |
| Path list membership checks | `PathSetComparator` |
| K shortest path weight validator | `KShortestPathValidator` |
| Archetype factory functions | `GraphArchetypeFactory` (strategy-based) |
| Optimizer rule expectation | `OptimizerExpectation(rule, should_fire=True/False)` |
| Memory comparison | `ProjectionMemoryComparator` |
| Parallel harness | `ParallelTraversalHarness` |
| Failpoint enablement | `FailpointManager` |
| Plan inspection utilities | `ExecutionPlanInspector` |

---

## 17. Python Test Layer Structure (Planned)

```
armadillo/
  traversal/
    archetypes.py
    options.py
    validators/
      dfs.py
      bfs.py
      weighted.py
      uniqueness.py
      k_shortest.py
      path_canonical.py
    optimizer/
      expectations.py
      memory_projection.py
      pruning.py
      filter_pushdown.py
    parallel/
      harness.py
      failpoints.py
    scenarios/
      test_matrix_generation.py
      test_k_shortest.py
      test_weighted_ordering.py
      test_pruning.py
      test_parallelism.py
      test_optimizer_rules.py
```

---

## 18. Traceability Matrix (Representative Subset)

| Requirement | Validator / Test ID (planned) |
|-------------|-------------------------------|
| DFS ordering correctness | TRV-DFS-ORDER-001 |
| BFS level expansion | TRV-BFS-ORDER-002 |
| Weighted cost monotonicity | TRV-WS-COST-003 |
| Path uniqueness (edges) | TRV-PATH-EDGE-004 |
| Global vertex uniqueness | TRV-GLOBAL-VERT-005 |
| Optimizer rule removal check | OPT-RULE-RPV-010 |
| Projection memory saving | OPT-PROJ-MEM-011 |
| PRUNE semantic correctness | OPT-PRUNE-012 |
| K shortest path cost order | KP-KSP-020 |
| Parallel multiplicity stable | PAR-MULT-030 |
| Failpoint concurrency path | PAR-FAILPOINT-031 |
| Invalid start empty result | ERR-INVSTART-040 |
| Depth 0 path enumeration | DEP-0-RANGE-050 |
| Large binary enumeration completeness | STRESS-LBT-060 |

---

## 19. Open Issues / Notes
- Deterministic tie-breaking for weighted BFS: JS relies on engine expansion order; Python harness to avoid over-constraining order (use multiset comparison when cost ties).
- Memory metrics parity: need to confirm accessible profiling counters in Python interface; fallback measurement strategy may introduce noise thresholds.
- Cluster plan variability: must allow pattern / subset assertions rather than full equality of plan JSON.

---

## 20. Risk & Mitigation
| Risk | Mitigation |
|------|------------|
| Over-constrained ordering assertions cause flakiness | Use canonicalization + cost buckets |
| Parallel timing nondeterminism | Retry harness with stable hashing; majority consensus |
| Failpoint leakage between tests | Central FailpointManager + SUT checker invariants |
| Future optimizer rule additions break expectations | Expectation layer loads dynamic rule list, asserts relative conditions only |

---

## 21. Implementation Priorities (Python Port)
1. Implement archetype factory + teardown safety.
2. Implement path canonicalization utilities.
3. Port DFS/BFS/Weighted validators.
4. Add uniqueness + global uniqueness enforcement validators.
5. Implement k-shortest path validator (cost + ordering).
6. Introduce optimizer expectation inspection + plan diff helpers.
7. Integrate projection memory comparator (deferred until profiling infra ready).
8. Add pruning + label forwarding tests.
9. Implement parallel harness with failpoint control.
10. Stress test large binary tree last (performance baseline established first).

---

## 22. Integration With SUT Checkers
Traversal tests rely on:
- Collections / graphs cleanup
- Failpoints reset
- Tasks drained
These are enforced by SUT checker layer executed after each test module.

---

## 23. Summary
This documentation captures the full semantic contract of the legacy traversal generic test suite, establishing traceable requirements and structured validators for the Python Armadillo framework. It enables a faithful, test-first reconstruction ensuring optimizer, correctness, performance, and concurrency behaviors are preserved.
