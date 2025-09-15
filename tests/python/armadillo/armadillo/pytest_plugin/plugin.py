"""Main pytest plugin for Armadillo framework integration."""

import pytest
import asyncio
import atexit
from typing import Generator, Optional, Dict, Any, List
from pathlib import Path

from ..core.config import load_config, get_config
from ..core.log import configure_logging, get_logger, log_test_event, set_log_context, clear_log_context
from ..core.time import set_global_deadline, stop_watchdog
from ..core.types import ServerRole, DeploymentMode, ClusterConfig
from ..instances.server import ArangoServer
from ..instances.manager import InstanceManager, get_instance_manager
from ..instances.orchestrator import ClusterOrchestrator, get_cluster_orchestrator
from ..utils.crypto import random_id
from ..utils.filesystem import set_test_session_id, clear_test_session, cleanup_work_dir

logger = get_logger(__name__)


class ArmadilloPlugin:
    """Main pytest plugin for Armadillo framework."""

    def __init__(self) -> None:
        self._session_servers: Dict[str, ArangoServer] = {}
        self._session_deployments: Dict[str, InstanceManager] = {}
        self._session_orchestrators: Dict[str, ClusterOrchestrator] = {}
        self._armadillo_config: Optional[Any] = None

    def pytest_configure(self, config: pytest.Config) -> None:
        """Configure pytest for Armadillo."""
        # Register custom markers
        config.addinivalue_line(
            "markers", "arango_single: Requires single ArangoDB server"
        )
        config.addinivalue_line(
            "markers", "arango_cluster: Requires ArangoDB cluster"
        )
        config.addinivalue_line(
            "markers", "slow: Long-running test (>30s expected)"
        )
        config.addinivalue_line(
            "markers", "fast: Fast test (<5s expected)"
        )
        config.addinivalue_line(
            "markers", "crash_test: Test involves intentional crashes"
        )
        config.addinivalue_line(
            "markers", "stress_test: High-load stress test"
        )
        config.addinivalue_line(
            "markers", "flaky: Test has known intermittent failures"
        )
        config.addinivalue_line(
            "markers", "auth_required: Test requires authentication"
        )
        config.addinivalue_line(
            "markers", "cluster_coordination: Tests cluster coordination features"
        )
        config.addinivalue_line(
            "markers", "replication: Tests data replication"
        )
        config.addinivalue_line(
            "markers", "sharding: Tests sharding functionality"
        )
        config.addinivalue_line(
            "markers", "failover: Tests high availability and failover"
        )
        config.addinivalue_line(
            "markers", "rta_suite: RTA test suite marker"
        )
        config.addinivalue_line(
            "markers", "smoke_test: Basic smoke test"
        )
        config.addinivalue_line(
            "markers", "regression: Regression test"
        )
        config.addinivalue_line(
            "markers", "performance: Performance measurement test"
        )

        # Configure Armadillo framework
        self._armadillo_config = load_config(
            verbose=config.option.verbose,
            # Add other CLI options as they become available
        )

        # Configure logging
        configure_logging(
            level="DEBUG" if config.option.verbose > 0 else "INFO",
            enable_console=True,
            enable_json=True,
        )

        # Set global test timeout
        set_global_deadline(self._armadillo_config.test_timeout)

        logger.info("Armadillo pytest plugin configured with timeout=%.1fs",
                   self._armadillo_config.test_timeout)

        # Pre-start session-scoped servers if needed
        self._maybe_start_session_servers(config)

    def pytest_unconfigure(self, config: pytest.Config) -> None:
        """Clean up after pytest run."""
        logger.debug("Starting pytest plugin cleanup")

        # Create a list of items to clean up to avoid modifying dicts during iteration
        deployments_to_clean = list(self._session_deployments.items())
        orchestrators_to_clean = list(self._session_orchestrators.items())
        servers_to_clean = list(self._session_servers.items())

        # Stop any remaining session deployments (safety net cleanup)
        for deployment_id, manager in deployments_to_clean:
            try:
                if manager.is_deployed():
                    logger.info(f"Plugin safety cleanup: shutting down deployment {deployment_id}")
                    manager.shutdown_deployment()
                else:
                    logger.debug(f"Deployment {deployment_id} already stopped")
            except Exception as e:
                logger.error(f"Error during plugin cleanup of deployment {deployment_id}: {e}")

        # Stop any remaining session orchestrators (safety net cleanup)
        for orchestrator_id, orchestrator in orchestrators_to_clean:
            try:
                logger.debug(f"Plugin safety cleanup: cleaning up orchestrator {orchestrator_id}")
                # Orchestrators don't have explicit cleanup methods, just remove from tracking
            except Exception as e:
                logger.error(f"Error during plugin cleanup of orchestrator {orchestrator_id}: {e}")

        # Stop any remaining session servers (safety net cleanup)
        for server_id, server in servers_to_clean:
            try:
                if server.is_running():
                    logger.info(f"Plugin safety cleanup: stopping server {server_id}")
                    server.stop()
                else:
                    logger.debug(f"Server {server_id} already stopped")
            except Exception as e:
                logger.error(f"Error during plugin cleanup of server {server_id}: {e}")

        # Clear tracking dictionaries
        self._session_deployments.clear()
        self._session_orchestrators.clear()
        self._session_servers.clear()

        # Stop timeout watchdog
        stop_watchdog()

        logger.info("Armadillo pytest plugin unconfigured")

    def _maybe_start_session_servers(self, config: pytest.Config) -> None:
        """Optionally pre-start session-scoped servers based on test collection.

        This method could analyze the collected tests and pre-start servers that
        will definitely be needed. For now, we use fixture-driven startup but
        with proper plugin tracking for safety net cleanup.

        Architecture:
        - Fixtures manage their own lifecycle (start/stop)
        - Plugin tracks all session-scoped resources for safety net cleanup
        - Plugin cleanup only activates if fixtures fail to clean up properly
        """
        logger.debug("Session server pre-start analysis complete")

    def pytest_sessionstart(self, session: pytest.Session) -> None:
        """Called at the beginning of the pytest session."""
        logger.debug("ArmadilloPlugin: Session start")

        # Load configuration
        load_config()

        # Configure logging
        configure_logging()

        # Initialize session-specific resources
        set_test_session_id()

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        """Called at the end of the pytest session."""
        logger.debug(f"ArmadilloPlugin: Session finish with exit status {exitstatus}")
        # Clean up session resources
        clear_test_session()
        cleanup_work_dir()
        stop_watchdog()

    def pytest_runtest_setup(self, item: pytest.Item) -> None:
        """Set up test execution environment."""
        test_name = item.nodeid
        set_log_context(test_name=test_name)
        log_test_event(logger, "setup", test_name=test_name)

    def pytest_runtest_teardown(self, item: pytest.Item, nextitem: Optional[pytest.Item]) -> None:
        """Clean up after test execution."""
        test_name = item.nodeid
        log_test_event(logger, "teardown", test_name=test_name)

        if nextitem is None:
            clear_log_context()

    def pytest_runtest_call(self, item: pytest.Item) -> None:
        """Handle test execution."""
        test_name = item.nodeid
        log_test_event(logger, "call", test_name=test_name)


# Global plugin instance
_plugin = ArmadilloPlugin()


def pytest_configure(config: pytest.Config) -> None:
    """Plugin entry point."""
    _plugin.pytest_configure(config)


def pytest_unconfigure(config: pytest.Config) -> None:
    """Plugin cleanup entry point."""
    _plugin.pytest_unconfigure(config)


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Test setup entry point."""
    _plugin.pytest_runtest_setup(item)


def pytest_runtest_teardown(item: pytest.Item, nextitem: Optional[pytest.Item]) -> None:
    """Test teardown entry point."""
    _plugin.pytest_runtest_teardown(item, nextitem)


def pytest_runtest_call(item: pytest.Item) -> None:
    """Test call entry point."""
    _plugin.pytest_runtest_call(item)


# Fixtures
@pytest.fixture(scope="session")
def arango_single_server() -> Generator[ArangoServer, None, None]:
    """Provide a single ArangoDB server for testing."""
    server = ArangoServer("test_single_server", ServerRole.SINGLE)

    try:
        logger.info("Starting session single server")
        server.start(timeout=60.0)

        # Verify server is healthy
        health = server.health_check_sync(timeout=10.0)
        if not health.is_healthy:
            raise RuntimeError(f"Server health check failed: {health.error_message}")

        logger.info(f"Session single server ready at {server.endpoint}")
        _plugin._session_servers["single"] = server
        yield server

    finally:
        logger.info("Stopping session single server")
        try:
            server.stop(timeout=30.0)
            logger.debug("Session single server stopped successfully")
        except Exception as e:
            logger.error(f"Error stopping session server: {e}")
        finally:
            # Always remove from plugin tracking, even if stop failed
            _plugin._session_servers.pop("single", None)
            logger.debug("Session single server removed from plugin tracking")


@pytest.fixture(scope="function")
def arango_single_server_function() -> Generator[ArangoServer, None, None]:
    """Provide a function-scoped single ArangoDB server."""
    from ..utils.crypto import random_id

    server_id = f"test_func_{random_id(8)}"
    server = ArangoServer(server_id, ServerRole.SINGLE)

    try:
        logger.info(f"Starting function server {server_id}")
        server.start(timeout=30.0)

        # Verify server is healthy
        health = server.health_check_sync(timeout=5.0)
        if not health.is_healthy:
            raise RuntimeError(f"Server health check failed: {health.error_message}")

        logger.info(f"Function server {server_id} ready at {server.endpoint}")
        yield server

    finally:
        logger.info(f"Stopping function server {server_id}")
        try:
            server.stop(timeout=15.0)
        except Exception as e:
            logger.error(f"Error stopping function server {server_id}: {e}")


@pytest.fixture(scope="session")
def arango_cluster() -> Generator[InstanceManager, None, None]:
    """Provide a full ArangoDB cluster for testing."""
    deployment_id = f"cluster_{random_id(8)}"
    manager = get_instance_manager(deployment_id)

    try:
        logger.info(f"Starting session cluster deployment {deployment_id}")

        # Create cluster deployment plan
        cluster_config = ClusterConfig(
            agents=3,
            dbservers=2,
            coordinators=1
        )
        plan = manager.create_deployment_plan(DeploymentMode.CLUSTER, cluster_config)

        # Deploy cluster
        manager.deploy_servers(timeout=300.0)

        # Initialize cluster coordination
        orchestrator = get_cluster_orchestrator(deployment_id)
        asyncio.run(orchestrator.initialize_cluster_coordination(timeout=120.0))

        # Wait for cluster to be ready
        asyncio.run(orchestrator.wait_for_cluster_ready(timeout=180.0))

        logger.info(f"Session cluster deployment {deployment_id} ready")
        # Register with plugin for tracking and safety cleanup
        _plugin._session_deployments[deployment_id] = manager
        _plugin._session_orchestrators[deployment_id] = orchestrator
        logger.debug(f"Cluster deployment {deployment_id} registered with plugin")

        yield manager

    finally:
        logger.info(f"Stopping session cluster deployment {deployment_id}")
        try:
            manager.shutdown_deployment(timeout=120.0)
            logger.debug(f"Cluster deployment {deployment_id} stopped successfully")
        except Exception as e:
            logger.error(f"Error stopping cluster deployment {deployment_id}: {e}")
        finally:
            # Always remove from plugin tracking, even if shutdown failed
            _plugin._session_deployments.pop(deployment_id, None)
            _plugin._session_orchestrators.pop(deployment_id, None)
            logger.debug(f"Cluster deployment {deployment_id} removed from plugin tracking")


@pytest.fixture(scope="function")
def arango_cluster_function() -> Generator[InstanceManager, None, None]:
    """Provide a function-scoped ArangoDB cluster."""
    deployment_id = f"cluster_func_{random_id(8)}"
    manager = get_instance_manager(deployment_id)

    try:
        logger.info(f"Starting function cluster deployment {deployment_id}")

        # Create minimal cluster for faster function-scoped tests
        cluster_config = ClusterConfig(
            agents=3,
            dbservers=1,
            coordinators=1
        )
        plan = manager.create_deployment_plan(DeploymentMode.CLUSTER, cluster_config)

        # Deploy cluster
        manager.deploy_servers(timeout=180.0)

        # Initialize cluster coordination
        orchestrator = get_cluster_orchestrator(deployment_id)
        asyncio.run(orchestrator.initialize_cluster_coordination(timeout=60.0))
        asyncio.run(orchestrator.wait_for_cluster_ready(timeout=90.0))

        logger.info(f"Function cluster deployment {deployment_id} ready")
        yield manager

    finally:
        logger.info(f"Stopping function cluster deployment {deployment_id}")
        try:
            manager.shutdown_deployment(timeout=60.0)
        except Exception as e:
            logger.error(f"Error stopping function cluster {deployment_id}: {e}")


@pytest.fixture
def arango_orchestrator(arango_cluster) -> ClusterOrchestrator:
    """Provide cluster orchestrator for advanced cluster operations."""
    deployment_id = list(_plugin._session_orchestrators.keys())[0]
    return _plugin._session_orchestrators[deployment_id]


@pytest.fixture
def arango_coordinators(arango_cluster) -> List[ArangoServer]:
    """Provide list of coordinator servers from cluster."""
    return arango_cluster.get_servers_by_role(ServerRole.COORDINATOR)


@pytest.fixture
def arango_dbservers(arango_cluster) -> List[ArangoServer]:
    """Provide list of database servers from cluster."""
    return arango_cluster.get_servers_by_role(ServerRole.DBSERVER)


@pytest.fixture
def arango_agents(arango_cluster) -> List[ArangoServer]:
    """Provide list of agent servers from cluster."""
    return arango_cluster.get_servers_by_role(ServerRole.AGENT)


# Marker-based automatic fixture selection
def pytest_fixture_setup(fixturedef, request):
    """Automatic fixture setup based on markers."""
    # Auto-provision server instances based on test markers
    if hasattr(request, 'node') and hasattr(request.node, 'iter_markers'):
        # Check for cluster requirements
        if any(marker.name == 'arango_cluster' for marker in request.node.iter_markers()):
            logger.debug(f"Test {request.node.nodeid} requires cluster - using arango_cluster fixture")

        # Check for single server requirements
        elif any(marker.name == 'arango_single' for marker in request.node.iter_markers()):
            logger.debug(f"Test {request.node.nodeid} requires single server - using arango_single_server fixture")


def pytest_collection_modifyitems(config, items):
    """Modify test collection based on markers and configuration."""
    # Apply default markers based on test patterns
    for item in items:
        # Mark tests as slow if they use cluster fixtures
        if any(fixture in ['arango_cluster', 'arango_cluster_function']
               for fixture in getattr(item, 'fixturenames', [])):
            item.add_marker(pytest.mark.slow)

        # Mark tests as fast if they use function-scoped fixtures
        elif any(fixture in ['arango_single_server_function']
                 for fixture in getattr(item, 'fixturenames', [])):
            item.add_marker(pytest.mark.fast)

        # Auto-mark stress tests based on name patterns
        if 'stress' in item.name.lower() or 'load' in item.name.lower():
            item.add_marker(pytest.mark.stress_test)
            item.add_marker(pytest.mark.slow)

        # Auto-mark crash tests
        if 'crash' in item.name.lower() or 'fail' in item.name.lower():
            item.add_marker(pytest.mark.crash_test)

        # Auto-mark performance tests
        if any(word in item.name.lower() for word in ['perf', 'benchmark', 'timing']):
            item.add_marker(pytest.mark.performance)


def pytest_runtest_setup(item):
    """Enhanced test setup with marker-based logic."""
    # Skip slow tests unless explicitly requested
    if item.get_closest_marker("slow"):
        if not item.config.getoption("--runslow", default=False):
            pytest.skip("need --runslow option to run slow tests")

    # Skip stress tests in normal runs
    if item.get_closest_marker("stress_test"):
        if not item.config.getoption("--stress", default=False):
            pytest.skip("need --stress option to run stress tests")

    # Skip flaky tests unless explicitly requested
    if item.get_closest_marker("flaky"):
        if not item.config.getoption("--flaky", default=False):
            pytest.skip("need --flaky option to run flaky tests")


def pytest_addoption(parser):
    """Add custom command line options."""
    parser.addoption(
        "--runslow", action="store_true", default=False,
        help="run slow tests"
    )
    parser.addoption(
        "--stress", action="store_true", default=False,
        help="run stress tests"
    )
    parser.addoption(
        "--flaky", action="store_true", default=False,
        help="run flaky tests"
    )
    parser.addoption(
        "--deployment-mode", action="store", default="single",
        choices=["single", "cluster"],
        help="default deployment mode for tests"
    )


@pytest.hookimpl(tryfirst=True)
def pytest_sessionstart(session):
    """Set up test session with isolated directories and register cleanup."""
    logger.debug("Starting pytest plugin setup")

    # Set up test session isolation
    session_id = set_test_session_id()
    logger.info(f"Test session started with ID: {session_id}")

    # Register emergency cleanup at exit
    atexit.register(_emergency_cleanup)


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    """Clean up all resources at the end of test session."""
    logger.debug("Starting pytest plugin cleanup")

    try:
        # Force cleanup of any remaining deployments
        _cleanup_all_deployments()

        # Force cleanup of any remaining processes
        _cleanup_all_processes()

        # Clean up work directories
        cleanup_work_dir()

        # Clear test session
        clear_test_session()

        logger.info("Armadillo pytest plugin cleanup completed")

    except Exception as e:
        logger.error(f"Error during pytest plugin cleanup: {e}")
    finally:
        # Stop the timeout watchdog
        try:
            stop_watchdog()
        except Exception as e:
            logger.debug(f"Error stopping watchdog: {e}")


def _cleanup_all_deployments():
    """Emergency cleanup of all tracked deployments with bulletproof shutdown."""
    if hasattr(_plugin, '_session_deployments'):
        deployments = list(_plugin._session_deployments.items())

        if deployments:
            logger.warning(f"Emergency cleanup of {len(deployments)} deployments")

            for deployment_id, manager in deployments:
                try:
                    logger.info(f"Emergency shutdown of deployment: {deployment_id}")

                    # Use shorter timeout for emergency cleanup - we need to be aggressive
                    manager.shutdown_deployment(timeout=15.0)
                    logger.debug(f"Deployment {deployment_id} shutdown completed")

                except Exception as e:
                    logger.error(f"Failed emergency cleanup of deployment {deployment_id}: {e}")

                    # Try to force kill processes directly if manager shutdown failed
                    try:
                        logger.warning(f"Attempting direct process cleanup for failed deployment {deployment_id}")
                        if hasattr(manager, '_servers'):
                            for server_id, server in manager._servers.items():
                                try:
                                    if hasattr(server, '_process_info') and server._process_info:
                                        from ..core.process import _process_supervisor
                                        _process_supervisor.stop(server_id, graceful=False, timeout=5.0)
                                        logger.debug(f"Force killed server {server_id}")
                                except Exception as server_e:
                                    logger.error(f"Failed to force kill server {server_id}: {server_e}")
                    except Exception as force_e:
                        logger.error(f"Failed direct process cleanup for deployment {deployment_id}: {force_e}")

        # Always clear tracking, even if some shutdowns failed
        _plugin._session_deployments.clear()
        _plugin._session_orchestrators.clear()
        logger.info("Emergency deployment cleanup completed")


def _cleanup_all_processes():
    """Emergency cleanup of all supervised processes with bulletproof termination."""
    try:
        from ..core.process import _process_supervisor

        # Get all tracked processes
        if hasattr(_process_supervisor, '_processes'):
            process_ids = list(_process_supervisor._processes.keys())

            if process_ids:
                logger.warning(f"Emergency cleanup of {len(process_ids)} processes: {process_ids}")

                # First pass: Try graceful termination with short timeout
                logger.info("Phase 1: Attempting graceful shutdown (SIGTERM, 3s timeout)")
                graceful_failed = []

                for process_id in process_ids:
                    try:
                        _process_supervisor.stop(process_id, graceful=True, timeout=3.0)
                        logger.debug(f"Process {process_id} terminated gracefully")
                    except Exception as e:
                        logger.warning(f"Graceful termination failed for {process_id}: {e}")
                        graceful_failed.append(process_id)

                # Second pass: Force kill any remaining processes
                if graceful_failed:
                    logger.warning(f"Phase 2: Force killing {len(graceful_failed)} stubborn processes: {graceful_failed}")

                    for process_id in graceful_failed:
                        try:
                            _process_supervisor.stop(process_id, graceful=False, timeout=2.0)
                            logger.debug(f"Process {process_id} force killed")
                        except Exception as e:
                            logger.error(f"CRITICAL: Failed to force kill process {process_id}: {e}")
                            # Continue with cleanup of other processes

                logger.info("Emergency process cleanup completed")

    except Exception as e:
        logger.error(f"Error during emergency process cleanup: {e}")
        import traceback
        logger.error(f"Stack trace: {traceback.format_exc()}")


def _emergency_cleanup():
    """Emergency cleanup function registered with atexit."""
    logger.warning("Emergency cleanup triggered via atexit")
    try:
        # Phase 1: Try normal cleanup
        _cleanup_all_deployments()
        _cleanup_all_processes()

        # Phase 2: If anything is still running, use nuclear option
        try:
            from ..core.process import kill_all_supervised_processes
            kill_all_supervised_processes()
        except Exception as nuclear_e:
            logger.error(f"Nuclear cleanup failed: {nuclear_e}")

    except Exception as e:
        logger.error(f"Error in emergency cleanup: {e}")
        import traceback
        logger.error(f"Emergency cleanup stack trace: {traceback.format_exc()}")

