# testing.js - Main Test Framework Entry Point

## Purpose
Main orchestration module that serves as the entry point for the entire ArangoDB testing framework. Provides command-line interface, test suite discovery, execution coordination, and result aggregation.

## Core Functionality

### Test Suite Management
- **Dynamic Test Suite Loading**: Automatically discovers and loads test suites from `@arangodb/testsuites/` directory
- **Test Function Registry**: Maintains a registry of all available test functions with documentation
- **Module Option Registration**: Collects configuration options from all framework modules
- **Wildcard Expansion**: Supports wildcard patterns in test suite names (e.g., `cluster*`)

### Test Discovery and Filtering
- **Test Case Discovery**: `findTestCases()` scans test paths and applies filters
- **Pattern Matching**: Supports complex test filtering by name patterns and file paths
- **Cluster Test Detection**: Automatically detects cluster-specific tests by naming convention
- **Auto Test Resolution**: `autoTest()` automatically finds and runs matching test suites

### Command-Line Interface
- **Argument Parsing**: Comprehensive CLI argument processing with defaults
- **Usage Documentation**: Dynamic help generation from registered test functions
- **Option Validation**: Configuration option validation and normalization
- **Completion Support**: `dumpCompletions()` provides shell completion data

### Test Execution Orchestration
- **Sequential Execution**: `iterateTests()` manages ordered test suite execution
- **Failed Test Re-runs**: Support for re-running only previously failed tests
- **Multiple Option Sets**: Support for running same test with different configurations via `optionsJson`
- **Instance Management**: Coordinates with instance manager for test isolation

### Result Processing and Aggregation
- **Status Aggregation**: Collects and normalizes results across all test suites
- **Global Status Tracking**: Maintains overall pass/fail status across test runs
- **Crash Detection**: Integrates with process utilities to detect server crashes
- **Result Normalization**: Standardizes result formats from different test runners

### Configuration Management
- **Default Options**: Comprehensive set of default configuration options
- **Option Inheritance**: Supports option inheritance and overrides
- **Environment Integration**: Integrates with environment variables and external configuration
- **Module Registration**: Allows test modules to register their own configuration options

### Error Handling and Debugging
- **Exception Handling**: Comprehensive exception handling during test execution
- **Verbose Logging**: Multiple verbosity levels for debugging
- **Signal Handling**: Interrupt handling for graceful test termination
- **Error Propagation**: Proper error propagation with stack traces

## Key Configuration Options

### Execution Control
- `force`: Continue execution even if tests fail
- `cleanup`: Whether to remove data files and logs after tests
- `extremeVerbosity`: Detailed logging for debugging
- `failed`: Re-run only previously failed tests
- `oneTestTimeout`: Timeout for individual test suites

### Protocol and Communication
- `protocol`: Communication protocol (tcp, ssl, unix)
- `vst`/`http2`: Enable VST or HTTP/2 protocols
- `forceJson`: Disable VPack compression for debugging
- `username`/`password`: Authentication credentials

### Test Selection and Filtering
- `test`: Test name filter patterns
- `testBuckets`: Test bucketing for parallel execution
- `suffix`: Append suffix to test result names

## Integration Points
- **Process Utils**: Binary setup and process management
- **Result Processing**: Result collection and export
- **Crash Utils**: Crash detection and analysis
- **Test Utils**: Test discovery and filtering utilities
- **Instance Management**: Server instance coordination

## Arangosh V8 Extension Dependencies

The legacy entry point indirectly relies on a broad V8-embedded C++ utility surface exposed into arangosh. These functions are not ordinary Node.js APIs and must be mapped or emulated.

### Filesystem & Archives
- FS_EXISTS / FS_READ / FS_WRITE / FS_LIST / FS_LIST_TREE / FS_REMOVE(_DIRECTORY/_RECURSIVE)
- FS_ZIP_FILE / FS_UNZIP_FILE / FS_ADLER32
Python plan:
- Phase 1: Wrap pathlib + os + shutil + zipfile + hashlib (adler32 via zlib.adler32)
- Provide thin `fs` helper with controlled root (future sandbox)
Deferred: Full tree diffing, advanced permission modeling.

### System / Process
- SYS_EXECUTE_EXTERNAL / SYS_STATUS_EXTERNAL / SYS_KILL_EXTERNAL / SYS_SET_PRIORITY_EXTERNAL
- SYS_PROCESS_STATISTICS / SYS_GET_PID / SYS_TEST_PORT
- SYS_SLEEP, SYS_WAIT (with deadline clamping)
- Pipes: SYS_READPIPE / SYS_WRITEPIPE / SYS_CLOSEPIPE
Python plan:
- Phase 1: subprocess (Popen), psutil (optional) for statistics, custom ProcessSupervisor
- Port probing via socket.bind
- Priority nice/ionice (Linux) deferred (Phase 6 optional)
- Implement monotonic deadline aware sleep wrapper.

### Networking / HTTP
- SYS_DOWNLOAD (redirects, custom headers, timeout, VPack detection)
Python plan:
- Phase 1: Minimal HTTP via httpx/requests with streaming download & checksum
- Redirect & timeout support native
Deferred: Automatic VPack detection (JSON-only initial).

### Data Conversion
- VPACK_TO_V8 / V8_TO_VPACK (VelocyPack ↔ JS)
Python plan:
- Phase 1: JSON-only (HTTP JSON endpoints)
- Future optional: python-arango / velocypack module adapter
Decision: Provide abstraction `DataCodec` with strategy interface; default = JSON.

### Crypto / Hashing
- SYS_MD5, SYS_SHA{1,224,256,384,512}, SYS_HMAC, SYS_PBKDF2, SYS_PBKDF2HS1, SYS_RSAPRIVSIGN
Python plan:
- hashlib + hmac + hashlib.pbkdf2_hmac
- RSA signing deferred (Phase 4+ if required by auth tooling)
- Expose via `crypto` helper.

### Random / Nonce
- SYS_GEN_RANDOM_NUMBERS / _ALPHA_NUMBERS / _SALT
- SYS_CREATE_NONCE / SYS_CHECK_AND_MARK_NONCE
Python plan:
- secrets (token_urlsafe / choice) + tracking set for nonce reuse detection.

### Deadline / Timeout
- correctTimeoutToExecutionDeadline(S/ms)
- isExecutionDeadlineReached
Python plan:
- TimeoutManager: global execution_deadline (monotonic), `clamp_timeout(requested)`
- Integrate into process waits & sleeps.

### Logging
- SYS_LOG / SYS_LOG_LEVEL + topic-based adjustments
Python plan:
- Structured logging (logging.Logger) with levels, colorized formatter (Phase 1)
- Topic granularity simulated via hierarchical logger names.

### Errors
- JS_ArangoError construction (error codes, message enrichment)
Python plan:
- Custom ArmadilloError with code, cause, metadata.

### Buffer / Binary
- V8 Buffer operations (slicing, base64/hex, endian read/write)
Python plan:
- Use Python `bytes`/`bytearray`; helper functions for base64/hex
- Endian utilities only when required by dump/restore (Phase 4).

### Compression
- gzip operations implicitly via FS_ utilities
Python plan:
- gzip / tarfile integration added Phase 4 (dump/restore).

### Security Gating
- V8SecurityFeature path & endpoint restrictions
Python plan:
- Not replicated initially; rely on controlled invocation context
- Future: optional allowlist for file operations.

### Usage in testing.js
Direct calls are mostly mediated through higher-level modules (process-utils, result-processing). Entry point needs:
- Process execution & monitoring
- Filesystem access for test discovery & result emission
- Logging & timeouts
- Random suffix generation
- Optional download (e.g., external artifacts) minimal
All others routed indirectly.

### Python Mapping Summary (Initial Phase 1)
Category -> Module:
- fs/archive -> armadillo.core.fs
- process -> armadillo.core.process
- timeouts -> armadillo.core.time
- logging -> armadillo.core.log
- crypto/random -> armadillo.core.crypto
- data codec -> armadillo.core.codec (JSON only)
- errors -> armadillo.core.errors
Future: velocypack adapter (armadillo.ext.vpack), RSA signing, sandboxed FS.

### Deferred / Out-of-Scope (For MVP)
- Direct VelocyPack conversion
- Advanced priority / cgroup tuning
- Network packet capture (Phase 6)
- Full security gating layer
- RSA private signing
- Pipe write multiplex optimization

## Special Features
- **Auto Mode**: Automatically discovers and runs tests matching filter criteria
- **Find Mode**: Searches and lists available tests without execution
- **Bucket Support**: Supports test partitioning for parallel execution
- **Signal Handling**: Proper interrupt handling for clean shutdown
- **Module Discovery**: Dynamic module loading and option registration
