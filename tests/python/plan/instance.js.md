# instance.js - Individual ArangoDB Instance Wrapper

## Purpose
Comprehensive wrapper for individual ArangoDB server instances providing process control, health monitoring, crash analysis, and advanced debugging capabilities. Serves as the foundational building block for the testing framework's instance management.

## Core Functionality

### Instance Creation and Configuration
- **Role-Based Configuration**: Supports different instance roles (single, agent, coordinator, dbserver)
- **Protocol Support**: Handles TCP, SSL, Unix socket, VST, and HTTP/2 protocols
- **Argument Processing**: Sophisticated command-line argument building and validation
- **Directory Management**: Automatic creation and management of data, app, and temp directories
- **Memory Management**: Per-instance memory limit enforcement and configuration

### Process Lifecycle Management
- **Process Spawning**: `startArango()` and `launchInstance()` for instance creation
- **Graceful Shutdown**: `shutdownArangod()` with maintenance mode coordination
- **Force Termination**: `killWithCoreDump()` for emergency shutdown with core dump collection
- **Restart Management**: `restartOneInstance()` for instance restart with configuration updates
- **Suspend/Resume**: Process suspension and resumption for testing scenarios

### Health Monitoring and Diagnostics
- **Continuous Health Checks**: `checkArangoAlive()` monitors process status and responsiveness
- **Connection Management**: Automatic connection establishment and reconnection handling
- **Readiness Validation**: `pingUntilReady()` ensures instance is ready to accept requests
- **Status Monitoring**: Real-time process status tracking and state management
- **Network Validation**: Connection testing and endpoint validation

### Crash Detection and Analysis
- **Automatic Crash Detection**: Detects abnormal terminations and signal-based crashes
- **Core Dump Generation**: Automatic core dump creation for crashed instances
- **Crash Analysis Integration**: Integration with crash analysis utilities
- **Signal Handling**: Proper handling of termination signals (SIGTERM, SIGABRT, SIGKILL)
- **Post-Mortem Analysis**: Detailed crash analysis with stack trace collection

### Advanced Debugging Features
- **Failure Point Injection**: `debugSetFailAt()` for controlled failure testing
- **Debug Termination**: `debugTerminate()` for controlled instance termination
- **Race Condition Testing**: Debug race control for concurrent testing scenarios
- **Failure Point Management**: Comprehensive failure point injection and cleanup
- **Development Support**: Integration with debugging tools and external analyzers

### Authentication and Security
- **JWT Integration**: Full JWT token management and authentication
- **Connection Security**: Secure connection establishment across protocols
- **Authentication Headers**: Automatic authentication header generation and management
- **Token Rotation**: Support for JWT token rotation and refresh
- **Multi-Level Authentication**: Support for different authentication mechanisms

### Log Management and Analysis
- **Log File Processing**: Comprehensive log file reading and analysis
- **Important Message Detection**: Automatic detection of critical log messages
- **Assert Line Detection**: Detection and collection of assertion failures
- **Log Filtering**: Intelligent filtering of unimportant log messages
- **Error Aggregation**: Collection and aggregation of fatal errors

### Resource Monitoring
- **Process Statistics**: Real-time process resource usage monitoring
- **Memory Profiling**: Memory snapshot collection and leak detection
- **Network Statistics**: Socket statistics collection and analysis
- **I/O Monitoring**: File and network I/O tracking on Linux systems
- **Delta Statistics**: Resource usage delta calculation between snapshots

### Sanitizer Integration
- **AddressSanitizer Support**: Comprehensive ASAN report collection and processing
- **ThreadSanitizer Support**: TSAN report integration and analysis
- **Report Processing**: Automatic sanitizer report collection after process termination
- **Environment Configuration**: Sanitizer environment variable management
- **Report Filtering**: Intelligent filtering and processing of sanitizer output

### Development and Testing Support
- **Valgrind Integration**: Memory debugging tool integration with report collection
- **RR Integration**: Record and replay debugging tool support
- **External Tool Support**: Integration with external debugging and monitoring tools
- **Configuration Flexibility**: Extensive configuration options for different testing scenarios
- **Maintenance Mode**: Cluster maintenance mode coordination during operations

## Key Features

### Process Control
- **Multi-Protocol Support**: TCP, SSL, Unix sockets, VST, HTTP/2 protocol handling
- **Graceful Lifecycle**: Proper startup, shutdown, and restart procedures
- **Resource Management**: Memory limits, directory management, and cleanup
- **Error Recovery**: Automatic recovery and error handling procedures

### Monitoring and Diagnostics
- **Real-Time Monitoring**: Continuous process and service health monitoring
- **Performance Tracking**: Resource usage monitoring and performance analysis
- **Crash Analysis**: Comprehensive crash detection and post-mortem analysis
- **Network Monitoring**: Connection tracking and network statistics collection

### Testing Integration
- **Failure Injection**: Controlled failure point injection for testing
- **Debug Support**: Extensive debugging capabilities and tool integration
- **State Management**: Comprehensive instance state tracking and management
- **Configuration Override**: Dynamic configuration changes during testing

### Security and Authentication
- **JWT Management**: Complete JWT token lifecycle management
- **Secure Connections**: SSL/TLS and encrypted connection support
- **Authentication Flexibility**: Multiple authentication mechanism support
- **Connection Pooling**: Efficient connection management and reuse

## Configuration Options

### Instance Configuration
- `instanceRole`: Role of the instance (single, agent, coordinator, dbserver)
- `protocol`: Communication protocol (tcp, ssl, unix)
- `dataDir`/`appDir`/`tmpDir`: Directory paths for instance data
- `useableMemory`: Memory limit for the instance

### Monitoring Configuration
- `enableAliveMonitor`: Enable continuous process monitoring
- `maxLogFileSize`: Maximum log file size before analysis
- `skipLogAnalysis`: Skip log file analysis during shutdown
- `getSockStat`: Collect socket statistics on Linux

### Development Configuration
- `valgrind`: Enable Valgrind memory debugging
- `rr`: Enable record-replay debugging
- `bindBroadcast`: Bind to 0.0.0.0 instead of localhost
- `extremeVerbosity`: Enable detailed logging for debugging

## Integration Points
- **Instance Manager**: Coordinated lifecycle management across multiple instances
- **Agency Manager**: Cluster consensus and coordination for agent instances
- **Process Utils**: Process execution and monitoring utilities
- **Crash Utils**: Crash analysis and debugging integration
- **Port Manager**: Port allocation and conflict detection
- **Sanitizer Handler**: Sanitizer report processing and management

## Error Handling and Recovery
- **Graceful Degradation**: Handles failures with appropriate cleanup and recovery
- **Timeout Management**: Sophisticated timeout handling with deadline enforcement
- **Resource Cleanup**: Comprehensive cleanup on failure or shutdown
- **State Consistency**: Maintains consistent instance state across operations
- **Error Propagation**: Proper error reporting with detailed diagnostics

## Special Features
- **Connection Handle Management**: Efficient connection pooling and reuse
- **Multi-Format Authentication**: Support for JWT, basic auth, and custom authentication
- **Advanced Process Control**: Suspend, resume, and controlled termination capabilities
- **Comprehensive Logging**: Detailed logging with intelligent filtering and analysis
- **Platform Integration**: Linux-specific features for enhanced monitoring and diagnostics

## Arangosh V8 Extension Dependencies (Concise)

Legacy `instance.js` depended on arangosh-injected V8 helpers. These inform Python replacements.

### Categories & Legacy Primitives
- Process/System: SYS_EXECUTE_EXTERNAL, SYS_STATUS_EXTERNAL, SYS_KILL_EXTERNAL, SYS_PROCESS_STATISTICS, SYS_GET_PID
- Timing/Deadlines: SYS_SLEEP, SYS_WAIT, correctTimeoutToExecutionDeadline*
- Filesystem: FS_EXISTS, FS_READ, FS_WRITE, FS_REMOVE(_DIRECTORY/_RECURSIVE), FS_LIST
- Ports/Networking: SYS_TEST_PORT, endpoint normalization (getEndpoint)
- Logging: SYS_LOG (level/topic), dynamic verbosity control
- Random/IDs: SYS_GEN_RANDOM_ALPHA_NUMBERS (temp dirs, secrets)
- Crypto/Auth: SHA256/HMAC for JWT signing, PBKDF2 (rare)
- Crash/Debug: External gdb invocation via SYS_EXECUTE_EXTERNAL, core presence checks
- Pipes: SYS_READPIPE (sanitizer/debug tool output)
- Sanitizers: Environment variable assembly + post-run log scan
- Buffer/Binary: Base64/hex helpers (minor)

### Python Mapping
Category -> Module
- Process/System -> armadillo.core.process (subprocess + optional psutil)
- Deadlines -> armadillo.core.time.TimeoutManager
- Filesystem -> armadillo.core.fs (pathlib/shutil)
- Ports -> armadillo.core.net (port probing)
- Logging -> armadillo.core.log (structured, component=instance)
- Random/IDs -> armadillo.core.crypto.random_id()
- Auth/JWT -> armadillo.core.auth (HMAC JWT)
- Crash/Debug -> armadillo.core.crash (Phase 1: abnormal exit + stderr capture)
- Sanitizers -> armadillo.ext.sanitizers (stub until Phase 5)
- Buffer/Binary -> builtin base64 / binascii

### Deferred (Post-MVP)
- Core dump symbolization (Phase 6)
- Full sanitizer parsing (Phase 5)
- Priority / cgroup tuning
- Advanced resource delta profiling
- Pipe multiplex optimization

### Design Alignment
Instance object composes: ProcessHandle, TimeoutManager, AuthProvider, LogScanner, HealthChecker.
All waits use clamp_timeout(); errors specialized (InstanceStartError, InstanceCrashError).
Structured lifecycle events feed result processing & crash analytics.

## Arangosh V8 Extension Dependencies

The per-instance wrapper relied on numerous arangosh V8-exposed primitives for process control, filesystem operations, authentication token handling, timing, crash diagnostics, and sanitizer integration.

### Categories & Legacy Functions

1. Process & System
- SYS_EXECUTE_EXTERNAL / SYS_STATUS_EXTERNAL / SYS_KILL_EXTERNAL for spawning and monitoring `arangod`
- SYS_PROCESS_STATISTICS for collecting CPU, RSS, I/O stats
- SYS_GET_PID for identity checks
- SYS_SLEEP / SYS_WAIT (deadline aware) for retry loops
- Potential priority adjustments (SYS_SET_PRIORITY_EXTERNAL) (often unused but available)

2. Filesystem & Paths
- FS_EXISTS / FS_READ / FS_WRITE / FS_REMOVE(_DIRECTORY/_RECURSIVE)
- FS_LIST for log and directory inspection
- FS_ZIP_FILE / FS_UNZIP_FILE occasionally for archived artifacts (rare in instance wrapper itself)

3. Logging
- SYS_LOG(level/topic) for lifecycle events (start, ready, shutdown, crash)
- Dynamic topic/verbosity toggling (extremeVerbosity)

4. Networking / Ports
- SYS_TEST_PORT to probe free ports for endpoints
- Endpoint normalization helpers (getEndpoint() logic in V8 layer)

5. Random / IDs
- SYS_GEN_RANDOM_ALPHA_NUMBERS for temporary directory suffixes and JWT secrets (test mode)
- Random numeric generation for ephemeral IDs in debugging contexts

6. Crypto / Auth
- JWT token generation (HMAC-based) using hashing primitives (SYS_SHA256/HMAC)
- Optional PBKDF2 derivations if password-based auth flows appear

7. Deadline / Timeout
- correctTimeoutToExecutionDeadline* for startup readiness loops and shutdown grace periods

8. Crash & Debug
- Integration points for invoking external gdb/lldb via SYS_EXECUTE_EXTERNAL
- Core file presence checks via FS_* utilities
- Pipe handling (SYS_READPIPE) for reading debugger or sanitizer outputs

9. Sanitizers
- Environment variable assembly (ASAN_OPTIONS/TSAN_OPTIONS) written into process environment before spawn
- Post-termination log scanning (FS_READ + filtering)

10. Buffer / Binary
- Base64/hex utilities when transporting crash signatures or sanitized stack fragments
- Rare endian operations (mostly not needed here)

### Python Translation Plan (Phase 1 Focus)

Category -> Python Module:
- Process/system -> armadillo.core.process (subprocess + psutil optional)
- Filesystem -> armadillo.core.fs (pathlib + shutil)
- Logging -> armadillo.core.log (structured + component=instance)
- Ports -> armadillo.core.net (port probing)
- Random -> armadillo.core.crypto.random_id()
- Auth/JWT -> armadillo.core.auth (HMAC JWT; refresh support)
- Deadlines -> armadillo.core.time.TimeoutManager
- Crash/Debug -> armadillo.core.crash (stub Phase 1: detect abnormal exit + collect stderr)
- Sanitizers -> armadillo.ext.sanitizers (deferred until later phase; Phase 1 stub capturing env)
- Buffer/Binary -> native bytes utilities (base64, binascii)

### Deferred / Future Phases
- Full sanitizer report parsing (Phase 5)
- Core dump symbolization (Phase 6 with gdb integration)
- Advanced memory & network stat deltas (psutil extended + /proc parsing)
- Pipe multiplex optimization
- Priority / cgroup tuning

### Usage Hotspots
- Startup readiness: loop with HTTP ping + timeout clamping
- Graceful shutdown: send SIGTERM then escalate to SIGKILL with deadline
- Crash path: detect non-zero exit / signal, gather logs, produce CrashReport
- Log scanning: parse fatal/assert lines, extract failure points
- JWT rotation: rebuild auth header cache on demand

### Design Notes
- Instance object composes: ProcessHandle, HealthChecker, LogScanner, AuthProvider, TimeoutManager
- Clear state machine: INIT -> STARTING -> RUNNING -> STOPPING -> STOPPED / CRASHED
- All waits use monotonic deadlines via clamp_timeout()
- Rich error classes (InstanceStartError, InstanceCrashError)
- Structured lifecycle events emitted for result processing integration.
