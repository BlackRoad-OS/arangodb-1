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

## Arangosh V8 Extension Dependencies

Agency coordination in the legacy JS layer indirectly relies on several arangosh-specific V8 injected utilities. These power HTTP communication, timing, auth token handling, state dumps, and randomness for IDs.

### Categories & Legacy Functions

1. HTTP & Networking
- Underlying usage via internal HTTP client built atop V8 utilities (e.g., SYS_DOWNLOAD style semantics)
- Redirect & leader-follow handling at agency endpoint level
- Timeout clamping before requests (deadline aware)

2. Data Encoding (VelocyPack / JSON)
- Transparent VPACK_TO_V8 / V8_TO_VPACK conversions for request/response bodies
- Mixed response handling (binary VPack vs JSON debug mode `--forceJson`)

3. Crypto / JWT
- JWT signing / header assembly (potential RSA/private key or shared secret)
- Hashing utilities (SHA256) occasionally for integrity checks

4. Random / ID Generation
- SYS_GEN_RANDOM_ALPHA_NUMBERS for log/job IDs, unique participant IDs

5. Timing / Deadlines
- correctTimeoutToExecutionDeadline* to avoid over-running global execution allowance
- Sleep/wait loops polling leader or supervision state

6. Logging & Diagnostics
- SYS_LOG(topic, level) for consensus transitions, retry backoff reporting
- Dynamic verbosity toggles for detailed Raft tracing

7. Filesystem
- FS_WRITE / FS_READ for agency dump exports
- Optional compression (deferred until broader dump tooling phase)

8. Errors
- JS_ArangoError for enriched error codes surfaced during agency operations

### Python Translation Plan (Initial Implementation Phase Mapping)

Category -> Python Module / Abstraction:
- HTTP Client -> armadillo.core.http (wrap httpx; retry + redirect + leader re-resolution)
- Data Codec -> armadillo.core.codec (JSON only initially; placeholder strategy for future VPack)
- JWT / Crypto -> armadillo.core.auth (HMAC/JWT handling using PyJWT or manual hmac + base64url)
- Random IDs -> armadillo.core.crypto.random_id(length=...) using secrets
- Deadlines -> armadillo.core.time.TimeoutManager.clamp_timeout()
- Logging -> armadillo.core.log (structured, with context: component=agency, action=...)
- FS Dumps -> armadillo.core.fs (write JSON snapshots)
- Errors -> armadillo.core.errors.AgencyError (inherits ArmadilloError)

### Deferred / Future Enhancements
- Direct VelocyPack request/response handling (Phase 4+ or dedicated extension)
- Leader redirect optimization (cache invalidation heuristics)
- Compressed (gzip) agency dump artifacts
- Detailed Raft trace channel (topic-based log filtering)
- RSA private signing support if required for advanced JWT modes

### Usage Hotspots in Agency Module
- Leader election polling loops: needs deadline clamping + jittered sleeps
- State read/modify CAS operations: HTTP + codec + error mapping
- Job creation & tracking: random ID, HTTP, retry with backoff
- Health supervision queries: periodic HTTP + timeout management
- Dump generation: filesystem write + timestamped naming

### Design Notes
- Provide AgencyClient abstraction encapsulating: (http_client, codec, auth_provider, timeout_manager, logger)
- All operations accept an optional per-call timeout which is clamped against global deadline
- Backoff policy centralized (e.g., exponential with upper bound) to avoid ad hoc sleeps scattered in code
