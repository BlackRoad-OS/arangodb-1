# Process Utilities and System Integration (`process-utils.js`)

## Overview
Core system utilities providing process management, binary path resolution, authentication handling, and system integration capabilities. Serves as the foundation layer for all external process execution, file system operations, and system resource management across the testing framework.

## Core Functionality

### Binary Path Management and Resolution
- **Automatic binary discovery**: Intelligent detection of ArangoDB binaries across different build configurations
- **Path resolution**: Resolves paths for all ArangoDB tools (arangod, arangosh, arangodump, etc.)
- **Build directory detection**: Automatically locates build directories and validates binary existence
- **Enterprise edition detection**: Distinguishes between Community and Enterprise installations
- **Cross-platform support**: Handles platform-specific executable extensions and path conventions

### Process Execution and Management
- **Command execution wrapper**: Robust wrapper around system process execution with comprehensive error handling
- **Timeout management**: Configurable timeouts for process execution with proper cleanup
- **Exit code handling**: Comprehensive exit code analysis and status reporting
- **Signal handling**: Proper handling of process termination signals (SIGTERM, SIGABRT, SIGKILL)
- **Background process monitoring**: Tracks and manages long-running background processes

### Authentication and Security
- **JWT token generation**: Creates and manages JWT tokens for API authentication
- **Authorization header creation**: Generates appropriate authorization headers for HTTP requests
- **Secret management**: Handles JWT secrets from files, folders, or direct configuration
- **Basic authentication**: Fallback to basic authentication when JWT is unavailable
- **Multi-source authentication**: Supports various authentication configurations

### System Resource Monitoring
- **Process lifecycle tracking**: Monitors process creation, execution, and termination
- **Resource usage statistics**: Collects CPU, memory, and other system resource metrics
- **Crash detection integration**: Integrates with crash analysis utilities for failure detection
- **Sanitizer integration**: Coordinates with AddressSanitizer/ThreadSanitizer for memory error detection
- **Core dump coordination**: Works with core dump analysis systems

### External Tool Integration
- **Valgrind support**: Comprehensive Valgrind integration for memory debugging
- **GDB integration**: Coordinates with GNU Debugger for crash analysis
- **Sanitizer tool support**: Integration with various sanitizer tools (ASAN, TSAN, etc.)
- **External command execution**: Generic framework for executing external tools and utilities
- **Tool configuration management**: Handles configuration for various external debugging tools

### Path and Directory Management
- **Directory structure setup**: Establishes and manages directory hierarchies for testing
- **Configuration directory handling**: Manages configuration file locations across different environments
- **Log directory management**: Sets up and manages log file locations
- **Temporary directory handling**: Creates and manages temporary directories for test execution
- **Cleanup coordination**: Ensures proper cleanup of temporary resources

## Advanced Features

### Process Monitoring and Control
- **Orphaned process detection**: Identifies and handles processes that weren't properly cleaned up
- **Process tree management**: Manages complex process hierarchies with proper termination order
- **Resource leak detection**: Identifies and reports resource leaks from test execution
- **Graceful shutdown coordination**: Implements proper shutdown sequences for complex process groups

### Error Handling and Recovery
- **Comprehensive error reporting**: Detailed error messages with context information
- **Failure analysis integration**: Coordinates with crash analysis systems for detailed failure reports
- **Recovery mechanisms**: Implements recovery strategies for various failure scenarios
- **State preservation**: Maintains process state information for post-mortem analysis

### Cross-Platform Compatibility
- **Platform detection**: Identifies operating system and adjusts behavior accordingly
- **Path separator handling**: Manages path separators across different operating systems
- **Executable extension handling**: Handles platform-specific executable extensions (.exe on Windows)
- **System command adaptation**: Adapts system commands for different platforms

### Development and Debugging Support
- **Verbose logging**: Configurable logging levels for debugging test framework issues
- **Command tracing**: Logs all executed commands for debugging and audit purposes
- **Performance monitoring**: Tracks execution times and resource usage
- **Development mode features**: Additional debugging capabilities for framework development

## Integration Points

### Test Framework Integration
- **Binary validation**: Ensures all required binaries are available before test execution
- **Configuration setup**: Establishes configuration directories and files
- **Process coordination**: Manages process lifecycle in coordination with test execution
- **Result coordination**: Integrates with result processing for comprehensive reporting

### Instance Management Integration
- **Process creation**: Creates and configures ArangoDB server instances
- **Lifecycle management**: Coordinates with instance manager for server lifecycle
- **Health monitoring**: Provides health check capabilities for running instances
- **Cleanup coordination**: Ensures proper cleanup when instances terminate

### Security and Authentication
- **Token management**: Provides authentication tokens for API communication
- **Secure communication**: Ensures secure communication with ArangoDB instances
- **Permission handling**: Manages file and directory permissions for test execution
- **Secret handling**: Securely manages authentication secrets and tokens

## Configuration Management

### Binary Configuration
- **Build directory specification**: Configurable build directory location
- **Binary path customization**: Override default binary locations
- **Tool configuration**: Configure paths for external tools and utilities
- **Version compatibility**: Handles different versions of ArangoDB binaries

### Process Configuration
- **Timeout settings**: Configurable timeouts for different types of operations
- **Resource limits**: Configure resource limits for spawned processes
- **Execution environment**: Control environment variables and execution context
- **Debugging options**: Configure debugging and profiling options

### System Configuration
- **Directory structure**: Configure directory layouts for different environments
- **File permissions**: Configure file and directory permission settings
- **Cleanup policies**: Configure cleanup behavior for temporary resources
- **Logging configuration**: Configure logging levels and destinations

## Error Handling and Robustness
- **Comprehensive error detection**: Detects and reports various types of process failures
- **Graceful degradation**: Continues operation when non-critical components fail
- **Resource cleanup**: Ensures proper cleanup even when errors occur
- **Detailed error reporting**: Provides comprehensive error information for debugging
- **Recovery mechanisms**: Implements recovery strategies for common failure scenarios

## Performance and Optimization
- **Efficient process management**: Optimized process creation and management
- **Resource usage monitoring**: Monitors and reports resource usage patterns
- **Performance bottleneck identification**: Identifies performance issues in process execution
- **Optimization recommendations**: Provides guidance for optimizing test execution

## Test Framework Foundation
- Provides core utilities for all other framework components
- Establishes foundation for process management and system integration
- Enables robust and reliable test execution across different environments
- Supports development and debugging of the test framework itself
- Ensures compatibility across different platforms and configurations

## Arangosh V8 Extension Dependencies (Concise)

`process-utils.js` was the heaviest direct consumer of arangosh V8 injected helpers, acting as a façade over system process, filesystem, auth, crypto, and timeout primitives.

### Categories & Legacy Primitives
- Process/System: SYS_EXECUTE_EXTERNAL, SYS_STATUS_EXTERNAL, SYS_KILL_EXTERNAL, SYS_SET_PRIORITY_EXTERNAL, SYS_PROCESS_STATISTICS, SYS_GET_PID
- Timing/Deadlines: SYS_SLEEP, SYS_WAIT, correctTimeoutToExecutionDeadline*
- Filesystem: FS_EXISTS, FS_READ, FS_WRITE, FS_REMOVE(_DIRECTORY/_RECURSIVE), FS_LIST, FS_LIST_TREE, FS_ZIP_FILE, FS_UNZIP_FILE, FS_ADLER32
- Logging: SYS_LOG, SYS_LOG_LEVEL (dynamic verbosity / topic tuning)
- Crypto/Hashing: SYS_MD5, SYS_SHA{1,224,256,384,512}, SYS_HMAC, SYS_PBKDF2, SYS_PBKDF2HS1, SYS_RSAPRIVSIGN (rare), checksums for artifact verification
- Random/Nonce: SYS_GEN_RANDOM_{NUMBERS,ALPHA_NUMBERS,SALT}, SYS_CREATE_NONCE / SYS_CHECK_AND_MARK_NONCE
- Auth/JWT: HMAC signing primitives for JWT generation
- Networking/Ports: SYS_TEST_PORT (free port probing), getEndpoint normalization logic
- Pipes: SYS_READPIPE, SYS_WRITEPIPE, SYS_CLOSEPIPE (stream tool output)
- Environment/Sanitizers: Setting ASAN/TSAN env vars before spawn
- Buffer/Binary: Base64/hex encode/decode for transporting tokens or compressed fragments
- Compression/Archive: ZIP/GZIP via FS_* helpers (zip/unzip abstractions)

### Python Mapping
Category -> Module
- Process & Stats -> armadillo.core.process (ProcessHandle, exec(), capture; optional psutil integration)
- Filesystem & Archive -> armadillo.core.fs (pathlib/shutil/zipfile + zlib.adler32)
- Logging -> armadillo.core.log
- Deadlines -> armadillo.core.time.TimeoutManager
- Crypto/Hashing -> armadillo.core.crypto (hashlib, hmac, pbkdf2_hmac)
- Random/Nonce -> armadillo.core.crypto.random_id() + NonceRegistry
- Auth/JWT -> armadillo.core.auth (HMAC JWT)
- Ports -> armadillo.core.net (port probe)
- Pipes/Streaming -> subprocess + nonblocking reader utilities
- Sanitizer Env -> armadillo.ext.sanitizers (stub until later phase)
- Compression -> builtin gzip/tarfile (zip in Phase 4 if needed)
- Buffer/Binary -> base64 / binascii helpers

### Deferred (Post-MVP)
- RSA private signing (if required)
- Advanced process tree cgroup/resource enforcement
- Sandboxed FS layer (deny/allow list)
- Parallel archive compression pipeline
- Nonce replay attack audit logs

### Design Alignment
`process-utils` dissolves into focused services:
- BinaryLocator
- AuthProvider
- ProcessExecutor / ProcessSupervisor
- FilesystemService
- CryptoService
- TimeoutManager (shared)
Exposed through a thin orchestration layer; all blocking waits use clamp_timeout() to respect global execution deadline.
