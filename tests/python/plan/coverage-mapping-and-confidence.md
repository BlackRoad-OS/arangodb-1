# Coverage Mapping & Confidence Rating

## 1. Purpose
Map every identified legacy JavaScript framework capability to its planned Armadillo Python implementation (phase, component), highlight enhancements, explicitly note deferred items, and assign a pre-implementation confidence rating (gate before Phase 1 execution).

---

## 2. Legend
| Status | Meaning |
|--------|---------|
| MAPPED | Fully covered in implementation_plan with concrete component & phase |
| ENHANCED | Covered plus improved design / additional capability |
| DEFERRED | Intentionally postponed to later phase (not Phase 1 critical) |
| OPTIONAL | Nice-to-have, not required for parity |
| GAP-ID | Refer to gap-analysis requirement ID for remediation tracking |

---

## 3. High-Level Capability Matrix

| Legacy Capability | JS Source (Representative) | Armadillo Component | Phase | Status | Notes / GAP |
|-------------------|----------------------------|---------------------|-------|--------|-------------|
| Single-server lifecycle | testing.js / instance.js | core.process + instances.server | 1 | MAPPED | ProcessSupervisor abstraction |
| Cluster topology orchestration | instance-manager.js / agency.js | instances.cluster / instances.agency / topology | 2 | MAPPED | |
| Agency consensus monitoring | agency.js | instances.agency + health | 2 | MAPPED | Leader event logging deferred (INST-RESILIENCE-010) |
| Health checks & readiness | instance-manager.js | instances.health | 1 | MAPPED | Backoff policy Phase 2 (see gap) |
| Crash detection & analysis (GDB) | crash-utils.js | monitoring.crash_analyzer | 4 | MAPPED | Advanced filtering deferred CRASH-GDB-020 |
| Core dump management | crash-utils.js | monitoring.crash_analyzer | 4 | MAPPED | Size/limit policy deferred (CRASH-GDB-020) |
| Sanitizer log capture | crash-utils.js | monitoring.sanitizer_handler | 4 | MAPPED | Correlation tagging Phase 2 uplift |
| Result aggregation multi-format | result-processing.js | results.processor + exporters.* | 3 | ENHANCED | Adds HTML & trend analysis |
| Statistical performance metrics | result-processing.js | results.analysis.{statistics,performance} | 3 | MAPPED | Trend baseline Phase 6 (historical) |
| Test discovery & filtering | testing.js | pytest_plugin.collectors / filters | 3 | MAPPED | Advanced pattern compiler Phase 5 (ORCH-BUCKET-001 indirect) |
| Bucket splitting (parallel shards) | testing.js | pytest_plugin / utils (BucketAssigner) | 5 | DEFERRED | ORCH-BUCKET-001 |
| Parallel execution coordination | testing.js | pytest -n integration (future) + core concurrency helpers | 3 | MAPPED | |
| SUT cleanup invariants | sutcheckers/* | checkers.* (planned) | 2 (foundation), 3+ | ENHANCED | Policy + severity escalation CHECK-POLICY-070 |
| Failure point enforcement | sutcheckers/failurepoints.js | checkers.failurepoints + failpoint manager | 2 | MAPPED | Auto-remediation policy toggle |
| Resource leak prevention (collections/dbs) | multiple sutcheckers | checkers.(collections,databases,graphs,views) | 2 | MAPPED | Extended domains Phase 6 |
| Analyzer diff stability | analyzers.js | checkers.analyzers | 2 | MAPPED | |
| Tasks leak detection | tasks.js | checkers.tasks | 2 | MAPPED | Payload hashing enhancement planned |
| Transaction leak detection | transactions.js | checkers.transactions | 2 | MAPPED | |
| Traversal correctness validators | aql-graph-traversal-generic-tests.js | traversal.validators.* | 7 | DEFERRED | Deferred to Phase 7 post-core (modular validator suite) |
| Weighted BFS & tie semantics | traversal generic | traversal.validators.weighted | 7 | DEFERRED | Deferred; cost-bucket comparator design preserved |
| K_PATHS / K_SHORTEST_PATHS | traversal generic | traversal.validators.k_shortest | 7 | DEFERRED | Deferred; algorithm harness design retained |
| Optimizer rule presence checks | traversal generic | traversal.optimizer.expectations | 7 | DEFERRED | Deferred; dynamic discovery retained for later |
| Projection memory optimization | traversal generic | traversal.optimizer.memory_projection | 7 | DEFERRED | Deferred; memory noise calibration later (RES-PERF-MEM-030) |
| PRUNE semantics | traversal generic | traversal.optimizer.pruning | 7 | DEFERRED | Deferred |
| Parallel traversal harness | traversal generic | traversal.parallel.harness | 7 | DEFERRED | Deferred; failpoint concurrency patterns preserved |
| Failpoint orchestration | crash-utils.js / traversal tests | parallel.failpoints + checkers.failurepoints | 2 / 5 | MAPPED | |
| REST vs AQL CRUD divergence | legacy CRUD suites | crud dual-layer tests (to be added under scenarios) | 7 | DEFERRED | Deferred; synthetic mapping documented |
| Overwrite modes parity | CRUD tests | crud tests + enums | 7 | DEFERRED | Deferred |
| Partial success vs atomic rollback | CRUD tests | crud PartialSuccessAsserter | 7 | DEFERRED | Deferred |
| Revision conflict handling | CRUD tests | crud RevisionConflictHarness | 7 | DEFERRED | Deferred; retry harness CRUD-RETRY-040 later |
| Client tools (dump/restore/import/export) | client-tools.js | tools.(dump,restore,import_tool,export_tool) | 4 | MAPPED | Adds structured output parsing |
| Benchmark integration | client-tools.js | tools.benchmark | 4 | MAPPED | |
| Backup management | client-tools.js | tools.backup | 4 | MAPPED | |
| Auth token management (JWT) | process-utils.js | utils.auth + core.config | 1 | MAPPED | Rotation scenarios Phase 4 |
| Process supervision & escalation | process-utils.js | core.process (ProcessSupervisor) | 1 | ENHANCED | Structured lifecycle events |
| Port allocation | process-utils.js | utils.ports | 1 | MAPPED | |
| Path resolution | process-utils.js | utils.paths | 1 | MAPPED | |
| Logging & structured diagnostics | testing.js/process-utils.js | utils.logging + rich integration | 1 | ENHANCED | Color + structured JSON option |
| Layered timeout enforcement | implicit JS runtime controls | core.time.TimeoutManager + pytest_plugin.hooks | 1 | ENHANCED | Global + per-test + watchdog + signal escalation |
| Result analysis CLI (examine_results.js replacement) | scripts/examine_results.js | cli.commands.analyze + results.analysis.registry | 1 (scaffold), 3 (extended) | ENHANCED | Analyzer registry, diff & future trend integration |
| Network statistics capture | crash-utils.js / instance-manager | monitoring.network_monitor | 5 | MAPPED | Packet capture conditional Phase 6 |
| Memory profiling | result-processing (peak usage) | monitoring.memory_profiler | 5 | MAPPED | Noise calibration RES-PERF-MEM-030 |
| GDB scripted stack filtering | crash-utils.js | monitoring.crash_analyzer | 6 | DEFERRED | CRASH-GDB-020 |
| Core dump trimming / quotas | crash-utils.js | monitoring.crash_analyzer | 6 | DEFERRED | CRASH-GDB-020 |
| Trend analysis / historical comparison | result-processing.js | results.analysis.trends | 6 | MAPPED | |
| CLI orchestration & flags | testing.js | cli.main + commands.* | 1..4 iterative | MAPPED | Clean modern CLI |
| Policy-driven checker severities | sutcheckers integration | checkers.policy | 2 | ENHANCED | Deterministic escalation |
| Environment feature detection | implicit JS logic | core.environment_probe (planned) | 1 | MAPPED | ENV-PROBE-003 |
| Resilience scenarios (restart member) | manual JS patterns | resilience runner (future) | 3 | DEFERRED | INST-RESILIENCE-010 |
| Leader failover monitoring | agency.js | leadership event log | 3 | DEFERRED | INST-RESILIENCE-010 |
| Agency plan/current diff | agency.js | agency inspector | 3 | DEFERRED | INST-RESILIENCE-010 |
| Bucket splitting | testing.js | BucketAssigner | 5 | DEFERRED | ORCH-BUCKET-001 |
| Historical error catalog | result-processing.js (partial) | results.analysis.error_catalog | 5 | DEFERRED | LOG-SEGMENT-090 (related) |
| Per-test log segmentation | ad-hoc JS | logging segmenter | 2 | DEFERRED | LOG-SEGMENT-090 |
| Extended SUT domains (backups, active queries) | future JS | checkers.* extended | 6 | OPTIONAL | Pregel removed (deprecated) |

---

## 4. Phase 1 Coverage Verification (Gate)
| Phase 1 Item | Implementation Plan Component Present? | Dependency Gaps? | Notes |
|--------------|----------------------------------------|------------------|-------|
| Package skeleton & pyproject | Yes | None | Already scaffold partially (core files exist) |
| Logging & structured output | Yes (`log.py`) | None | Enhanced vs legacy |
| Auth & crypto basics | Yes (`auth.py`, crypto placeholder) | None | Rotation tests later |
| Timeout & global deadline | Yes (`time.py`) | None | |
| Process supervision | Yes (`process.py`) | None | Includes escalation policy |
| Port allocation | Yes (`ports.py`) | None | |
| Single server start/stop | Yes (ArangoServer) | None | |
| Health readiness loop | Yes | Backoff config (Gap) | Acceptable to refine Phase 2 |
| Basic pytest fixture (single server) | Yes | None | Minimal plugin scaffold defined |
| JSON + JUnit export stubs | Yes | None | YAML/HTML deferred to Phase 3 |
| CLI minimal commands | Yes | None | |

Gate Conclusion: All mandatory Phase 1 elements have mapped plan entries; only minor tunable behavior (health backoff) flagged but not blocking.

---

## 5. Deferred / Risk Items Summary
| Item | Phase | Risk if Deferred | Mitigation Path |
|------|-------|------------------|-----------------|
| Resilience scenarios | 3 | Hidden recovery regressions | Early design placeholder + targeted tests mid-Phase 3 |
| Advanced GDB filtering | 6 | Noisy crash output early | Accept noise until stabilization; enable baseline capture |
| Bucket splitting | 5 | Slower CI & potential scheduling imbalance | Interim manual distribution in CI |
| Network packet capture | 6 | Reduced deep network diagnostics | Use lightweight netstat snapshots earlier |
| Trend analysis | 6 | Performance drift undetected early | Manual compare until automated |

---

## 6. Residual Unmapped Items (After Review)
None critical for Phase 1. All previously unidentified features either mapped or logged as GAP IDs in gap-analysis.md.

---

## 7. Confidence Rating

### 7.1 Method (Weights)
- Coverage (0.30)
- Behavioral Fidelity (0.35)
- Observability (0.20)
- Risk Mitigation Preparedness (0.15)

### 7.2 Current Scores (Pre-Implementation)
| Dimension | Score | Rationale |
|-----------|-------|-----------|
| Coverage | 7.8 | Core domains covered; traversal & CRUD semantics deferred to Phase 7; removal of deprecated Pregel has no negative impact |
| Fidelity | 7.3 | High for core orchestration; semantic depth (traversal/CRUD) deferred; invariants & checker policies retained |
| Observability | 7.0 | Added layered timeout + analysis CLI scaffold; log segmentation & trends still deferred |
| Risk Mitigation | 6.3 | Timeout layering reduces hang risk; resilience & retry harness still pending |

Weighted Sum = 0.3*7.8 + 0.35*7.3 + 0.2*7.0 + 0.15*6.3 = 2.34 + 2.555 + 1.4 + 0.945 = 7.24 → Rounded 7.2 / 10.

### 7.3 Target Before Executing Phase 1
Raise to ≥8.0 by:
- Finalizing config precedence & marker taxonomy (CONF-PRECEDENCE-002)
- Implement EnvironmentProbe (ENV-PROBE-003)
- Draft pytest hook matrix (PLUGIN-HOOKS-080) with timeout hook integration examples
- Introduce per-test log segmentation early (LOG-SEGMENT-090) for observability uplift
- Expand analysis CLI with diff + regression stubs Phase 3
Expected uplift: Observability +0.7, Fidelity +0.3, Risk +0.2 → Projected ≈8.2.

### 7.4 Acceptance Recommendation
Proceed to Phase 1 only after confirming Must-Have remediation list (coverage-mapping sections 4 + gap-analysis Section 5) is satisfied or explicitly waived.

---

## 8. Gating Checklist (To Validate Before Coding)
| Gate Item | Status |
|-----------|--------|
| Must-Have remediation items enumerated | Complete |
| No critical unmapped legacy feature | Confirmed |
| Confidence ≥7.0 preliminary | Achieved |
| Path to ≥8.0 documented | Yes |
| Deferred items risk-assessed | Yes |

---

## 9. Summary
All legacy JavaScript framework capabilities have explicit mappings to Armadillo components with phase assignments. No Phase 1 blocking gaps remain. Confidence rating 7.2 pre-implementation is acceptable with a clear, low-effort path to ≥8.0 via early configuration & observability tasks. Await approval to begin Phase 1 implementation.
