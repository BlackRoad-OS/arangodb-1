# Gap Analysis & Unmodeled Behaviors (Pre-Phase 1 Gate)

## 1. Purpose
Identify discrepancies, omissions, and ambiguities between the legacy JS test orchestration ecosystem and the planned Armadillo Python/pytest implementation. Serve as a remediation backlog gating Phase 1 start.

---

## 2. Source Domains Reviewed
- Core orchestrator (`testing.js`)
- Instance lifecycle + manager (`instance.js`, `instance-manager.js`)
- Agency / cluster coordination (`agency.js`)
- Crash handling (`crash-utils.js`)
- Result processing & reporting (`result-processing.js`)
- Process utilities (`process-utils.js`)
- Client tools integration (`client-tools.js`)
- SUT checkers (all audited invariants)
- Traversal generic tests (extensive)
- CRUD REST vs AQL divergence
- Additional generic suites (partially referenced: optimizer interactions, concurrency harness)

---

## 3. Gaps by Category

### 3.1 Orchestration & Execution Control
| Gap | Impact | Planned Mitigation |
|-----|--------|-------------------|
| No explicit Python design for "bucket splitting" of test sets | Parallel scheduling & CI time balancing risk | Add `BucketAssigner` utility (hash-based stable partition) Phase 5 |
| Dynamic test filtering via complex pattern sets (incl. include/exclude groups, fuzzy matching) unspecified | Reduced parity with legacy selective runs | Implement filter compiler (regex + glob + tag intersection) Phase 5 |
| Retry-on-flaky facility (legacy may implicitly re-run subsets) not yet specified | Flaky test isolation risk | Introduce `FlakeRetryPolicy` with deterministic hash gating Phase 6 |
| Timeouts per test vs per suite not mapped | Potential indefinite hangs | Layered TimeoutManager (global, per-test, watchdog, signals) Phase 1 (design locked) |

### 3.2 Configuration & Environment
| Gap | Impact | Planned Mitigation |
|-----|--------|-------------------|
| Environment auto-detection matrix (enterprise vs community, sanitizer modes) only referenced implicitly | Misapplied sanitizer parsing | Add `EnvironmentProbe` that caches feature flags Phase 1 |
| Missing layered config precedence doc (env vars > CLI > file > defaults) | Ambiguity in overrides | Write config precedence spec + enforcement Phase 1 |
| No mapping for legacy JSON argument passing to server start flags (auth, replication2 toggles) | Start inconsistency | `ArangoServerArgsBuilder` per deployment type Phase 2 |

### 3.3 Instance / Cluster Management
| Gap | Impact | Planned Mitigation |
|-----|--------|-------------------|
| Hot-restart / resilience scenarios (kill + restart member) not listed | Miss regression on recovery logic | Add `ResilienceScenarioRunner` Phase 3 |
| Leader failover detection callbacks absent | Limited validation of agency leadership transitions | Implement polling + `LeadershipEventLog` Phase 3 |
| Agency state snapshot diffing (compare plan/current) not specified | Silent config drift | Add agency inspector with JSON pointer diff Phase 3 |
| Health polling jitter/backoff strategy undefined | Potential thundering herd | Exponential backoff policy Phase 2 |

### 3.4 Crash & Debugging
| Gap | Impact | Planned Mitigation |
|-----|--------|-------------------|
| GDB integration details (non-interactive scripted sessions) not ported | Loss of automated stack filtering | Implement `GdbSession` wrapper (script template + symbol demangle) Phase 6 |
| Core dump discovery logic (glob patterns, size limits) unspecified | Missed or excessive artifact capture | Add `CoreCollector` with size & count thresholds Phase 6 |
| Sanitizer (ASAN/TSAN/UBSAN) log correlation to test case not mapped | Harder triage | Tag each server stderr segment with test UUID Phase 2 |
| Intelligent stack frame filtering heuristics not enumerated | Noise in crash reports | Port rule set (internal frames prune list) Phase 6 |

### 3.5 Result Processing & Reporting
| Gap | Impact | Planned Mitigation |
|-----|--------|-------------------|
| Multi-format export (XML, JSON, YAML) parity not yet codified | Tooling integration risk (CI, dashboards) | Implement `ResultSerializer` Phase 3/5 (initial Phase 3, YAML later) |
| Performance profiling dimension list (latency, memory, network) incomplete | Partial regression detection | Define metric schema (execution, resource) Phase 5 |
| Trend baseline comparison (previous run deltas) absent | Unnoticed performance drift | Introduce optional historical cache Phase 6 |
| Integrated result analysis CLI extensions (diff, regression comparison) not fully specified | Limited post-run insight parity | Scaffold Phase 1, add diff Phase 3, regression & trend hooks Phase 6 |

### 3.6 Networking & System Metrics
| Gap | Impact | Planned Mitigation |
|-----|--------|-------------------|
| Netstat / TCP capture translation unspecified | Lost network behavior diagnostics | Provide `NetworkSnapshot` (ss / procfs parsing) Phase 2 |
| Packet capture (pcap) trigger criteria absent | Over-capture overhead | Add conditional capture on test marker Phase 6 |
| Port collision avoidance algorithm unspecified | Startup flakiness | Central `PortAllocator` with reservation file Phase 1 |

### 3.7 Client Tools Integration
| Gap | Impact | Planned Mitigation |
|-----|--------|-------------------|
| Credential / auth propagation to each tool builder not documented | Auth failures | Shared `AuthContext` injected into tool configs Phase 4 |
| Dump/restore compression/encryption matrix details missing | Coverage gap | Enumerate config matrix (compression algo x encryption flag) Phase 4 |
| Benchmark / backup tool output parsing spec absent | Unable to assert metrics | Add parsing adapters (structured stdout extraction) Phase 4 |

### 3.8 Traversal & Query Validation
| Gap | Impact | Planned Mitigation |
|-----|--------|-------------------|
| Weighted BFS tie handling fallback details minimal | Potential over-constrained tests | Use cost-bucket multiset logic (documented) Phase 7 (deferred) |
| Global uniqueness concurrency race tests unspecified | Miss parallel uniqueness issues | Add stress harness variant Phase 7 (deferred) |
| Additional optimizer rules beyond `remove-redundant-path-var` (e.g. filter move, early pruning) not enumerated | Partial optimizer coverage | Rule discovery via `EXPLAIN` dynamic map + expected subset assertions Phase 7 (deferred) |

### 3.9 CRUD & Data Integrity
| Gap | Impact | Planned Mitigation |
|-----|--------|-------------------|
| Legacy tests for revision conflict loops with backoff not captured | Under-tested write conflict resilience | Add backoff strategy tests Phase 7 (deferred) |
| Edge constraint negative tests (missing vertex doc) not enumerated | Partial validation of error codes | Add parameterized missing endpoint tests Phase 7 (deferred) |

### 3.10 SUT Checkers & Environment Cleanliness
| Gap | Impact | Planned Mitigation |
|-----|--------|-------------------|
| No checker for active queries, hot backups | Residual workload may skew metrics | Introduce optional extended checkers Phase 6 (Pregel deprecated/removed) |
| Policy severity escalation algorithm not finalized | Inconsistent triage | Implement deterministic evaluation order + tie resolution Phase 2 |
| Metrics on leak frequency not instrumented | Hard to prioritize stability work | Emit counters in JSON artifact Phase 2 |

### 3.11 Test Runner Integration
| Gap | Impact | Planned Mitigation |
|-----|--------|-------------------|
| Pytest plugin hook coverage (collection, setup, teardown, reporting) not fully mapped | Missed injection points | Draft plugin hook matrix Phase 1 |
| Marker taxonomy (cluster, slow, parallel, sanitizer, failpoint) not listed | Unclear filtering semantics | Define markers + docs Phase 1 |
| Parallel execution isolation strategy (tmp dirs, ports, logs) not fully defined | Cross-test interference | Namespaced run directory tree Phase 1 |

### 3.12 Observability & Logs
| Gap | Impact | Planned Mitigation |
|-----|--------|-------------------|
| Structured log slicing per test window not defined | Harder per-test diagnostics | Log segmenter w/ monotonic sequence Phase 2 |
| Aggregated error index (by error code, frequency) absent | Low regression visibility | Build `ErrorCatalog` Phase 5 |

### 3.13 Security / Auth
| Gap | Impact | Planned Mitigation |
|-----|--------|-------------------|
| JWT rotation / expiration scenario tests absent | Auth renewal regressions | Add token expiry simulation Phase 4 |
| Mixed auth mode (basic vs JWT) fallback tests absent | Partial coverage | Dual-mode fixture Phase 4 |

### 3.14 Reliability / Flakiness
| Gap | Impact | Planned Mitigation |
|-----|--------|-------------------|
| Flake classification taxonomy (infra vs logic vs timing) not defined | Hard remediation prioritization | Tagging ruleset Phase 6 |
| Deterministic seed handling (random data builders) unspecified | Non-reproducible failures | Global seed registry Phase 1 |

### 3.15 Performance & Resource
| Gap | Impact | Planned Mitigation |
|-----|--------|-------------------|
| Peak memory measurement fallback (RSS delta noise) unresolved | Flaky memory assertions | Calibrate noise threshold & warmup Phase 5 |
| CPU saturation guard for parallel tests not defined | Noisy perf data | Capture per-test CPU load (procstat) Phase 5 |

---

## 4. Risk Register (Top)
| Risk | Likelihood | Impact | Mitigation Reference |
|------|-----------|--------|----------------------|
| Missing bucket splitting delays CI | M | M | 3.1 (BucketAssigner) |
| Unmodeled crash filtering noise | M | H | 3.4 (GdbSession + filters) |
| Optimizer coverage incomplete | H | M | 3.8 dynamic rule discovery |
| Partial network metrics parity | M | M | 3.6 NetworkSnapshot |
| Memory metric instability | M | M | 3.15 threshold calibration |

---

## 5. Priority Remediation (Before Phase 1 start)
| Must-Have | Rationale |
|-----------|-----------|
| Config precedence & markers taxonomy | Foundation for all test classification |
| Port allocator + deterministic seed | Ensures stable isolation |
| Pytest plugin hook matrix draft | Enables incremental integration |
| EnvironmentProbe (sanitizer, cluster flags) | Drives conditional logic |

---

## 6. Deferable (Safe Post-Phase 1)
| Item | Reason |
|------|--------|
| Core dump symbolic filtering | Only needed when crash features engaged (Phase 6) |
| Extended checkers (backups, active queries) | Non-critical early coverage (Pregel deprecated) |
| Performance historical baselining | Adds storage overhead early |

---

## 7. Unresolved Ambiguities
| Topic | Decision Needed |
|-------|-----------------|
| Scope of automatic remediation policy (failpoints only or include tasks?) | Define to avoid hidden masking |
| Baseline snapshot granularity (session vs per-test) for collections | Trade-off speed vs precision |
| Inclusion of network packet capture default | Likely opt-in via marker |

---

## 8. Traceability Additions (New Requirement IDs)
| ID | Description |
|----|-------------|
| ORCH-BUCKET-001 | Deterministic bucket splitting |
| CONF-PRECEDENCE-002 | Config source override order enforced |
| ENV-PROBE-003 | Sanitizer & cluster feature detection |
| INST-RESILIENCE-010 | Restart + recovery scenario coverage |
| CRASH-GDB-020 | Scripted GDB stack filtering |
| RES-PERF-MEM-030 | Memory threshold comparator noise calibration |
| CRUD-RETRY-040 | Write conflict retry harness |
| NET-SNAPSHOT-050 | Netstat & connection snapshot |
| TOOL-AUTH-060 | Propagation of auth context to client tools |
| CHECK-POLICY-070 | Severity escalation deterministic |
| PLUGIN-HOOKS-080 | Pytest hook integration matrix complete |
| LOG-SEGMENT-090 | Per-test log segmentation implemented |

---

## 9. Confidence Rating Methodology
Dimensions:
1. Coverage completeness (features mapped)
2. Behavioral fidelity (semantic nuanced parity)
3. Observability (diagnostics sufficiency)
4. Risk mitigation readiness

Scoring (0-10 each, weighted: 0.3,0.35,0.2,0.15). Final = weighted sum.

Current preliminary (pre-remediation):
- Coverage: 8 (most major areas mapped; minor optimizer & resilience gaps)
- Fidelity: 7.5 (crash & partial success mapped; some resilience & advanced optimizer incomplete)
- Observability: 6.5 (log segmentation & perf baseline lacking)
- Risk Mitigation: 6 (policies & retries pending)
Weighted = 0.3*8 + 0.35*7.5 + 0.2*6.5 + 0.15*6 = 2.4 + 2.625 + 1.3 + 0.9 = 7.225 → Rounded 7.2/10 BEFORE implementing Must-Have remediation list.

Target before Phase 1 start: ≥8.0 (raise Observability + Risk).

---

## 10. Summary
Gaps identified largely cluster around resilience scenarios, advanced crash/debug tooling, dynamic optimizer rule breadth, and observability/policy layers. None block initial Phase 1 core infrastructure so long as Must-Have remediation items are addressed first. Proceed only after signing off that Section 5 items are implemented or formally accepted as early-phase tasks.
