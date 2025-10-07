# InstanceManager Refactoring Design

## Problem Statement

The current `InstanceManager` class (1079 lines, 41 methods) violates the Single Responsibility Principle by handling at least 7 distinct responsibilities:
1. Deployment planning coordination
2. Server lifecycle management
3. Cluster orchestration logic
4. Health checking & monitoring
5. Server discovery & querying
6. Statistics collection
7. Resource management

## Design Goals

1. **Single Responsibility**: Each class has one clear purpose
2. **Testability**: Components can be tested in isolation
3. **Extensibility**: Easy to add new deployment strategies or monitoring approaches
4. **Maintainability**: Smaller, focused classes that are easier to understand
5. **Backward Compatibility**: Maintain existing API through facade pattern

## New Architecture

### Component Responsibilities

#### 1. DeploymentOrchestrator
**Responsibility**: High-level deployment lifecycle orchestration

**Core Methods**:
- `execute_deployment(plan: DeploymentPlan) -> None` - Execute deployment based on plan
- `shutdown_deployment(timeout: float) -> None` - Graceful shutdown
- `restart_deployment(timeout: float) -> None` - Restart all servers

**Dependencies**:
- ServerRegistry (to store created servers)
- ClusterBootstrapper (for cluster-specific logic)
- ServerFactory (to create servers)
- Logger

**Key Design**:
- Drives deployment from the DeploymentPlan (fixes the "unused plan" issue)
- Orchestrates the high-level flow, delegates specifics

#### 2. ClusterBootstrapper
**Responsibility**: Cluster-specific startup sequencing and agency management

**Core Methods**:
- `bootstrap_cluster(servers: Dict[str, ArangoServer]) -> None` - Bootstrap cluster
- `wait_for_agency_ready(timeout: float) -> None` - Wait for agency consensus
- `verify_cluster_ready(timeout: float) -> None` - Verify cluster is operational
- `start_servers_by_role(role: ServerRole, servers: List[ArangoServer]) -> None`

**Dependencies**:
- Logger
- ConfigProvider

**Key Design**:
- Encapsulates cluster-specific knowledge (agency, consensus, bootstrap sequence)
- Can be replaced with different strategies for different ArangoDB versions

#### 3. HealthMonitor
**Responsibility**: Health checking and monitoring of servers

**Core Methods**:
- `check_server_health(server: ArangoServer, timeout: float) -> HealthStatus`
- `check_deployment_health(servers: Dict[str, ArangoServer], timeout: float) -> HealthStatus`
- `collect_server_stats(server: ArangoServer) -> ServerStats`
- `collect_deployment_stats(servers: Dict[str, ArangoServer]) -> Dict[str, ServerStats]`

**Dependencies**:
- Logger
- HTTP client (requests)

**Key Design**:
- Pure health checking logic, no lifecycle management
- Easy to mock for testing
- Can be enhanced with more sophisticated health metrics

#### 4. ServerRegistry
**Responsibility**: Server storage, discovery, and lookup

**Core Methods**:
- `register_server(server_id: str, server: ArangoServer) -> None`
- `get_server(server_id: str) -> Optional[ArangoServer]`
- `get_servers_by_role(role: ServerRole) -> List[ArangoServer]`
- `get_all_servers() -> Dict[str, ArangoServer]`
- `get_endpoints_by_role(role: ServerRole) -> List[str]`
- `clear() -> None`

**Dependencies**: None (pure data structure)

**Key Design**:
- Thread-safe registry
- Simple query interface
- No business logic, just storage and retrieval

#### 5. InstanceManager (Refactored as Facade)
**Responsibility**: Simple facade API for backward compatibility

**Core Methods**:
- `create_deployment_plan(...)` - Delegate to planner
- `deploy_servers(...)` - Delegate to orchestrator
- `shutdown_deployment(...)` - Delegate to orchestrator
- `get_server(...)` - Delegate to registry
- `check_deployment_health(...)` - Delegate to health monitor

**Dependencies**:
- All the above components

**Key Design**:
- Thin facade, minimal logic
- Maintains backward compatibility
- Easy to deprecate if we want a cleaner API later

## Implementation Plan

### Phase 1: Create New Components (with tests)
1. ServerRegistry
2. HealthMonitor
3. ClusterBootstrapper
4. DeploymentOrchestrator

### Phase 2: Refactor InstanceManager
1. Integrate new components
2. Delegate to components
3. Remove duplicated code

### Phase 3: Update Tests
1. Add unit tests for new components
2. Update integration tests
3. Ensure all existing tests pass

### Phase 4: Cleanup
1. Remove old code
2. Update documentation
3. Performance verification

## Benefits

1. **Testability**: Each component can be tested independently with mocks
2. **Clarity**: Each class has <300 lines and <15 methods
3. **Extensibility**: Easy to swap ClusterBootstrapper for different ArangoDB versions
4. **Maintainability**: Easier to understand and modify
5. **Reusability**: Components can be reused in different contexts
6. **Fixes Design Issues**: The DeploymentPlan now actually drives the deployment

## Migration Strategy

- Keep old InstanceManager API intact (facade pattern)
- Gradually migrate internal implementation
- No breaking changes for external consumers
- Tests ensure behavior is preserved

