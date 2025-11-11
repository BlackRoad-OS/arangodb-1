# Implementation Plan

[Overview]
Refactor deployment architecture (issue armadillo-49) by eliminating pass-through layers so deployment strategies own full lifecycle and ServerRegistry is removed in favor of plain in-memory dicts per orchestrator.

The current chain InstanceManager → DeploymentOrchestrator → Strategy → ClusterBootstrapper introduces artificial indirection and duplicated data flow (plan + servers dict + registry). ServerRegistry adds locking despite single-threaded lifecycle mutations. Strategies are thin validators while real work happens in ArangoServer.start() and ClusterBootstrapper.bootstrap_cluster(). The refactor will make strategies construct, start, verify, and return server instances directly, collapsing storage to a dict managed by DeploymentOrchestrator (or InstanceManager facade). Health monitoring remains read-only on that dict. Background monitoring (future) will update per-server state but should not mutate membership. Multi-deployment support later: each deployment owns isolated dict; no global registry needed.

[Types]
Adapt type signatures to remove ServerRegistry and push ServerFactory + bootstrap logic into strategy classes, using Dict[ServerId, ArangoServer] as the authoritative runtime collection.

Detailed type changes and definitions:
- Remove class ServerRegistry entirely (file deletion).
- Replace all references to ServerRegistry with Dict[ServerId, ArangoServer].
- Replace DeploymentStrategy Protocol with concrete strategy classes exposing:
  - deploy(plan: DeploymentPlan, timeout: float) -> Dict[ServerId, ArangoServer]
  - startup_order: List[ServerId]
- SingleServerDeploymentStrategy: handles create/start/health verify of single server.
- ClusterDeploymentStrategy: handles create all servers + cluster bootstrap sequence.
- DeploymentOrchestrator internal collection: _servers: Dict[ServerId, ArangoServer]; _startup_order: List[ServerId].
- InstanceManager.state.servers continues as Dict[ServerId, ArangoServer]; sync copies from orchestrator (no registry).
- HealthMonitor functions updated to accept Dict[ServerId, ArangoServer] (change key type in signatures from Dict[str,...]).
- Remove threading.RLock references tied to registry.
- Optional future BackgroundMonitor Protocol (placeholder, not implemented): start(servers: Dict[ServerId, ArangoServer]) / stop().

[Files]
File modifications and lifecycle:
- Delete: tests/python/armadillo/armadillo/instances/server_registry.py
- Delete: tests/python/armadillo/framework_tests/unit/test_instances_server_registry.py
- Modify: tests/python/armadillo/armadillo/instances/deployment_strategy.py (rename to deployment_lifecycle.py or keep name; implement new strategy classes with deploy()).
- Modify: tests/python/armadillo/armadillo/instances/deployment_orchestrator.py (remove server_registry parameter and usage; remove _create_servers_from_plan; integrate strategy.deploy()).
- Modify: tests/python/armadillo/armadillo/instances/manager.py (remove _server_registry and related delegation; rename _sync_state_from_registry).
- Modify: tests/python/armadillo/armadillo/instances/server_factory.py (optional helper create_servers_for_plan(plan) delegating to existing create_server_instances()).
- Modify: tests/python/armadillo/armadillo/instances/health_monitor.py (update key types to ServerId).
- Modify: tests/python/armadillo/armadillo/instances/cluster_bootstrapper.py (ensure type hints use ServerId keys consistently).
- No change: deployment_plan.py (document that plan does not store runtime instances).
- New tests:
  - tests/python/armadillo/framework_tests/unit/test_deployment_strategies.py
  - tests/python/armadillo/framework_tests/integration/test_deployment_orchestrator_refactored.py
- Update imports in manager/orchestrator/tests removing ServerRegistry.

[Functions]
Function lifecycle adjustments:
- New SingleServerDeploymentStrategy.deploy(plan, timeout) -> Dict[ServerId, ArangoServer]; creates via factory, starts server, health_check_sync, populates startup_order.
- New ClusterDeploymentStrategy.deploy(plan, timeout) -> Dict[ServerId, ArangoServer]; creates all servers, invokes ClusterBootstrapper.bootstrap_cluster() which appends startup_order; returns servers dict.
- Modified DeploymentOrchestrator.execute_deployment: instantiate strategy, self._servers = strategy.deploy(plan, timeout), copy startup_order, run health monitor optionally.
- Modified DeploymentOrchestrator.shutdown_deployment: iterate self._servers directly; remove registry clear.
- Removed DeploymentOrchestrator._create_servers_from_plan.
- Modified InstanceManager._sync_state_from_registry -> _sync_state_from_orchestrator (copy orchestrator._servers).
- Modified InstanceManager.get_server/get_servers_by_role: operate directly on self.state.servers.
- Modified InstanceManager.check_deployment_health/collect_server_stats: pass self.state.servers to HealthMonitor.
- HealthMonitor signatures changed: Dict[ServerId, ArangoServer].
- Optional helper ServerFactory.create_servers_for_plan(plan): dispatch based on plan type.
- Removed all ServerRegistry-specific accessors (register_server, etc.).

[Classes]
Class-level modifications:
- Removed ServerRegistry class.
- Replaced DeploymentStrategy Protocol with concrete strategy classes (SingleServerDeploymentStrategy, ClusterDeploymentStrategy).
- Modified DeploymentOrchestrator (remove server_registry parameter; add _servers dict).
- Modified InstanceManager (remove _server_registry attribute; adapt sync and query methods).
- HealthMonitor key type adjustments (ServerId).
- ClusterBootstrapper unchanged semantically; maintain bootstrap_cluster signature with ServerId keys.
- ArangoServer unchanged.
- Optional future BackgroundMonitor placeholder (not implemented now).

[Dependencies]
No new third-party dependencies. Removed unnecessary threading imports (RLock). Continues to rely on ThreadPoolExecutor only inside ClusterBootstrapper. Update imports removing server_registry references. Ensure tests adapt.

[Testing]
Testing approach:
- Remove registry unit tests.
- Add unit tests for new strategies:
  - Single server deploy returns one started server, health verified.
  - Cluster deploy ensures startup_order sequencing: agents → dbservers → coordinators; failure injection test for agent startup aborts sequence.
- Add orchestrator integration test verifying execute_deployment populates internal dict and shutdown releases servers.
- Adjust existing InstanceManager deployment tests to reflect absence of registry.
- HealthMonitor tests remain valid; ensure they use ServerId key dict.
- Edge cases: duplicate deployment detection, shutdown with no servers, partial startup failure cleanup.

[Implementation Order]
Sequential steps minimizing disruption:
1. Introduce new strategy classes alongside existing ones; add new unit tests (keep old orchestrator path).
2. Refactor DeploymentOrchestrator to use new strategies guarded by transitional flag; ensure tests pass.
3. Update InstanceManager to synchronize from orchestrator internal dict; adjust health/stats calls; run tests.
4. Remove transitional flag; delete ServerRegistry usages from orchestrator and manager.
5. Delete ServerRegistry module and its tests; update imports.
6. Adjust HealthMonitor type hints and any dict key conversions to ServerId; run full test suite.
7. Clean up residual threading imports and obsolete comments.
8. Add new integration tests; verify startup/shutdown order correctness.
9. Documentation update (developer notes inside implementation_plan or README snippet).
10. Final regression test run and prepare for potential background monitoring integration.

# Read Overview section
sed -n '/[Overview]/,/[Types]/p' implementation_plan.md | head -n 1 | cat

# Read Types section
sed -n '/[Types]/,/[Files]/p' implementation_plan.md | head -n 1 | cat

# Read Files section
sed -n '/[Files]/,/[Functions]/p' implementation_plan.md | head -n 1 | cat

# Read Functions section
sed -n '/[Functions]/,/[Classes]/p' implementation_plan.md | head -n 1 | cat

# Read Classes section
sed -n '/[Classes]/,/[Dependencies]/p' implementation_plan.md | head -n 1 | cat

# Read Dependencies section
sed -n '/[Dependencies]/,/[Testing]/p' implementation_plan.md | head -n 1 | cat

# Read Testing section
sed -n '/[Testing]/,/[Implementation Order]/p' implementation_plan.md | head -n 1 | cat

# Read Implementation Order section
sed -n '/[Implementation Order]/,$p' implementation_plan.md | cat
