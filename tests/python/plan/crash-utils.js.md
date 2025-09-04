# Crash Analysis and Core Dump Utilities (`crash-utils.js`)

## Overview
Advanced crash detection, analysis, and debugging utilities providing comprehensive post-mortem analysis capabilities. Integrates with GDB (GNU Debugger) for stack trace analysis, core dump generation, and intelligent crash pattern filtering to support robust debugging workflows in distributed testing environments.

## Core Functionality

### Core Dump Analysis
- **Automated core dump detection**: Locates core files using system-specific patterns and configurations
- **GDB integration**: Launches GNU Debugger with automated script execution for crash analysis
- **Stack trace extraction**: Captures complete stack traces including full backtraces and thread information
- **Core file pattern handling**: Supports various core file naming patterns (systemd-coredump, /var/tmp, custom patterns)
- **Multiple format support**: Handles different core dump formats and locations across Linux distributions

### Intelligent Stack Filtering
- **Pattern-based filtering**: Uses configurable filters to remove known/expected stack traces
- **Noise reduction**: Filters out common framework stacks to focus on actual crash causes
- **Filter configuration**: JSON-based filter definitions for customizable stack trace filtering
- **Duplicate elimination**: Removes repetitive or identical stack traces from analysis output
- **Relevance scoring**: Prioritizes meaningful crash information over framework overhead

### Interactive Debugging Support
- **GDB command automation**: Executes predefined GDB commands for consistent analysis
- **Batch processing**: Non-interactive debugging suitable for automated test environments
- **Custom debugging scripts**: Configurable GDB command sequences for specific analysis needs
- **Process attachment**: Can attach to running processes for live debugging scenarios
- **Symbol resolution**: Handles debug symbol loading and path resolution

### Live Process Analysis
- **Runtime crash detection**: Monitors running processes for crash conditions
- **Process state capture**: Records process information at time of crash
- **Memory analysis**: Captures memory usage and virtual/resident size information
- **Signal handling**: Properly handles different termination signals (SIGTERM, SIGABRT)
- **Process statistics**: Collects performance and resource usage data during crashes

### Output Processing and Reporting
- **Formatted output generation**: Creates structured crash reports with relevant information
- **Multi-format export**: Supports various output formats for different analysis tools
- **Verbose logging**: Configurable verbosity levels for detailed crash analysis
- **Report aggregation**: Combines multiple crash reports for batch analysis
- **Timeline tracking**: Records crash timestamps and sequence information

### System Integration
- **Core pattern detection**: Automatically detects system core dump configuration
- **Distribution compatibility**: Handles different Linux distributions (Ubuntu, systemd-based systems)
- **Apport integration**: Detects and works around Ubuntu's Apport crash reporting system
- **Permission handling**: Manages file permissions and access rights for core dumps
- **Temporary file management**: Handles temporary files for intermediate processing

### Advanced Features

#### Smart Core Generation
- **Conditional core dumps**: Generates core dumps based on process size and system resources
- **Resource-aware processing**: Avoids core generation for oversized processes
- **Sanitizer integration**: Adapts behavior when running under AddressSanitizer/ThreadSanitizer
- **Background processing**: Runs analysis in background to avoid blocking test execution

#### Process Management
- **Graceful termination**: Attempts clean shutdown before forcing termination
- **Priority management**: Adjusts process priorities to prevent resource starvation
- **Timeout handling**: Implements timeouts for debugging operations to prevent hangs
- **Status monitoring**: Tracks debugger process status and completion

#### Error Recovery
- **Fallback mechanisms**: Provides alternative analysis methods when primary tools fail
- **Partial analysis**: Continues analysis even when some components fail
- **Error reporting**: Detailed error messages for troubleshooting analysis failures
- **Retry logic**: Automatic retry for transient failures in debugging operations

## Configuration Options

### Core Dump Settings
- **Core directory configuration**: Customizable core file location
- **Core generation control**: Enable/disable automatic core dump generation
- **Size limitations**: Configure memory limits for core dump generation
- **Pattern customization**: Support for custom core file naming patterns

### Analysis Control
- **Verbosity levels**: Configurable detail levels for crash analysis output
- **Filter customization**: Configurable stack trace filtering rules
- **Timeout settings**: Adjustable timeouts for various debugging operations
- **Tool selection**: Choose between different debugging tools and approaches

### Integration Settings
- **Test framework integration**: Coordinates with test execution and reporting
- **Instance management**: Integrates with ArangoDB instance lifecycle management
- **Logging coordination**: Synchronizes with broader logging and monitoring systems
- **Cleanup policies**: Configurable cleanup of temporary files and resources

## Test Framework Integration
- Provides crash analysis for failed test instances
- Integrates with instance manager for process monitoring
- Supports test isolation and cleanup after crashes
- Enables automated crash reporting in continuous integration
- Coordinates with result processing for crash statistics

## Error Handling
- Robust error handling for system-level operations
- Graceful degradation when debugging tools are unavailable
- Comprehensive logging of analysis failures and their causes
- Fallback strategies for different system configurations
- Protection against infinite loops and resource exhaustion

## Platform Support
- Linux-focused implementation with distribution-specific adaptations
- GDB dependency management and version compatibility
- System core dump configuration detection and adaptation
- File system permission and access handling
- Process control and signal management across different kernels

## Arangosh V8 Extension Dependencies (Concise)

Crash analysis utilities leveraged numerous arangosh-injected primitives to discover cores, invoke debuggers, filter stacks, and manage timeouts.

### Categories & Legacy Primitives
- Process/System: SYS_EXECUTE_EXTERNAL, SYS_STATUS_EXTERNAL, SYS_KILL_EXTERNAL (invoke gdb, symbol tools)
- Filesystem: FS_LIST / FS_READ / FS_WRITE / FS_REMOVE for core file discovery, temp scripts, filtered outputs
- Timing/Deadlines: SYS_SLEEP, SYS_WAIT, correctTimeoutToExecutionDeadline* (bounded debugger runs)
- Logging: SYS_LOG (crash summary, stack filtering decisions)
- Random: SYS_GEN_RANDOM_ALPHA_NUMBERS (temp file suffixes)
- Crypto/Hashing: SHA256 / MD5 occasionally to fingerprint stacks (dedupe)
- Pipes: SYS_READPIPE (capture gdb stdout/stderr streaming)
- Environment: Setting ASAN_OPTIONS / TSAN_OPTIONS for sanitizer-aware behavior
- Buffer/Binary: Base64/hex (rare) for embedding snippets into JSON reports

### Python Mapping
Category -> Module
- External Debugger Invocation -> armadillo.core.crash (gdb runner)
- Filesystem Ops -> armadillo.core.fs
- Deadlines -> armadillo.core.time.TimeoutManager
- Logging -> armadillo.core.log (component=crash)
- Random Temp Names -> armadillo.core.crypto.random_id()
- Hash Fingerprints -> hashlib (sha256) inside crash filter
- Pipes & Streaming -> subprocess with non-blocking read wrapper
- Sanitizer Env Handling -> armadillo.ext.sanitizers (later phase)
- Stack Filtering Rules -> armadillo.core.crash.filters (configurable patterns)

### Deferred (Post-MVP)
- Advanced stack de-dup & clustering
- Symbolication caching layer
- Parallel core analysis worker pool
- Sanitizer log correlation (ASAN/TSAN interleave parsing)
- Fingerprint-based regression suppression database

### Design Alignment
CrashAnalyzer composes: DebuggerInvoker, CoreLocator, StackFilter, ReportBuilder.
All analysis steps time-boxed via clamp_timeout(); produces structured CrashReport objects integrated into result processing.
