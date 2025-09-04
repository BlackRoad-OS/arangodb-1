# Consolidated SUT Checker Invariants

## 1. Purpose
Defines authoritative post-test invariants enforced by SUT checkers to ensure environmental cleanliness, isolation, and correctness after each test (or test module). Serves as the contract to be preserved in the Python Armadillo framework.

---

## 2. Global Principles
| Principle | Description |
|-----------|-------------|
| Zero Residual User Artifacts | No leftover user-created resources beyond explicitly whitelisted baseline/system objects |
| Deterministic Snapshots | Baseline captured once per test session (or test) before mutations |
| Minimal False Positives | Ignore lists restricted and documented; no broad pattern suppression |
| Cluster-Aware Validation | Per-resource scoping to correct server role (coordinator, DBServer) |
| Fast Execution | Snapshot comparison O(n) in number of objects; no expensive deep fetch unless required |
| Idempotent | Checker execution has no side effects unless performing sanctioned remediation (e.g. clearing failpoints) |

---

## 3. Resource Domain Invariants

### 3.1 Collections Checker
| Aspect | Invariant |
|--------|-----------|
| Scope | `_system` database only (or all databases?) → Current JS checker filters non-system + agency internal; Python will target global across dbs except ephemeral test DB if policy requires |
| Baseline | Set of non-system collection names existing prior to test |
| Post-test | Same set (no additions, no undeleted collections) |
| Ignore | System collections (`_graphs`, `_analyzers`, internal replication/state) automatically inside baseline |
| Failure Modes | Added collections, leaked sharded collections, orphan orphaned smart-edge collections |
| Edge Cases | Parallel tests may intentionally create same-named collections in isolated databases (database isolation prevents conflict) |

Enhancements (Python): Optional strict mode ensuring no system collection count anomalies (detection of internal leaks).

### 3.2 Databases Checker
| Aspect | Invariant |
|--------|-----------|
| Baseline | Only `_system` or explicitly allowed ephemeral test db(s) (e.g. `UnitTestDB` if framework standardizes) |
| Post-test | All temporary test databases deleted |
| Ignore | `_system` always retained |
| Known JS Observation | TODO comment referencing authentication tests not fully cleaning up (flag for improvement) |
| Failure Conditions | Extra user databases remain; mismatched dropped database attempt leaving shards |

Policy: Allow list config `allowed_transient_databases=[]`.

### 3.3 Graph Definitions Checker
| Aspect | Invariant |
|--------|-----------|
| Baseline | Count (and optionally definitions signature) of entries in `_graphs` collection |
| Post-test | Identical count & (optional) sets of graph names |
| Failure | Leaked named graph or missing expected baseline definition |
| Edge | Smart / disjoint graph metadata must fully disappear (including hidden collections) — cross-check with Collections checker |

Optional deep signature (vertex/edge collection sets) to detect partial mutation.

### 3.4 Views Checker
| Aspect | Invariant |
|--------|-----------|
| Baseline | Set of view names (ArangoSearch / SearchAlias) |
| Post-test | Same set; no added / removed |
| Failure | Residual view or dropped baseline view |
| Edge | View rename operations reflected correctly (difference = removed + added → fail) |

Potential Enhancement: Compare primary properties hash to detect parameter drift.

### 3.5 Users Checker
| Aspect | Invariant |
|--------|-----------|
| Baseline | User list (excluding built-in system users) |
| Post-test | No residual added users; no deletion of baseline |
| Failure | Added test user not removed; baseline user removed |
| Edge | Password changes not tracked (non-goal) |

### 3.6 Tasks Checker
| Aspect | Invariant |
|--------|-----------|
| Baseline | Count/list of server tasks minus known persistent internal tasks (`foxx-queue-manager`) |
| Post-test | No additional tasks; all scheduled transient tasks completed/cancelled |
| Failure | Orphaned async task present |
| Edge | Long-running background tasks (benchmarks) should be awaited or explicitly excluded by policy |

Python Enhancement: Capture task payload hash to identify repeating leak patterns.

### 3.7 Transactions Checker
| Aspect | Invariant |
|--------|-----------|
| Post-test | `db._transactions()` empty (no open transactions) |
| Failure | Any remaining open transaction IDs |
| Edge | Cluster: coordinator vs DBServer discrepancy; must assert emptiness via coordinator endpoint |

Baseline unnecessary (expectation always zero).

### 3.8 Failure Points Checker
| Aspect | Invariant |
|--------|-----------|
| Baseline | (Optional) initial failure point list should be empty |
| Post-test | No active failure points |
| Failure | Any un-cleared failpoint |
| Remediation | Optionally auto-clear (policy controlled) |
| Edge | Race: failpoint cleared after snapshot but before comparison (benign) |

### 3.9 Analyzers Checker
(Defined fully in separate doc; summarized)
| Aspect | Invariant |
|--------|-----------|
| Baseline | List of analyzer names |
| Post-test | Identical set |
| Failure | Added/removed analyzer |
| Edge | Analyzer feature versions; underlying property mutation not currently checked |

### 3.10 Optional Future Domains
| Domain | Potential Invariant |
|--------|--------------------|
| Running Queries | No long-lived queries post-test |
| Pregel Jobs | No active jobs after test |
| Replication Appliers | No leftover paused applier states |
| Hot Backup Artifacts | No stray backup directories |
| Temp Files | No leaked temp directories (needs path policy) |

---

## 4. Cross-Domain Consistency
| Relation | Consistency Requirement |
|----------|------------------------|
| Graph → Collections | All vertex/edge collections of leaked graphs will also appear in collection diff (dual signal) |
| Views → Analyzers | Analyzer diff should not appear if view with custom analyzer was properly dropped |
| Tasks → Failure Points | Residual failurepoints should not spawn recurring tasks; dual leak suggests systemic cleanup issue |

Checker runner aggregates multi-domain failures; reporting merges related hints.

---

## 5. Cluster vs SingleServer Nuances
| Domain | Cluster Consideration |
|--------|-----------------------|
| Collections | Smart / disjoint produce multiple physical shard collections—diff at logical layer only |
| Tasks | Coordinator enumeration differs; ensure API endpoint used is coordinator-scoped |
| Failure Points | Must iterate all DBServers; any non-empty set fails |
| Transactions | Aggregation via coordinator; DBServer-local introspection optional |
| Graphs | SmartGraph internal collections validated indirectly through collection names pattern |

Configuration: `cluster_mode=true` triggers multi-instance fan-out capture for failurepoints.

---

## 6. Snapshot Strategy Matrix
| Domain | Snapshot Timing | Requires Baseline? | Reason |
|--------|-----------------|--------------------|--------|
| Collections | Session or per-test (configurable) | Yes | Detect additions |
| Databases | Session | Yes | Expect minimal churn |
| Graphs | Session | Yes | Usually sparse |
| Views | Session | Yes | Rare creation expected |
| Users | Session | Yes | User creation unusual per test |
| Tasks | Per-test | Yes (filtered baseline) | Transient tasks frequent |
| Transactions | Post-test only | No | Must be empty |
| Failure Points | Pre + Post | Baseline optional | Should be empty always |
| Analyzers | Session | Yes | Rare creation |

---

## 7. Diff Computation Standard
`diff = { added: sorted(current - baseline), removed: sorted(baseline - current) }`
Augmented fields per domain:
- `transactions`: list of active transaction IDs
- `failurepoints`: active failpoint names
- `tasks`: leaked task descriptors (id, type, created, info hash)
- `collections`: optional structural metadata (type, shardCount) in details for diagnostics

---

## 8. Severity Policy Defaults
| Domain | Default Severity on Violation |
|--------|-------------------------------|
| Failure Points | fail (remediated optionally) |
| Transactions | fail |
| Tasks | fail |
| Collections | fail |
| Databases | fail |
| Graphs | fail |
| Views | fail |
| Users | fail |
| Analyzers | fail |

Policy overrides allow downgrade (e.g. known intermittent task leak → warn) via `policy.yaml`.

---

## 9. Remediation Hooks
| Domain | Hook | Policy Flag |
|--------|------|-------------|
| Failure Points | Clear each failpoint | `remediate_failurepoints=true` |
| Tasks | Attempt cancel (future) | `remediate_tasks=true` |
| Transactions | Not attempted (dangerous) | n/a |
| Collections/Databases | Not attempted (explicit test responsibility) | n/a |

Remediated status still surfaced; may still count as failure depending on `fail_on`.

---

## 10. Diagnostic Message Patterns
| Domain | Example Message |
|--------|-----------------|
| Collections | `Collection leak detected: added=['tmp_edges'] removed=[]` |
| Databases | `Residual databases: ['TestDB_42']` |
| Failure Points | `Active failure points remain: ['RocksDBEdgeIndex::disableHasExtra']` |
| Tasks | `Orphan tasks: added_ids=[12345]` |
| Transactions | `Dangling transactions: ['trx-98765']` |
| Analyzers | `Analyzer changes detected: added=['text_fr'] removed=[]` |

---

## 11. False Positive Avoidance Strategies
| Risk | Mitigation |
|------|------------|
| Concurrent creation during snapshot window | Snapshot early before test spawns concurrency |
| System internal transient tasks | Maintain curated ignore list with hash of stable attributes |
| Cluster propagation delay | Delay / retry small backoff for failurepoint enumeration |
| Ephemeral analyzer installed by startup scripts | Include in baseline snapshot automatically |

---

## 12. Implementation Mapping (Python)
| Domain | Python Class |
|--------|--------------|
| Collections | `CollectionsChecker` |
| Databases | `DatabasesChecker` |
| Graphs | `GraphsChecker` |
| Views | `ViewsChecker` |
| Users | `UsersChecker` |
| Tasks | `TasksChecker` |
| Transactions | `TransactionsChecker` |
| Failure Points | `FailurePointsChecker` |
| Analyzers | `AnalyzerChecker` |

Each subclass overrides: `capture_baseline()`, `capture_current()`, `diff()`, and optionally `evaluate()`.

---

## 13. Metrics Capture (Optional Future)
| Metric | Purpose |
|--------|---------|
| Leak Frequency | Trend analysis across CI runs |
| Time to Remediation | Effectiveness of remediation attempts |
| Domain Failure Distribution | Prioritize stability work |
| Average Checker Duration | Performance budgeting |

---

## 14. Open Issues / Decisions Pending
| Issue | Decision Needed |
|-------|-----------------|
| Multi-database parallel test strategy | Decide if per-test database isolation replaces some invariants |
| Deep property diffs (views/analyzers) | Evaluate cost vs benefit |
| Automatic collection cleanup | Likely out-of-scope (tests must own teardown) |
| Partial graph definition cleanup detection | May require parsing internal smart graph collection naming scheme |

---

## 15. Example JSON Result Fragment
```
{
  "test": "test_graph_traversal_parallel.py::test_parallel_prune",
  "checkers": [
    {
      "name": "collections",
      "status": "fail",
      "details": {
        "added": ["tmp_edges"],
        "removed": []
      },
      "message": "Collection leak detected: added=['tmp_edges'] removed=[]",
      "duration_s": 0.012
    }
  ]
}
```

---

## 16. Validation Plan (Meta-Tests)
| Test | Intent |
|------|--------|
| Create & leak collection | Expect collections checker fail |
| Create & drop collection | Pass |
| Add analyzer & drop | Pass |
| Add analyzer & do not drop | Fail analyzers |
| Inject failpoint & leave | Fail failurepoints |
| Open transaction & not commit | Fail transactions |
| Create transient task & wait completion | Pass |
| Create transient task & kill test early | Fail tasks |

---

## 17. Summary
These invariants form the baseline environmental cleanliness contract necessary for reliable higher-level traversal, optimizer, and concurrency testing. They will be implemented via snapshot/diff checkers with strict failure defaults and a configurable policy layer for controlled downgrades.
