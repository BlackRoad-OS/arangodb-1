# SUT Checker Base Abstraction & Analyzer Checker Pattern

## 1. Purpose
SUT (System Under Test) checkers enforce *post-test environmental cleanliness and invariants* across ArangoDB instances. They detect leaked resources, lingering failure points, orphaned tasks, or state mutations that would cause flakiness, cross-test interference, or misleading performance signals.

The Analyzer Checker serves as the canonical exemplar: snapshot pre-test state (list of analyzers) → after test compare → fail if unexpected additions/removals.

---

## 2. Core Design Goals
| Goal | Rationale |
|------|-----------|
| Deterministic cleanup validation | Prevent test-order dependence |
| Low false-positive rate | Avoid masking genuine regressions with broad ignore lists |
| Uniform interface | Enables batched execution & report aggregation |
| Extensible | New resource domains (e.g. views, analyzers, failure points) plug in smoothly |
| Fast & side-effect free | Checker execution must not mutate SUT state (read-only except sanctioned resets) |
| Rich diagnostics | Provide actionable diff details (added/removed identifiers) |
| Phase-aware | Some invariants only meaningful once cluster fully healthy |

---

## 3. Canonical Lifecycle (Per Test)
1. Pre-test snapshot (during fixture/session setup)
2. Test executes (possibly mutating system)
3. Post-test phase:
   - Sequential (or parallel-safe) execution of registered checkers
   - Each checker gathers current state
   - Computes delta vs snapshot
   - Emits Result (pass / fail / skipped / soft-warning)
4. Aggregator collates & attaches to test outcome
5. Optional remediation (e.g. clearing stray failure points) for continuity

---

## 4. JS Pattern (Generalized)
```
checker.setUp():
  baseline = snapshot_state()

checker.runCheck():
  current = snapshot_state()
  diff = diff_arrays(baseline, current)
  assert diff empty (with domain-specific ignores)
```
Shared helper: `tu.diffArray(a, b)` (produces {added, removed}).

Analyzer Checker specifics:
- Snapshot: list of analyzer names
- Ignore: system-default analyzers (baseline already includes them)
- Fail if any added or removed

---

## 5. Resource Domains (Handled by Other Checkers)
(Details of invariants deferred to separate consolidated invariants document)
- Collections
- Databases
- Graph Definitions
- Views
- Users
- Tasks (async server tasks)
- Transactions
- Failure Points (fault injection)
- Analyzers

---

## 6. Failure Classification
| Class | Condition | Test Impact |
|-------|-----------|-------------|
| HARD_FAIL | Non-empty diff violating invariant (e.g. leaked collection) | Mark test failed |
| SOFT_FAIL / WARN | Known intermittent issue, tagged for future resolution | Mark xfailed / add warning |
| SKIPPED | Checker not applicable in mode (e.g. cluster-only) | No effect |
| REMEDIATED | Violation auto-cleaned (e.g. cleared failpoint) | Test failed unless policy allows auto-clean success |

Policy file (planned): `armadillo/checkers/policy.yaml` controlling escalation.

---

## 7. Python Abstraction (Proposed API)
```
class CheckerResult(NamedTuple):
    name: str
    status: Literal["pass","fail","warn","skip","remediated"]
    details: dict
    message: str
    duration_s: float

class SUTChecker(ABC):
    name: ClassVar[str]
    priority: ClassVar[int] = 100  # ordering
    applicable_modes: ClassVar[set[str]] = {"single","cluster"}

    def __init__(self, ctx: "ArmadilloContext"):
        self.ctx = ctx
        self._snapshot = None

    def set_up(self) -> None:
        self._snapshot = self.capture_baseline()

    @abstractmethod
    def capture_baseline(self) -> object: ...

    @abstractmethod
    def capture_current(self) -> object: ...

    @abstractmethod
    def diff(self, baseline, current) -> dict: ...
        # returns structured difference

    def evaluate(self, diff: dict) -> CheckerResult:
        # default: pass if empty diff else fail
        ...

    def run(self) -> CheckerResult:
        start = time.time()
        current = self.capture_current()
        diff = self.diff(self._snapshot, current)
        result = self.evaluate(diff)
        return result._replace(duration_s=time.time() - start)
```

Registration:
```
CHECKER_REGISTRY: list[type[SUTChecker]] = []
def register(cls):
    CHECKER_REGISTRY.append(cls)
    return cls
```

Execution orchestrator sorts by `priority` (e.g. failure points early to allow cleanup before other snapshots are interpreted).

---

## 8. Analyzer Checker (Python Port Sketch)
```
@register
class AnalyzerChecker(SUTChecker):
    name = "analyzers"

    def capture_baseline(self):
        return self.ctx.client.list_analyzers()

    capture_current = capture_baseline

    def diff(self, baseline, current):
        b = set(baseline); c = set(current)
        return {
            "added": sorted(c - b),
            "removed": sorted(b - c),
        }

    def evaluate(self, diff):
        if not diff["added"] and not diff["removed"]:
            return CheckerResult(self.name, "pass", diff, "Analyzer set stable", 0.0)
        return CheckerResult(
            self.name,
            "fail",
            diff,
            f"Analyzer changes detected: added={diff['added']} removed={diff['removed']}",
            0.0
        )
```

---

## 9. Aggregation & Reporting
Pytest plugin hook (`pytest_runtest_teardown`) triggers checker execution. Results appended to:
- JSON report (`artifacts/checkers.json`)
- Structured per-test metadata (for flakiness analytics)
- Console summary (failures only)

Fail-fast option: stop executing remaining checkers after first HARD_FAIL (configurable).

---

## 10. Performance Considerations
| Concern | Mitigation |
|---------|------------|
| Multiple HTTP round-trips | Batch endpoints (future optimization) |
| Large diff sets | Truncate display; keep full data in JSON artifact |
| Contention with test cleanup | Run after application-level teardown but before global fixtures finalize |

Snapshots stored lightweight (names/ids only). No heavy payload retention.

---

## 11. Concurrency & Isolation
- Single-threaded execution per test to avoid race with teardown.
- Cluster mode: checker optionally targets coordinator or each DBServer depending on resource domain (future extension: multi-instance fan-out via InstanceManager APIs).
- Failure points checker may *clear* orphaned failpoints (policy-controlled remediation).

---

## 12. Extensibility Patterns
| Need | Extension Mechanism |
|------|---------------------|
| New resource | Subclass + register |
| Mode-specific skip | Override `applicable_modes` |
| Soft warning | Override `evaluate` to downgrade severity |
| Custom diff algorithm | Provide specialized `diff` (e.g. hierarchical structure) |

---

## 13. Error Diagnostics Standards
Message SHOULD include:
- Compact human-readable summary
- Machine-parseable diff in `details`
- Optional suggested remediation (if safe)

Example:
```
Analyzer changes detected: added=['text_fr'] removed=[]
```

---

## 14. Integration With Test Runner Outcome
| Checker Status | Test Outcome Influence |
|----------------|------------------------|
| pass | none |
| fail | test marked failed |
| warn | attaches pytest warning (does not fail) |
| skip | none |
| remediated | configurable: fail or warn |

Central policy resolves conflicts if multiple fails: first failure drives message; all aggregated in diagnostics section.

---

## 15. Mapping From JS Concepts
| JS Element | Python Abstraction |
|------------|-------------------|
| `tu.diffArray` | `diff()` returning ordered set differences |
| `setUp` snapshot | `capture_baseline()` inside `set_up()` |
| `runCheck` | `run()` sequence |
| `runner.setResult` | Pytest plugin collects `CheckerResult` |
| Multiple checker modules | Registry of subclasses |
| Silent success | Only failures/warnings printed |

---

## 16. Testing the Checkers Themselves
Meta-tests:
1. Intentional leak: create analyzer, omit deletion → expect fail
2. No change scenario → pass
3. Policy transformation (fail → warn) respected via config override
4. Parallel unrelated test ensures isolation (no cross-test state corrupting snapshot)

Fixtures supply ephemeral analyzer creation utility.

---

## 17. Failure Mode Scenarios
| Scenario | Expected Checker Behavior |
|----------|--------------------------|
| HTTP error capturing current state | Mark checker failed with transport error classification |
| Snapshot missing (programming error) | Raise internal error → framework error summary |
| Baseline stale due to re-init | Re-snapshot logic (future optimization) |

---

## 18. Planned File Structure (Partial)
```
armadillo/checkers/
  __init__.py
  base.py               # SUTChecker, CheckerResult, registry
  policy.py             # Severity escalation rules
  analyzers.py          # AnalyzerChecker
  collections.py
  databases.py
  graphs.py
  views.py
  users.py
  tasks.py
  transactions.py
  failurepoints.py
  runner.py             # Execution orchestration
tests/
  test_checkers_analyzers.py
  test_checkers_policy.py
```

---

## 19. Configuration Surface
`[armadillo.checkers]` section in config (TOML/YAML):
```
enabled = ["analyzers","collections","databases","graphs","views","users","tasks","transactions","failurepoints"]
fail_on = ["fail","remediated"]      # treat remediated as failure
warn_on = ["warn"]
policy_file = "checkers-policy.yaml"
```

---

## 20. Summary
This document defines the uniform checker abstraction and demonstrates the Analyzer Checker pattern that models snapshot/diff-based invariant enforcement. It standardizes lifecycle, severity handling, registration, reporting, and extensibility for all SUT cleanliness validations required before porting traversal and advanced test logic.
