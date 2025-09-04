# instance-manager.js - Instance Lifecycle Management

## Purpose
Comprehensive instance lifecycle manager that orchestrates creation, startup, monitoring, and shutdown of ArangoDB server instances across different topologies (single server, agency, cluster). Provides advanced health monitoring, crash detection, and resource management.

## Core Functionality

### Instance Orchestration
- **Multi-Instance Management**: Manages collections of ArangoDB instances with different roles (single, agent, coordinator, dbserver)
- **Topology Setup**: Supports single server, agency-only, and full cluster configurations
- **Startup Ordering**: Enforces proper startup dependencies (agents → dbservers → coordinators)
- **Resource Distribution**: Distributes memory limits across instances based on role (8% agency, 23% coordinator, 69% dbserver)

### Instance Lifecycle Management
- **Creation and Configuration**: Creates instances with role-specific configurations and memory limits
- **Startup Coordination**: `launchInstance()` manages sequential startup with health verification
- **Graceful Shutdown**: `shutdownInstance()` coordinates orderly shutdown with maintenance mode
- **Force Termination**: Emergency shutdown with core dump collection for crashed instances
- **Restart Management**: `reStartInstance()` handles instance restart with configuration updates

### Health Monitoring and Diagnostics
- **Continuous Health Checks**: `checkInstanceAlive()` monitors process and service health
- **Cluster Health Verification**: `_checkServersGOOD()` validates cluster formation and server status
- **Readiness Validation**: `checkClusterAlive()` ensures all instances are responding to requests
- **Network Monitoring**: Integration with netstat collection for connection tracking
- **Process Statistics**: Real-time process monitoring and resource usage tracking

### Crash Detection and Analysis
- **Crash Detection**: Automatic detection of instance crashes and abnormal terminations
- **Core Dump Management**: Automatic core dump generation for crashed instances
- **Debug Analysis**: Integration with crash analysis utilities for post-mortem debugging
- **Sanitizer Integration**: Processing of AddressSanitizer/ThreadSanitizer reports
- **Failure Point Management**: Debug failure point injection and management for testing

### Agency Management Integration
- **Agency Coordination**: Tight integration with agency manager for cluster consensus
- **Leader Election**: Monitoring and management of agency leader election
- **Agency Health**: Specialized health monitoring for agency instances
- **Configuration Synchronization**: Ensures agency configuration consistency

### Network and Communication Management
- **Endpoint Management**: Dynamic endpoint discovery and connection management
- **Protocol Support**: Support for TCP, SSL, Unix sockets, VST, and HTTP/2 protocols
- **Authentication Handling**: JWT and basic authentication management
- **Connection Pooling**: Manages connections to multiple instances

### Resource and Environment Management
- **Memory Management**: Per-instance memory limit enforcement and distribution
- **Directory Management**: Root directory setup and cleanup for instance data
- **Environment Variables**: Process environment configuration and isolation
- **Temporary Directory Management**: Cleanup and lifecycle management of temporary files

### Advanced Monitoring Features
- **TCP Packet Capture**: `launchTcpDump()` for network traffic analysis
- **Cluster Health Monitor**: Background monitoring process for continuous health checks
- **Process Statistics**: Delta statistics collection for performance analysis
- **Memory Profiling**: Memory snapshot collection for leak detection
- **Network Statistics**: Comprehensive netstat gathering and analysis

### Maintenance and Operations
- **Maintenance Mode**: Cluster maintenance mode coordination during operations
- **Leadership Resignation**: Controlled leadership handover for dbservers
- **Upgrade Coordination**: `upgradeCycleInstance()` for rolling upgrades
- **Server Suspension**: Temporary server suspension for testing scenarios

## Key Features

### Topology Support
- **Single Server**: Simple single instance setup
- **Agency Only**: Agency cluster for external coordination
- **Full Cluster**: Complete cluster with agents, dbservers, and coordinators
- **External Server**: Support for connecting to pre-existing external servers

### Health and Monitoring
- **Multi-Layer Health Checks**: Process-level, service-level, and cluster-level health validation
- **Startup Timeout Management**: Configurable timeouts with intelligent deadline handling
- **Crash Recovery**: Automatic crash detection and recovery procedures
- **Performance Monitoring**: Resource usage tracking and anomaly detection

### Security and Authentication
- **JWT Integration**: Full JWT token management and rotation
- **Encryption at Rest**: Support for encrypted storage configuration
- **Authentication Headers**: Automatic authentication header generation
- **Connection Security**: Secure connection management across protocols

### Development and Testing Support
- **Failure Point Injection**: Debug failure point management for testing error conditions
- **Valgrind Integration**: Memory debugging tool integration
- **External Tool Integration**: Support for external debugging and monitoring tools
- **Configuration Flexibility**: Extensive configuration options for testing scenarios

## Integration Points
- **Instance Module**: Individual instance management and control
- **Agency Manager**: Cluster consensus and coordination
- **Process Utils**: Process execution and monitoring utilities
- **Crash Utils**: Crash analysis and debugging integration
- **Result Processing**: Test result collection and analysis
- **Network Monitoring**: Network statistics and packet capture

## Configuration Options

### Instance Configuration
- `memory`: Total memory to distribute among instances
- `singles`/`coordinators`/`dbServers`: Number of instances per role
- `agencySize`: Number of agency instances for cluster
- `encryptionAtRest`: Enable disk encryption (Enterprise)

### Monitoring Configuration
- `disableClusterMonitor`: Disable background health monitoring
- `memprof`: Enable memory profiling snapshots
- `sniff`: Enable network packet capture
- `sleepBeforeStart`: Pause before startup for debugging

### Development Configuration
- `valgrind`: Enable Valgrind memory debugging
- `server`/`serverRoot`: Use external server instead of managed instances
- `extraArgs`: Additional command-line arguments for instances

## Error Handling and Recovery
- **Graceful Degradation**: Handles partial failures with appropriate cleanup
- **Timeout Management**: Sophisticated timeout handling with deadline enforcement
- **Resource Cleanup**: Comprehensive cleanup on failure or shutdown
- **Error Propagation**: Proper error reporting and stack trace preservation
