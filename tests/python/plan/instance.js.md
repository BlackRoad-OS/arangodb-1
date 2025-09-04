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
