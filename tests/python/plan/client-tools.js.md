# Client Tools Integration and Management (`client-tools.js`)

## Overview
Comprehensive integration layer for all ArangoDB client tools providing configuration management, execution coordination, background process handling, and advanced testing capabilities. Manages the complete lifecycle of client tools including arangosh, arangodump, arangorestore, arangoimport, arangoexport, arangobench, and arangobackup with sophisticated configuration builders and execution frameworks.

## Core Functionality

### Configuration Builder System
- **Flexible configuration management**: Type-specific configuration builders for each client tool
- **Dynamic configuration generation**: Builds tool-specific arguments and configuration files
- **Parameter validation**: Ensures valid parameter combinations for different tools
- **Authentication handling**: Manages various authentication methods (basic auth, JWT, keyfiles)
- **Environment-specific settings**: Adapts configurations for different testing environments

### Client Tool Execution Management
- **Process lifecycle control**: Manages complete lifecycle from launch to termination
- **Background execution support**: Runs client tools in background with monitoring capabilities
- **Timeout management**: Configurable timeouts with proper cleanup on timeout
- **Exit code analysis**: Comprehensive exit code handling and error reporting
- **Resource monitoring**: Tracks resource usage during client tool execution

### ArangoSH Integration and Management
- **Interactive shell support**: Manages arangosh instances for interactive testing
- **Script execution**: Executes JavaScript files and code snippets in arangosh
- **Background shell management**: Runs multiple arangosh instances concurrently
- **Shell coordination**: Synchronizes multiple shell instances for complex testing scenarios
- **Environment setup**: Configures JavaScript modules and startup directories

### Data Import/Export Operations
- **ArangoImport integration**: Complete integration with arangoimport for data loading
- **Import configuration**: Flexible configuration for various data formats (JSON, CSV, TSV)
- **Data transformation**: Supports data conversion and manipulation during import
- **Collection management**: Handles collection creation and configuration during import
- **Error handling**: Comprehensive error handling for import operations

### Dump and Restore Operations
- **ArangoDump integration**: Complete backup creation with flexible configuration
- **ArangoRestore integration**: Backup restoration with database recreation capabilities
- **Multi-database support**: Handles single and multi-database backup/restore operations
- **Compression support**: Configurable compression for dump operations
- **Encryption support**: Handles encrypted backups and restoration
- **Incremental operations**: Supports incremental and differential backup strategies

### Background Process Management
- **Concurrent execution**: Manages multiple client tools running simultaneously
- **Process synchronization**: Coordinates execution across multiple background processes
- **Progress monitoring**: Tracks progress of long-running operations
- **Resource coordination**: Manages resource allocation across concurrent processes
- **Cleanup coordination**: Ensures proper cleanup of background processes

## Advanced Features

### Background Shell Framework
- **Snippet execution**: Executes JavaScript code snippets in background shells
- **Loop execution**: Supports continuous execution with stop conditions
- **Client coordination**: Manages multiple clients with shared stop mechanisms
- **Progress tracking**: Monitors execution progress and iteration counts
- **Error isolation**: Handles errors in individual clients without affecting others

### RTA (Resilience Testing Application) Integration
- **Makedata operations**: Generates test data for resilience testing
- **Data validation**: Validates generated data integrity
- **Cleanup operations**: Manages cleanup of test data
- **Shard synchronization**: Waits for shard synchronization in cluster environments
- **Progress monitoring**: Tracks data generation and validation progress

### Benchmark Integration
- **ArangoBench coordination**: Manages benchmark execution with configurable parameters
- **Performance monitoring**: Tracks performance metrics during benchmark execution
- **Result collection**: Gathers and processes benchmark results
- **Configuration management**: Handles complex benchmark configurations
- **Resource monitoring**: Monitors system resources during benchmarking

### Backup and Recovery Operations
- **ArangoBackup integration**: Complete backup management with enterprise features
- **Backup validation**: Validates backup integrity and completeness
- **Recovery testing**: Tests backup recovery procedures
- **Schedule management**: Handles backup scheduling and rotation
- **Storage coordination**: Manages backup storage locations and cleanup

## Configuration Management

### Tool-Specific Configuration
- **Per-tool configuration**: Specialized configuration for each client tool
- **Parameter validation**: Ensures valid parameter combinations for each tool
- **Default handling**: Provides sensible defaults with override capabilities
- **Environment adaptation**: Adapts configuration for different environments

### Authentication Configuration
- **JWT token management**: Generates and manages JWT tokens for authentication
- **Keyfile handling**: Manages JWT keyfiles and secret handling
- **Basic authentication**: Fallback to username/password authentication
- **Security coordination**: Ensures secure communication with ArangoDB instances

### Database and Collection Configuration
- **Database selection**: Handles single and multi-database operations
- **Collection filtering**: Supports collection inclusion/exclusion patterns
- **System collection handling**: Configurable inclusion of system collections
- **Permission management**: Handles database and collection permissions

## Integration Features

### Test Framework Coordination
- **Test isolation**: Ensures test isolation through proper configuration
- **Resource management**: Coordinates resource usage across tests
- **Cleanup coordination**: Ensures proper cleanup after test execution
- **Error propagation**: Propagates errors appropriately to test framework

### Instance Manager Integration
- **Endpoint coordination**: Automatically discovers and uses appropriate endpoints
- **Authentication coordination**: Uses instance-specific authentication configuration
- **Health monitoring**: Coordinates with instance health monitoring
- **Lifecycle coordination**: Aligns client tool lifecycle with instance lifecycle

### Sanitizer and Coverage Integration
- **Sanitizer support**: Integrates with sanitizer tools for memory error detection
- **Coverage coordination**: Supports code coverage collection during tool execution
- **Debugging support**: Provides debugging capabilities for client tool issues
- **Profiling integration**: Supports performance profiling of client tools

## Error Handling and Robustness
- **Comprehensive error detection**: Detects and reports various types of client tool failures
- **Graceful degradation**: Continues operation when non-critical tools fail
- **Resource cleanup**: Ensures proper cleanup even when errors occur
- **Detailed error reporting**: Provides comprehensive error information for debugging
- **Retry mechanisms**: Implements retry logic for transient failures

## Performance Optimization
- **Concurrent execution**: Optimizes performance through concurrent tool execution
- **Resource management**: Efficient resource allocation and usage
- **Caching mechanisms**: Caches configurations and repeated operations
- **Performance monitoring**: Monitors and reports performance metrics
- **Bottleneck identification**: Identifies performance bottlenecks in tool execution

## Configuration Options

### Execution Control
- **Timeout configuration**: Configurable timeouts for different operations
- **Concurrency control**: Configure concurrent execution limits
- **Resource limits**: Configure resource limits for client tools
- **Retry policies**: Configure retry behavior for different failure types

### Tool-Specific Options
- **Import/export settings**: Configure data format handling and transformation
- **Backup/restore options**: Configure backup compression, encryption, and validation
- **Benchmark parameters**: Configure benchmark execution parameters
- **Shell configuration**: Configure arangosh behavior and environment

### Integration Settings
- **Authentication options**: Configure authentication methods and credentials
- **Endpoint configuration**: Configure connection endpoints and timeouts
- **Logging configuration**: Configure logging levels and destinations
- **Debug options**: Configure debugging and profiling options

## Test Framework Integration
- Provides comprehensive client tool support for all test types
- Integrates with instance management for endpoint and authentication coordination
- Supports complex multi-tool testing scenarios
- Enables automated data generation and validation
- Coordinates with result processing for comprehensive reporting

## Arangosh V8 Extension Dependencies (Concise)

Client tool orchestration leveraged a broad subset of arangosh V8 helpers for spawning tools, building configs, handling auth, managing temp files, and streaming outputs.

### Categories & Legacy Primitives
- Process/System: SYS_EXECUTE_EXTERNAL, SYS_STATUS_EXTERNAL, SYS_KILL_EXTERNAL (run arangosh, arangodump, arangorestore, arangoimport, arangoexport, arangobench, arangobackup)
- Timing/Deadlines: SYS_SLEEP, correctTimeoutToExecutionDeadline* (polling long dumps/imports)
- Filesystem: FS_EXISTS, FS_READ, FS_WRITE, FS_LIST, FS_REMOVE(_DIRECTORY/_RECURSIVE), FS_ZIP_FILE / FS_UNZIP_FILE (compressed dumps), FS_ADLER32 (integrity)
- Logging: SYS_LOG (per-tool start/finish, progress, anomalies)
- Crypto/Hashing: SHA256 / MD5 for checksum validation (dump/restore), HMAC for JWT
- Random/IDs: SYS_GEN_RANDOM_ALPHA_NUMBERS (temp dir / file suffixes, run IDs)
- Auth/JWT: HMAC signing primitives; keyfile reading via FS_READ
- Buffer/Binary: Base64/hex (rare) for embedding small binary artifacts or credentials
- Pipes: SYS_READPIPE (stream background arangosh / bench output), SYS_WRITEPIPE (inject commands)
- Compression: ZIP helpers for dump archives (plus possible gzip layering)
- Environment/Sanitizers: Propagate sanitizer env vars to tool processes
- Network/Ports: getEndpoint normalization for tool targets

### Python Mapping
Category -> Module
- Process Exec -> armadillo.core.process (ToolRunner abstraction)
- Deadlines -> armadillo.core.time.TimeoutManager
- Filesystem / Compression -> armadillo.core.fs (+ zipfile, gzip)
- Logging -> armadillo.core.log (component=client_tools)
- Crypto/Hash / JWT -> armadillo.core.auth + armadillo.core.crypto
- Random IDs -> armadillo.core.crypto.random_id()
- Pipes / Streaming -> subprocess with async readers
- Dump/Restore Config -> armadillo.tools.dump_restore (future Phase 4)
- Import/Export -> armadillo.tools.import_export
- Benchmarks -> armadillo.tools.benchmark
- Backup -> armadillo.tools.backup
- Config Builders -> armadillo.tools.config (shared argument assembly)
- Checksums -> zlib.adler32 / hashlib
- Archiving -> zipfile (Phase 4), tarfile/gzip as needed

### Deferred (Post-MVP)
- Parallel segmented dump/restore optimization
- Streaming incremental backup diff engine
- Live progress socket listener for long imports
- Advanced checksum manifest (multi-hash)
- Interactive multi-shell coordination (script injection orchestration)
- HTML/JSON live progress endpoints

### Design Alignment
Introduce ToolRunner (exec + timeout + structured output), ConfigBuilder (idempotent flag synthesis), and ArtifactManager (paths, archives, checksums). Each tool wrapper emits structured ToolEvent objects consumed by result processing. All waits/timeouts pass through TimeoutManager to enforce global deadline.
