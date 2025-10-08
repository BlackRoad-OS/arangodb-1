"""Main pytest plugin for Armadillo framework integration."""

import asyncio
import atexit
import logging
import signal
import sys
import pytest
import time
import traceback
from typing import Generator, Optional, Dict, Any, List
from ..core.config import get_config
from ..core.log import (
    configure_logging,
    get_logger,
    log_test_event,
    set_log_context,
    clear_log_context,
)
from ..core.time import set_global_deadline, stop_watchdog
from ..core.types import ServerRole, DeploymentMode, ClusterConfig
from ..instances.server import ArangoServer
from ..instances.manager import InstanceManager, get_instance_manager
from .reporter import get_armadillo_reporter
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
        # In pytest subprocess, config needs to be loaded from environment variables
        # get_config() will call load_config() if not already loaded
        framework_config = get_config()
        if framework_config.log_level != "DEBUG":
            logging.getLogger("faker").setLevel(logging.WARNING)
            logging.getLogger("urllib3").setLevel(logging.WARNING)
            logging.getLogger("requests").setLevel(logging.WARNING)
            logging.getLogger("asyncio").setLevel(logging.WARNING)
            logging.getLogger("aiohttp").setLevel(logging.WARNING)
        self._deployment_mode = framework_config.deployment_mode.value
        self._compact_mode = framework_config.compact_mode
        self._armadillo_config = framework_config
        self._register_markers(config)
        configure_logging(
            level="DEBUG" if config.option.verbose > 0 else "INFO",
            enable_console=True,
            enable_json=True,
        )
        set_global_deadline(self._armadillo_config.test_timeout)
        logger.info(
            "Armadillo pytest plugin configured with timeout=%.1fs",
            self._armadillo_config.test_timeout,
        )
        self._maybe_start_session_servers(config)

    def _register_markers(self, config: pytest.Config) -> None:
        """Register custom markers for Armadillo tests."""
        config.addinivalue_line(
            "markers", "arango_single: Requires single ArangoDB server"
        )
        config.addinivalue_line("markers", "arango_cluster: Requires ArangoDB cluster")
        config.addinivalue_line("markers", "slow: Long-running test (>30s expected)")
        config.addinivalue_line("markers", "fast: Fast test (<5s expected)")
        config.addinivalue_line(
            "markers", "crash_test: Test involves intentional crashes"
        )
        config.addinivalue_line("markers", "stress_test: High-load stress test")
        config.addinivalue_line(
            "markers", "flaky: Test has known intermittent failures"
        )
        config.addinivalue_line(
            "markers", "auth_required: Test requires authentication"
        )
        config.addinivalue_line(
            "markers", "cluster_coordination: Tests cluster coordination features"
        )
        config.addinivalue_line("markers", "replication: Tests data replication")
        config.addinivalue_line("markers", "sharding: Tests sharding functionality")
        config.addinivalue_line(
            "markers", "failover: Tests high availability and failover"
        )
        config.addinivalue_line("markers", "rta_suite: RTA test suite marker")
        config.addinivalue_line("markers", "smoke_test: Basic smoke test")
        config.addinivalue_line("markers", "regression: Regression test")
        config.addinivalue_line("markers", "performance: Performance measurement test")

    def pytest_unconfigure(self, _config: pytest.Config) -> None:
        """Clean up after pytest run."""
        logger.debug("Starting pytest plugin cleanup")
        deployments_to_clean = list(self._session_deployments.items())
        orchestrators_to_clean = list(self._session_orchestrators.items())
        servers_to_clean = list(self._session_servers.items())
        for deployment_id, manager in deployments_to_clean:
            try:
                if manager.is_deployed():
                    logger.info(
                        "Plugin safety cleanup: shutting down deployment %s",
                        deployment_id,
                    )
                    manager.shutdown_deployment()
                else:
                    logger.debug("Deployment %s already stopped", deployment_id)
            except (OSError, ProcessLookupError, RuntimeError, AttributeError) as e:
                logger.error(
                    "Error during plugin cleanup of deployment %s: %s", deployment_id, e
                )
        for orchestrator_id, orchestrator in orchestrators_to_clean:
            try:
                logger.debug(
                    "Plugin safety cleanup: cleaning up orchestrator %s",
                    orchestrator_id,
                )
                orchestrator.cancel_all_operations()
            except (OSError, RuntimeError) as e:
                logger.error(
                    "Error during plugin cleanup of orchestrator %s: %s",
                    orchestrator_id,
                    e,
                )
        for server_id, server in servers_to_clean:
            try:
                if server.is_running():
                    logger.info("Plugin safety cleanup: stopping server %s", server_id)
                    server.stop()
                else:
                    logger.debug("Server %s already stopped", server_id)
            except (OSError, ProcessLookupError, RuntimeError, AttributeError) as e:
                logger.error(
                    "Error during plugin cleanup of server %s: %s", server_id, e
                )
        self._session_deployments.clear()
        self._session_orchestrators.clear()
        self._session_servers.clear()
        stop_watchdog()
        logger.info("Armadillo pytest plugin unconfigured")

    def _maybe_start_session_servers(self, _config: pytest.Config) -> None:
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

    def pytest_sessionstart(self, _session: pytest.Session) -> None:
        """Called at the beginning of the pytest session."""
        logger.debug("ArmadilloPlugin: Session start")
        # Config already loaded by CLI and pytest_configure
        # Don't call load_config() again to avoid duplicate build detection
        configure_logging()
        set_test_session_id()

    def pytest_sessionfinish(self, _session: pytest.Session, exitstatus: int) -> None:
        """Called at the end of the pytest session."""
        logger.debug("ArmadilloPlugin: Session finish with exit status %s", exitstatus)
        for server_id, server in list(self._session_servers.items()):
            try:
                logger.debug("Stopping session server %s", server_id)
                server.stop(timeout=30.0)
            except (OSError, ProcessLookupError, RuntimeError, AttributeError) as e:
                logger.error("Error stopping session server %s: %s", server_id, e)
        for deployment_id, manager in list(self._session_deployments.items()):
            try:
                logger.debug("Stopping session deployment %s", deployment_id)
                manager.destroy_all_servers(timeout=60.0)
            except (OSError, ProcessLookupError, RuntimeError, AttributeError) as e:
                logger.error(
                    "Error stopping session deployment %s: %s", deployment_id, e
                )
        clear_test_session()
        cleanup_work_dir()
        stop_watchdog()

    def pytest_runtest_setup(self, item: pytest.Item) -> None:
        """Set up test execution environment."""
        test_name = item.nodeid
        set_log_context(test_name=test_name)
        log_test_event(logger, "setup", test_name=test_name)

    def pytest_runtest_teardown(
        self, item: pytest.Item, nextitem: Optional[pytest.Item]
    ) -> None:
        """Clean up after test execution."""
        test_name = item.nodeid
        log_test_event(logger, "teardown", test_name=test_name)
        if nextitem is None:
            clear_log_context()

    def pytest_runtest_call(self, item: pytest.Item) -> None:
        """Handle test execution."""
        test_name = item.nodeid
        log_test_event(logger, "call", test_name=test_name)


_plugin = ArmadilloPlugin()


def pytest_configure(config: pytest.Config) -> None:
    """Plugin entry point."""
    _plugin.pytest_configure(config)


def pytest_unconfigure(config: pytest.Config) -> None:
    """Plugin cleanup entry point."""
    _plugin.pytest_unconfigure(config)


@pytest.fixture(scope="session")
def arango_single_server() -> Generator[ArangoServer, None, None]:
    """Provide a single ArangoDB server for testing."""
    server = _create_configured_server("test_single_server")
    try:
        logger.info("Starting session single server")
        server.start(timeout=60.0)
        health = server.health_check_sync(timeout=10.0)
        if not health.is_healthy:
            raise RuntimeError(f"Server health check failed: {health.error_message}")
        logger.info("Session single server ready at %s", server.endpoint)
        _plugin._session_servers["single"] = server
        yield server
    finally:
        logger.info("Stopping session single server")
        try:
            server.stop(timeout=30.0)
            logger.debug("Session single server stopped successfully")
        except (OSError, ProcessLookupError, RuntimeError, AttributeError) as e:
            logger.error("Error stopping session server: %s", e)
        finally:
            _plugin._session_servers.pop("single", None)
            logger.debug("Session single server removed from plugin tracking")


@pytest.fixture(scope="session")
def arango_deployment():
    """Provide ArangoDB deployment based on CLI configuration - deployment agnostic.

    Returns the appropriate server/coordinator endpoint regardless of whether
    we're running single server or cluster mode.
    """
    framework_config = get_config()
    deployment_mode = framework_config.deployment_mode
    if deployment_mode == DeploymentMode.CLUSTER:
        logger.info("Auto-detecting cluster deployment for tests")
        cluster_manager = _plugin._get_or_create_cluster()
        coordinators = cluster_manager.get_servers_by_role(ServerRole.COORDINATOR)
        if not coordinators:
            raise RuntimeError("No coordinators available in cluster")
        return coordinators[0]
    else:
        logger.info("Auto-detecting single server deployment for tests")
        return _plugin._get_or_create_single_server()


def _get_or_create_cluster(self) -> "InstanceManager":
    """Get or create session cluster deployment."""
    if "cluster" not in self._session_deployments:
        deployment_id = f"cluster_{random_id(8)}"
        manager = get_instance_manager(deployment_id)
        logger.info("Starting session cluster deployment %s", deployment_id)
        cluster_config = ClusterConfig(agents=3, dbservers=2, coordinators=1)
        manager.create_deployment_plan(cluster_config)
        manager.deploy_servers(timeout=300.0)
        logger.info("Session cluster deployment ready")
        self._session_deployments["cluster"] = manager
    return self._session_deployments["cluster"]


def _get_or_create_single_server(self) -> ArangoServer:
    """Get or create session single server."""
    if "single" not in self._session_servers:
        server = _create_configured_server("test_single_server")
        logger.info("Starting session single server")
        server.start(timeout=60.0)
        health = server.health_check_sync(timeout=10.0)
        if not health.is_healthy:
            raise RuntimeError(f"Server health check failed: {health.error_message}")
        logger.info("Session single server ready at %s", server.endpoint)
        self._session_servers["single"] = server
    return self._session_servers["single"]


def _create_configured_server(server_id: str) -> ArangoServer:
    """Create an ArangoDB server with proper logging configuration.

    This centralizes the server creation logic to eliminate duplication across
    all the pytest plugin's server creation functions.

    Args:
        server_id: Unique identifier for the server

    Returns:
        Configured ArangoServer instance (not started)
    """
    from ..core.config import get_config as get_framework_config
    from ..core.log import get_logger as get_framework_logger
    from ..instances.server_config_builder import ServerConfigBuilder
    from ..instances.server_factory import MinimalConfig

    config = get_framework_config()
    server_logger = get_framework_logger(__name__)

    # Use centralized server configuration logic
    config_builder = ServerConfigBuilder(config, server_logger)
    server_args = config_builder.build_server_args()

    # Create minimal config with logging arguments
    minimal_config = MinimalConfig(args=server_args)

    # Create configured server (caller is responsible for starting)
    return ArangoServer(server_id, role=ServerRole.SINGLE, config=minimal_config)


ArmadilloPlugin._get_or_create_cluster = _get_or_create_cluster
ArmadilloPlugin._get_or_create_single_server = _get_or_create_single_server


@pytest.fixture(scope="function")
def arango_single_server_function() -> Generator[ArangoServer, None, None]:
    """Provide a function-scoped single ArangoDB server."""
    server_id = f"test_func_{random_id(8)}"
    server = _create_configured_server(server_id)
    try:
        logger.info("Starting function server %s", server_id)
        server.start(timeout=30.0)
        health = server.health_check_sync(timeout=5.0)
        if not health.is_healthy:
            raise RuntimeError(f"Server health check failed: {health.error_message}")
        logger.info("Function server %s ready at %s", server_id, server.endpoint)
        yield server
    finally:
        logger.info("Stopping function server %s", server_id)
        try:
            server.stop(timeout=15.0)
        except (OSError, ProcessLookupError, RuntimeError, AttributeError) as e:
            logger.error("Error stopping function server %s: %s", server_id, e)


@pytest.fixture(scope="session")
def arango_cluster() -> Generator[InstanceManager, None, None]:
    """Provide a full ArangoDB cluster for testing."""
    deployment_id = f"cluster_{random_id(8)}"
    manager = get_instance_manager(deployment_id)
    try:
        logger.info("Starting session cluster deployment %s", deployment_id)
        cluster_config = ClusterConfig(agents=3, dbservers=2, coordinators=1)
        manager.create_deployment_plan(cluster_config)
        manager.deploy_servers(timeout=300.0)
        logger.info("Session cluster deployment %s ready", deployment_id)
        _plugin._session_deployments[deployment_id] = manager
        logger.debug("Cluster deployment %s registered with plugin", deployment_id)
        yield manager
    finally:
        logger.info("Stopping session cluster deployment %s", deployment_id)
        try:
            manager.shutdown_deployment(timeout=120.0)
            logger.debug("Cluster deployment %s stopped successfully", deployment_id)
        except (OSError, ProcessLookupError, RuntimeError, AttributeError) as e:
            logger.error("Error stopping cluster deployment %s: %s", deployment_id, e)
        finally:
            _plugin._session_deployments.pop(deployment_id, None)
            logger.debug(
                "Cluster deployment %s removed from plugin tracking", deployment_id
            )


@pytest.fixture(scope="function")
def arango_cluster_function() -> Generator[InstanceManager, None, None]:
    """Provide a function-scoped ArangoDB cluster."""
    deployment_id = f"cluster_func_{random_id(8)}"
    manager = get_instance_manager(deployment_id)
    try:
        logger.info("Starting function cluster deployment %s", deployment_id)
        cluster_config = ClusterConfig(agents=3, dbservers=1, coordinators=1)
        manager.create_deployment_plan(cluster_config)
        manager.deploy_servers(timeout=180.0)
        orchestrator = get_cluster_orchestrator(deployment_id)
        asyncio.run(orchestrator.initialize_cluster_coordination(timeout=60.0))
        asyncio.run(orchestrator.wait_for_cluster_ready(timeout=90.0))
        logger.info("Function cluster deployment %s ready", deployment_id)
        yield manager
    finally:
        logger.info("Stopping function cluster deployment %s", deployment_id)
        try:
            manager.shutdown_deployment(timeout=60.0)
        except (OSError, ProcessLookupError, RuntimeError, AttributeError) as e:
            logger.error("Error stopping function cluster %s: %s", deployment_id, e)


@pytest.fixture
def arango_orchestrator(
    arango_cluster,
) -> ClusterOrchestrator:  # pylint: disable=redefined-outer-name
    """Provide cluster orchestrator for advanced cluster operations."""
    # Use the cluster's deployment_id to get the proper orchestrator
    # instead of relying on global state lookup
    from ..instances.orchestrator import get_cluster_orchestrator as get_orchestrator

    return get_orchestrator(arango_cluster.deployment_id)


@pytest.fixture
def arango_coordinators(
    arango_cluster,
) -> List[ArangoServer]:  # pylint: disable=redefined-outer-name
    """Provide list of coordinator servers from cluster."""
    return arango_cluster.get_servers_by_role(ServerRole.COORDINATOR)


@pytest.fixture
def arango_dbservers(
    arango_cluster,
) -> List[ArangoServer]:  # pylint: disable=redefined-outer-name
    """Provide list of database servers from cluster."""
    return arango_cluster.get_servers_by_role(ServerRole.DBSERVER)


@pytest.fixture
def arango_agents(
    arango_cluster,
) -> List[ArangoServer]:  # pylint: disable=redefined-outer-name
    """Provide list of agent servers from cluster."""
    return arango_cluster.get_servers_by_role(ServerRole.AGENT)


def pytest_fixture_setup(fixturedef, request):
    """Automatic fixture setup based on markers."""
    if hasattr(request, "node") and hasattr(request.node, "iter_markers"):
        if any(
            (marker.name == "arango_cluster" for marker in request.node.iter_markers())
        ):
            logger.debug(
                "Test %s requires cluster - using arango_cluster fixture",
                request.node.nodeid,
            )
        elif any(
            (marker.name == "arango_single" for marker in request.node.iter_markers())
        ):
            logger.debug(
                "Test %s requires single server - using arango_single_server fixture",
                request.node.nodeid,
            )


def pytest_collection_modifyitems(config, items):
    """Modify test collection based on markers and configuration."""
    for item in items:
        if any(
            (
                fixture in ["arango_cluster", "arango_cluster_function"]
                for fixture in getattr(item, "fixturenames", [])
            )
        ):
            item.add_marker(pytest.mark.slow)
        elif any(
            (
                fixture in ["arango_single_server_function"]
                for fixture in getattr(item, "fixturenames", [])
            )
        ):
            item.add_marker(pytest.mark.fast)
        if "stress" in item.name.lower() or "load" in item.name.lower():
            item.add_marker(pytest.mark.stress_test)
            item.add_marker(pytest.mark.slow)
        if "crash" in item.name.lower() or "fail" in item.name.lower():
            item.add_marker(pytest.mark.crash_test)
        if any((word in item.name.lower() for word in ["perf", "benchmark", "timing"])):
            item.add_marker(pytest.mark.performance)


def pytest_addoption(parser):
    """Add custom command line options."""
    parser.addoption(
        "--runslow", action="store_true", default=False, help="run slow tests"
    )
    parser.addoption(
        "--stress", action="store_true", default=False, help="run stress tests"
    )
    parser.addoption(
        "--flaky", action="store_true", default=False, help="run flaky tests"
    )
    parser.addoption(
        "--deployment-mode",
        action="store",
        default="single",
        choices=["single", "cluster"],
        help="default deployment mode for tests",
    )


@pytest.hookimpl(tryfirst=True)
def pytest_sessionstart(session):
    """Set up test session with isolated directories and register cleanup."""
    logger.debug("Starting pytest plugin setup")
    session_id = set_test_session_id()
    logger.info("Test session started with ID: %s", session_id)

    # Register cleanup handlers for both normal and abnormal exits
    atexit.register(_emergency_cleanup)

    # Install signal handlers for Ctrl+C and SIGTERM to ensure cleanup
    def _signal_handler(signum, frame):
        """Handle interrupt signals by performing emergency cleanup."""
        signal_name = (
            signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
        )
        logger.warning(f"Received {signal_name}, performing emergency cleanup...")
        _emergency_cleanup()
        sys.exit(128 + signum)  # Standard exit code for signal termination

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)
    from ..core.config import get_config as get_framework_config
    from ..core.types import DeploymentMode as DepMode

    framework_config = get_framework_config()
    deployment_mode = framework_config.deployment_mode
    logger.info("Starting %s deployment for test session...", deployment_mode.value)
    try:
        if deployment_mode == DepMode.CLUSTER:
            _plugin._get_or_create_cluster()
            logger.info("Cluster deployment ready for tests")
        else:
            _plugin._get_or_create_single_server()
            logger.info("Single server deployment ready for tests")
    except (
        OSError,
        ProcessLookupError,
        RuntimeError,
        ImportError,
        AttributeError,
    ) as e:
        logger.error("Failed to start %s deployment: %s", deployment_mode.value, e)
        raise
    if not framework_config.compact_mode:
        reporter = get_armadillo_reporter()
        reporter.pytest_sessionstart(session)
        # Set the actual test start time AFTER server deployment is complete
        reporter.session_start_time = time.time()


def _is_verbose_output_enabled():
    """Check if verbose output is enabled (default) or compact mode is requested."""
    from ..core.config import get_config as get_framework_config

    framework_config = get_framework_config()
    return not framework_config.compact_mode


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    """Clean up all resources at the end of test session."""
    logger.debug("Starting pytest plugin cleanup")

    # Capture the test end time BEFORE server shutdown begins
    if _is_verbose_output_enabled():
        reporter = get_armadillo_reporter()
        reporter.session_finish_time = time.time()
        # Print the final summary immediately, before any server cleanup
        reporter.print_final_summary()
        reporter.pytest_sessionfinish(session, exitstatus)

    try:
        _cleanup_all_deployments()
        _cleanup_all_processes()
        cleanup_work_dir()
        clear_test_session()
        logger.info("Armadillo pytest plugin cleanup completed")
    except (OSError, ProcessLookupError, RuntimeError, AttributeError) as e:
        logger.error("Error during pytest plugin cleanup: %s", e)
    finally:
        try:
            stop_watchdog()
        except (OSError, ProcessLookupError, RuntimeError, AttributeError) as e:
            logger.debug("Error stopping watchdog: %s", e)


def pytest_runtest_setup(item):
    """Handle test setup start."""
    if _is_verbose_output_enabled():
        reporter = get_armadillo_reporter()
        reporter.pytest_runtest_setup(item)


def pytest_runtest_call(item):
    """Handle test call start."""
    if _is_verbose_output_enabled():
        reporter = get_armadillo_reporter()
        reporter.pytest_runtest_call(item)


def pytest_runtest_teardown(item, nextitem):
    """Handle test teardown start."""
    if _is_verbose_output_enabled():
        reporter = get_armadillo_reporter()
        reporter.pytest_runtest_teardown(item)


def pytest_runtest_logreport(report):
    """Handle test report."""
    if _is_verbose_output_enabled():
        reporter = get_armadillo_reporter()
        reporter.pytest_runtest_logreport(report)


def pytest_runtest_logstart(nodeid, location):
    """Override pytest's default test file output to suppress filename printing."""
    if _is_verbose_output_enabled():
        # Call our reporter but suppress pytest's default filename output
        reporter = get_armadillo_reporter()
        reporter.pytest_runtest_logstart(nodeid, location)
        # Return empty string to suppress pytest's default output
        return ""
    return None


def pytest_report_teststatus(report, config):
    """Override test status reporting to suppress pytest's progress dots and status."""
    if _is_verbose_output_enabled():
        if report.when == "call":
            if report.passed:
                return ("passed", "", "")
            elif report.failed:
                return ("failed", "", "")
            elif report.skipped:
                return ("skipped", "", "")
        return ("", "", "")
    return None


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Override terminal summary - print our summary AFTER all cleanup is complete."""
    if _is_verbose_output_enabled():
        reporter = get_armadillo_reporter()
        if not reporter.summary_printed:
            reporter.print_final_summary()
            reporter.summary_printed = True


def _cleanup_all_deployments():
    """Emergency cleanup of all tracked deployments with bulletproof shutdown."""
    if hasattr(_plugin, "_session_deployments"):
        deployments = list(_plugin._session_deployments.items())
        if deployments:
            logger.warning("Emergency cleanup of %s deployments", len(deployments))
            for deployment_id, manager in deployments:
                try:
                    logger.info("Emergency shutdown of deployment: %s", deployment_id)
                    manager.shutdown_deployment(timeout=15.0)
                    logger.debug("Deployment %s shutdown completed", deployment_id)
                except (OSError, ProcessLookupError, RuntimeError, AttributeError) as e:
                    logger.error(
                        "Failed emergency cleanup of deployment %s: %s",
                        deployment_id,
                        e,
                    )
                    try:
                        logger.warning(
                            "Attempting direct process cleanup for failed deployment %s",
                            deployment_id,
                        )
                        # Try to get servers from registry (new architecture) or state (old architecture)
                        servers = {}
                        if (
                            hasattr(manager, "_server_registry")
                            and manager._server_registry
                        ):
                            servers = manager._server_registry.get_all_servers()
                        elif hasattr(manager, "state") and hasattr(
                            manager.state, "servers"
                        ):
                            servers = manager.state.servers
                        elif hasattr(manager, "_servers"):
                            servers = manager._servers

                        if servers:
                            for server_id, server in servers.items():
                                try:
                                    if (
                                        hasattr(server, "_process_info")
                                        and server._process_info
                                    ):
                                        from ..core.process import _process_supervisor

                                        _process_supervisor.stop(
                                            server_id, graceful=False, timeout=5.0
                                        )
                                        logger.debug(
                                            "Force killed server %s", server_id
                                        )
                                except (OSError, ProcessLookupError) as server_e:
                                    logger.error(
                                        "Failed to force kill server %s: %s",
                                        server_id,
                                        server_e,
                                    )
                    except (OSError, ProcessLookupError, AttributeError) as force_e:
                        logger.error(
                            "Failed direct process cleanup for deployment %s: %s",
                            deployment_id,
                            force_e,
                        )
        _plugin._session_deployments.clear()
        _plugin._session_orchestrators.clear()
        logger.info("Emergency deployment cleanup completed")


def _cleanup_all_processes():
    """Emergency cleanup of all supervised processes with bulletproof termination."""
    try:
        from ..core.process import _process_supervisor

        if hasattr(_process_supervisor, "_processes"):
            process_ids = list(_process_supervisor._processes.keys())
            if process_ids:
                logger.warning(
                    "Emergency cleanup of %s processes: %s",
                    len(process_ids),
                    process_ids,
                )
                logger.info(
                    "Phase 1: Attempting graceful shutdown (SIGTERM, 3s timeout)"
                )
                graceful_failed = []
                for process_id in process_ids:
                    try:
                        _process_supervisor.stop(process_id, graceful=True, timeout=3.0)
                        logger.debug("Process %s terminated gracefully", process_id)
                    except (OSError, ProcessLookupError) as e:
                        logger.warning(
                            "Graceful termination failed for %s: %s", process_id, e
                        )
                        graceful_failed.append(process_id)
                if graceful_failed:
                    logger.warning(
                        "Phase 2: Force killing %s stubborn processes: %s",
                        len(graceful_failed),
                        graceful_failed,
                    )
                    for process_id in graceful_failed:
                        try:
                            _process_supervisor.stop(
                                process_id, graceful=False, timeout=2.0
                            )
                            logger.debug("Process %s force killed", process_id)
                        except (OSError, ProcessLookupError) as e:
                            logger.error(
                                "CRITICAL: Failed to force kill process %s: %s",
                                process_id,
                                e,
                            )
                logger.info("Emergency process cleanup completed")
    except (OSError, ProcessLookupError, AttributeError, RuntimeError) as e:
        logger.error("Error during emergency process cleanup: %s", e)
        logger.error("Stack trace: %s", traceback.format_exc())


def _emergency_cleanup():
    """Emergency cleanup function registered with atexit."""
    logger.warning("Emergency cleanup triggered via atexit")
    try:
        _cleanup_all_deployments()
        _cleanup_all_processes()
        try:
            from ..core.process import kill_all_supervised_processes

            kill_all_supervised_processes()
        except (OSError, ProcessLookupError, AttributeError, RuntimeError) as nuclear_e:
            logger.error("Nuclear cleanup failed: %s", nuclear_e)
    except (OSError, ProcessLookupError, AttributeError, RuntimeError) as e:
        logger.error("Error in emergency cleanup: %s", e)
        logger.error("Emergency cleanup stack trace: %s", traceback.format_exc())
