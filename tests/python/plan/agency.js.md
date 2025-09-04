# Agency Management Module (`agency.js`)

## Overview
Comprehensive cluster consensus management system handling ArangoDB's agency (Raft-based distributed coordination service). Provides complete lifecycle management for agency instances, health monitoring, leader election coordination, and distributed state management with advanced debugging capabilities.

## Core Functionality

### Agency Cluster Management
- **Multi-instance orchestration**: Manages configurable agency clusters (typically 3-node Raft consensus)
- **Leader election coordination**: Handles automatic leader detection and election processes
- **Health monitoring**: Continuous monitoring of agency node health and consensus status
- **Configuration management**: Dynamic configuration updates across all agency nodes
- **Endpoint management**: URL and endpoint resolution with automatic failover handling

### Replicated Log System
- **Distributed log management**: Complete replicated log lifecycle from creation to deletion
- **Participant configuration**: Dynamic addition/removal of log participants with quorum management
- **Term management**: Leadership term coordination with automatic term bumping for recovery
- **State synchronization**: Ensures all participants acknowledge current terms and reach operational state
- **Leader establishment**: Waits for and validates leader establishment across log instances

### Agency State Operations
- **Read/write operations**: Direct agency state manipulation with transactional support
- **Path-based access**: Hierarchical state access using ArangoDB's agency path structure
- **Compare-and-swap**: Atomic operations for safe concurrent state updates
- **Version management**: Automatic version incrementation for Plan/Target coordination
- **Unique ID generation**: Thread-safe unique identifier generation for logs and jobs

### Server Health Monitoring
- **Health status tracking**: Monitors server health states (GOOD/FAILED) in Supervision
- **Reboot ID management**: Tracks and bumps server reboot identifiers for crash recovery
- **Current/Plan synchronization**: Ensures server state consistency across agency views
- **DB server discovery**: Automatic detection and listing of database servers in cluster

### Advanced Recovery Operations
- **Leader recovery**: Triggers leader elections and waits for leadership establishment
- **Term bumping**: Forces leadership transitions for recovery scenarios
- **Shard-to-log mapping**: Translates collection shards to underlying replicated logs
- **Collection recovery**: Coordinates recovery of entire collections with all their shards
- **Server removal**: Safe removal of failed servers from cluster coordination

### Job Management System
- **Reconfiguration jobs**: Creates and manages replicated log reconfiguration operations
- **Job tracking**: Monitors job progress through agency ToDo system
- **Operation coordination**: Handles complex multi-step operations as atomic jobs

### Debugging and Diagnostics
- **Agency dump functionality**: Complete agency state export for debugging
- **Multi-format export**: JSON dumps of configuration, state, and plan data
- **Crash analysis integration**: Coordinates with crash detection systems
- **Test lifecycle tracking**: Records test begin/end timestamps for analysis
- **Error condition detection**: Identifies and reports agency consensus failures

### HTTP Communication
- **REST API integration**: Full agency REST API communication with authentication
- **Redirect handling**: Automatic following of agency leader redirects
- **JWT authentication**: Token-based authentication for secure agency communication
- **Request/response management**: Robust HTTP client with error handling and retries
- **Timeout management**: Configurable timeouts for agency operations

### Configuration and Setup
- **Size configuration**: Configurable agency cluster size (default 3 nodes)
- **Supervision control**: Enables/disables agency supervision features
- **Sync configuration**: Configurable wait-for-sync behavior
- **Authentication setup**: JWT and file-based authentication configuration
- **Endpoint resolution**: Automatic discovery and configuration of agency endpoints

## Key Features

### Consensus Management
- Raft consensus protocol coordination
- Leader election and term management
- Quorum maintenance and validation
- Split-brain prevention and recovery

### State Coordination
- Hierarchical state management (Plan/Target/Current)
- Atomic state transitions
- Version-based change tracking
- Conflict resolution and retry logic

### High Availability
- Automatic failover handling
- Health check integration
- Recovery coordination
- Maintenance mode support

### Integration Points
- Instance manager coordination
- Test framework integration
- Crash detection system integration
- Client tools coordination

## Test Framework Integration
- Provides agency management for cluster tests
- Coordinates with instance manager for cluster topology
- Integrates with crash detection for failure scenarios
- Supports test isolation and cleanup
- Enables agency dump collection for test debugging

## Error Handling
- Comprehensive retry logic for transient failures
- Graceful degradation during agency issues
- Detailed error reporting and diagnostics
- Integration with crash detection and analysis systems
