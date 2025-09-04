# Integrated Result Analysis CLI Design

## 1. Objectives
Replace the standalone `scripts/examine_results.js` with a first‑class, extensible Armadillo CLI subcommand:
- Unified access to all result analyzers
- Modern Python extensibility (entry points / plugin registry)
- Consistent output formatting (Rich tables, JSON, YAML, JUnit, colored summaries)
- Supports multi-file aggregation and pairwise comparison (baseline vs candidate)
- Seamless integration with framework metadata (checker results, crash artifacts, resource stats)

Traversal & CRUD test suites are deferred; this analysis layer must remain agnostic to their future validators.

## 2. Scope (Initial Set)
Parity with existing analyzers:
| Legacy Analyzer | New Name | Purpose |
|-----------------|----------|---------|
| unitTestPrettyPrintResults | pretty | Human summary + failures file |
| saveToJunitXML | junit | JUnit XML export |
| locateLongRunning | long-running | Top N slow tests |
| locateShortServerLife | short-lifetime | Inefficient suite startup/teardown ratio |
| locateLongSetupTeardown | long-setup-teardown | Excessive setup/teardown time detection |
| yaml | yaml | YAML dump of raw JSON |
| unitTestTabularPrintResults | table | Column-oriented statistics |

Extensions (Phase 1–3 incremental):
| New Analyzer | Purpose |
|--------------|---------|
| resources | Summarize process / memory / network deltas |
| leaks | Summarize checker violations across runs |
| flake-delta (Phase ≥3) | Compare multiple historical files to detect timing variance |
| crash-summary (Phase 4+) | Extract crash / sanitizer synopsis |
| perf-regression (Phase ≥5) | Threshold comparison vs baseline file |

## 3. Data Model
All test run JSON files normalized into:
```
RunEnvelope {
  framework_version: str
  timestamp_utc: str
  duration_s: float
  tests: dict[str, TestRecord]
  meta: {
    process_stats: {...},
    checker_summary: {...},
    crashreport?: str,
    environment: {...}
  }
}

TestRecord {
  name: str
  status: "passed|failed|skipped|error|timeout|crashed"
  duration_s: float
  setup_duration_s: float
  teardown_duration_s: float
  process_contrib?: dict
  failure_message?: str
  checker_violations?: list
}
```
A lightweight schema validator ensures forward compatibility.

## 4. CLI Command
```
armadillo results analyze \
  --file UNITTEST_RESULT.json [--file other.json ...] \
  [--compare baseline.json] \
  [--analyzers pretty,table,long-running] \
  [--table-columns duration,status,totalSetUp,totalTearDown,residentSize] \
  [--top 15] \
  [--junit-out junit.xml] \
  [--yaml-out run.yaml] \
  [--fail-on slow>30s,failures>0] \
  [--output-format rich|plain|json] \
  [--list-analyzers]
```

## 5. Analyzer Execution Flow
1. Load all primary files (N). If `--compare` provided, also load baseline.
2. Normalize envelopes; attach logical run id.
3. Resolve analyzer names (validate; show suggestions on typos).
4. Execute analyzers in declared order; each returns an `AnalyzerResult`.
5. Aggregate severity (INFO/WARN/FAIL) for optional non-zero exit code.

```
AnalyzerResult {
  name: str
  status: "ok|warn|fail"
  summary: str
  artifacts: dict[str, Any]   # structured (tables, series)
  generated_files: list[Path]
}
```

## 6. Analyzer API
```
class ResultAnalyzer(Protocol):
    name: ClassVar[str]
    supports_compare: ClassVar[bool] = False
    def run(self, ctx: AnalysisContext) -> AnalyzerResult: ...
```

`AnalysisContext` exposes:
- `runs: list[RunEnvelope]`
- `baseline: RunEnvelope | None`
- convenience selectors (`all_tests()`, `tests_by_status(status)`)
- column resolver registry

Registration:
```
ANALYZERS: dict[str, ResultAnalyzer] = {}
def register(analyzer_cls): ANALYZERS[analyzer_cls.name] = analyzer_cls; return analyzer_cls
```
Future: setuptools entry points (`armadillo.results.analyzers`) for external plugins.

## 7. Table Column Resolver Strategy
Columns specified via dotted paths or functional aliases:
- Direct JSON path: `processStats.sum_servers.residentSize`
- Alias mapping: `duration` -> `test.duration_s`
- Derived: `setup_ratio` -> `test.setup_duration_s / max(0.001,test.duration_s)`

Resolver registry:
```
COLUMN_RESOLVERS: dict[str, Callable[[TestRecord, RunEnvelope], Any]]
```
Unresolvable columns produce warning unless `--strict-columns`.

## 8. Performance Considerations
- Streaming JSON parse (ijson) optional for very large files (defer if initial files small)
- Memoize expensive derived metrics (e.g. aggregated process deltas)
- Analyzers operate on in-memory normalized structures; size dominated by test count

## 9. Parallel vs Sequential Analysis
Initial implementation: sequential (I/O bound minimal).
Future: optional thread pool for CPU heavy diff / statistical variance analyzers.

## 10. Exit Code Policy
| Condition | Exit Code |
|-----------|-----------|
| Any analyzer status == fail OR `--fail-on` predicate true | 2 |
| CLI usage / validation error | 1 |
| Success | 0 |

`--fail-on` grammar examples:
- `fail-on failures>0`
- `fail-on slow>10s` (max test duration)
- `fail-on crashCount>0`

Predicate parser supported metrics:
`failures`, `errors`, `timeouts`, `crashCount`, `maxDuration`, `medianDuration`.

## 11. Implementation Phasing
| Phase | Deliverables |
|-------|--------------|
| 1 | Command skeleton, loader, pretty, table, junit, yaml |
| 2 | long-running, short-lifetime, long-setup-teardown, resources |
| 3 | leaks (checker aggregation), flake-delta groundwork |
| 4 | crash-summary (uses crash analyzer metadata) |
| 5 | perf-regression thresholds (once profiling stable) |
| ≥6 | historical DB/storage & variance statistics |

Traversal / CRUD specific analyzers explicitly deferred until post-core test parity.

## 12. Test Timeout Strategy (Integrated)
(Responding to new requirement)
- Pytest native: integrate `pytest-timeout` plugin if available OR internal enforcement.
- Internal fallback:
  - Phase 1: per-test global watchdog using `pytest_runtest_call` hook + `TimeoutManager`.
  - Async tests: `asyncio.wait_for`.
  - Sync tests: POSIX `signal.setitimer` (Linux only) + graceful exception; escalate to hard kill if stuck in C extensions.
  - Config surface:
    - `--test-timeout 900` (global)
    - Marker override: `@pytest.mark.timeout(120)`
    - Suite-level via ini: `[armadillo] default_test_timeout = 600`
  - Timeout taxonomy: `setup_timeout`, `call_timeout`, `teardown_timeout` tracked separately in results JSON.
- Result analyzer integration: highlight top timeout ratio tests.

## 13. JSON Schema (Draft)
```
{
  "framework_version": "1.0.0",
  "timestamp_utc": "...",
  "tests": {
     "suite/test_file::test_case": {
        "status": "passed",
        "duration_s": 1.234,
        "setup_duration_s": 0.02,
        "teardown_duration_s": 0.01,
        "timeout_budget_s": 10.0,
        "process_contrib": {
          "resident_delta": 123456
        }
     }
  },
  "meta": {
     "checker_summary": {
       "fail": 0,
       "warn": 1
     },
     "crashreport": "...optional...",
     "environment": {
       "deployment_mode": "single_server",
       "cluster": false
     }
  }
}
```

## 14. Security / Robustness
- Validate JSON size (< configurable cap) to prevent accidental huge ingestion
- Safe YAML emission (no custom tags)
- Defensive try/except around individual analyzers (one failure does not cancel others)
- Color output only when TTY (auto-detect)

## 15. Example Usage
```
armadillo results analyze --file out/UNITTEST_RESULT.json --analyzers pretty,table \
  --table-columns duration,status,residentSize --junit-out junit.xml

armadillo results analyze --file runA.json --compare runB.json \
  --analyzers long-running,resources --top 20 --fail-on failures>0
```

## 16. Future Enhancements (Deferred)
| Idea | Rationale |
|------|-----------|
| SQLite result cache | Multi-run statistical analysis |
| HTML dashboard exporter | Rich interactive drill-down |
| Trend sparkline columns | Visual regression spotting |
| Pluggable anomaly detectors | Outlier detection per metric |

## 17. Risks & Mitigations
| Risk | Mitigation |
|------|------------|
| Large file memory spike | Incremental parse (ijson) later |
| Column drift with new metrics | Column resolver warns + suggests |
| Analyzer API churn | Version in analyzer result metadata |
| Timeout false positives (system load) | Allow per-test grace multiplier marker |

## 18. Summary
A dedicated `armadillo results analyze` subcommand consolidates and extends legacy result examination functionality with a typed, extensible architecture, early integration of timeout metadata, and a clear phased roadmap. Traversal & CRUD specific analysis deferred until after core framework stabilization, aligning with updated prioritization.
