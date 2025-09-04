# Armadillo Phase 1 Planning Checklist (Pre-Implementation Gate)

Status: Planning mode (implementation paused at user request)

## 0. Current Implemented Foundations (Will NOT proceed further until approval)
- Implemented modules (draft quality, pending validation): `core.errors`, `core.log`, `core.config`, `core.time`, `core.process`
- Not yet integrated / tested: ArangoServer wrapper, health checks, plugin, result writer, CLI

## 1. Component Inventory (Phase 1 Target Scope)
| Component | Purpose | Notes |
|-----------|---------|-------|
| Error Hierarchy | Unified semantic failure taxonomy | Already drafted |
| Logging Subsystem | Structured + JSON logging + static context | Draft present |
| Configuration Loader | Immutable env + overrides resolution | Draft present |
| Timeout Manager | Layered deadlines (global run, per-test, watchdog, signal escalation) + clamp helpers | Draft present |
| Process Executor | One-shot commands w/ deadline clamp | Draft present |
| Process Supervisor | Long-running process mgmt + escalation | Draft present |
| Filesystem Service | Safe path ops, temp/work allocation, atomic writes | Planned |
| Crypto Service | Hashing (sha256, md5), random IDs, nonce registry | Planned |
| Auth Provider (JWT HMAC) | Token issuance (alg=HS256) + expiry | Planned |
| DataCodec (JSON) | Encapsulation; future VPack slot | Planned |
| Result Analysis CLI Scaffold | `armadillo analyze` loads JSON results & prints summary | Planned |
| ArangoServer Wrapper | Start/stop single server + env prep | Planned |
| Health Check Utility | HTTP reachability + classification | Planned |
| Pytest Plugin | Fixture: `arango_single_server`, markers scaffold | Planned |
| Result Writer (Minimal) | JSON + JUnit basic emission | Planned |
| CLI Skeleton | `armadillo` Typer entry stub | Planned |
| Documentation (Phase 1) | Dev setup, component overview, examples | Planned |

## 2. Cross-Cutting Concerns & Policies
- Deadlines: Layered timeout enforcement (global suite deadline, per-test mapping, cooperative async cancellation, watchdog thread, TERM→KILL escalation) via `TimeoutManager` and `clamp()`.
- Errors: No raw `Exception` escapes; mapped to domain classes.
- Logging: Emit canonical event names (`proc.exec.ok`, `server.start`, etc.).
- Paths: Use `config.derive_sub_tmp()` for deterministic artifact layout.
- Extensibility: Public interfaces minimal & protocol-oriented (e.g. DataCodec).

## 3. Proposed Acceptance / Exit Criteria (Per Component)
- Timeout Manager: Nested scope (outer=10, inner=5) ⇒ `remaining() <= 5.0`; watchdog triggers forced escalation event logged; simulated hang emits `timeout.watchdog.fired`.
- ProcessExecutor: Forced timeout raises `TimeoutExpired` with command context.
- ProcessSupervisor: Abnormal exit triggers `CrashDetected` with truncated buffers.
- Filesystem Service: `atomic_write()` guarantees full file contents even if interrupted (best-effort).
- Crypto Service: `sha256(data)` stable hash; `random_id()` uniqueness over 10k samples; nonce reuse raises.
- Auth Provider: `authorization_header()` returns `Bearer <jwt>`; `exp` claim within ±2s of requested ttl.
- DataCodec: `encode/decode` round-trip JSON primitives & nested structures; errors raise `CodecError`.
- ArangoServer: Start returns when process spawned AND health endpoint returns 200 (within timeout).
- Health Check: Distinguish connect refusal vs HTTP non-200 (different exception types or attributes).
- Pytest Plugin: Fixture starts server once per test using scope (session or function TBD) & ensures teardown.
- Result Writer: Produces minimal JSON summary and JUnit XML with test count, failures, durations.
- Analysis CLI Scaffold: `armadillo analyze <json>` prints summary table (total, passed, failed, duration) and exits 0; missing file exits >0 with clear message.
- CLI Skeleton: `armadillo --help` exits 0 and shows top-level verbs; `armadillo test` dry-run placeholder.

## 4. Interface Sketches (Draft – For Approval)

### FilesystemService
```
class FilesystemService:
    def __init__(self, config: ArmadilloConfig): ...
    def work_dir(self) -> Path
    def server_dir(self, name: str) -> Path
    def atomic_write(self, path: Path, data: bytes | str, mode: str = "w") -> None
    def read_text(self, path: Path) -> str
```

### CryptoService
```
class CryptoService:
    def sha256(self, data: bytes | str) -> str
    def md5(self, data: bytes | str) -> str
    def random_id(self, length: int = 16) -> str
    def register_nonce(self, nonce: str) -> None  # raises on replay
```

### AuthProvider
```
class AuthProvider:
    def __init__(self, secret: str, algorithm: str = "HS256"): ...
    def issue_jwt(self, *, ttl: float = 3600, claims: dict | None = None) -> str
    def authorization_header(self) -> dict[str, str]
```

### DataCodec (Protocol + JSON)
```
class DataCodec(Protocol):
    def encode(self, obj: Any) -> bytes
    def decode(self, data: bytes) -> Any
class JsonCodec(DataCodec): ...
```

### ArangoServer
```
class ArangoServer:
    def __init__(self, config: ArmadilloConfig, fs: FilesystemService, process: ProcessSupervisor, codec: DataCodec, auth: AuthProvider | None)
    def start(self, timeout: float | None = None) -> None
    def stop(self, timeout: float | None = None) -> None
    def is_running(self) -> bool
    def endpoint(self) -> str
    def health(self, timeout: float | None = None) -> dict  # raises HealthCheckError
```

### Health Check Utility
```
def simple_health_check(url: str, timeout: float | None) -> dict  # raises HealthCheckError / NetworkError
```

### Pytest Plugin (outline)
```
def pytest_addoption(parser)
def pytest_configure(config)
@pytest.fixture(scope="session")
def arango_single_server(request): ...
```

### Result Writer
```
class ResultWriter:
    def record_test(self, name: str, outcome: str, duration: float, error: str | None = None) -> None
    def write_json(self, path: Path) -> None
    def write_junit(self, path: Path) -> None
```

### CLI
```
typer.App:
  armadillo test [--bin-dir PATH] [--json-results PATH] (future expansion)
```

## 5. Risks & Mitigations (Concise)
| Risk | Mitigation |
|------|------------|
| Over-fitting early interfaces | Keep minimal, add via extension not mutation |
| JWT dependency bloat | Use `pyjwt` already declared; isolate usage |
| Future async refactor | Avoid leaking threading primitives in public APIs |
| VPack introduction | Use codec protocol boundary now |

## 6. Open Decisions Needing User Confirmation
1. Pytest fixture scope for single server (session vs function) – recommend session for performance.
2. Whether result writer needs per-test incremental flush in Phase 1 (recommend deferred).
3. Analysis CLI Phase 1 scope: summary only vs early diff (recommend summary only; diff Phase 3).
4. Accept inclusion of `pyjwt` (lightweight) now; defer `cryptography` unless advanced signing needed.
5. Confirm Python baseline remains 3.9+ (matches implementation_plan) not 3.11+.

## 7. Pending Planning Actions (Before Writing More Code)
- Approve / adjust interface sketches (updated for layered timeout + analysis CLI)
- Lock fixture scope decision
- Confirm acceptance criteria granularity (added watchdog + analysis CLI)
- Confirm minimal dependency set (pyjwt included; cryptography deferred)
- Approve risk table & cross-cutting policies
- Author short "Phase 1 README section" outline (include timeout layering + analyze command)
- Green-light implementation resume

## 8. Next Steps After Approval
1. Implement FilesystemService & CryptoService + unit tests
2. Implement AuthProvider + tests
3. Implement DataCodec(JSON) + tests
4. Implement ArangoServer + health check utility + tests (using real binary once available)
5. Implement pytest plugin & minimal result writer
6. Implement CLI skeleton
7. Documentation + consolidation pass
8. Phase 1 audit

---

Please review and indicate:
- Changes required
- Additional components or risks
- Approval to proceed to locked interface spec finalization
