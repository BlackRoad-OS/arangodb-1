"""Main pytest plugin for Armadillo framework integration."""

import atexit
import logging
import signal
import sys
import pytest
import time
import traceback
from typing import Generator, Optional, Dict, Any, List
from ..core.config import get_config
from ..core.config_initializer import initialize_config
from ..core.log import (
    configure_logging,
    get_logger,
    log_test_event,
    set_log_context,
    clear_log_context,
)
from ..core.time import set_global_deadline, stop_watchdog
from ..core.types import ServerRole, DeploymentMode, ClusterConfig, ExecutionOutcome
from ..core.process import has_any_crash, get_crash_state, clear_crash_state
from ..core.errors import ServerStartupError, ArmadilloError, ResultProcessingError
from ..instances.server import ArangoServer
from ..instances.manager import InstanceManager, get_instance_manager
from .reporter import get_armadillo_reporter
from ..utils.crypto import random_id

logger = get_logger(__name__)

# Global flag to track if we should abort remaining tests due to crash
_abort_remaining_tests = False
_crash_detected_during_test = None  # Store nodeid of test where crash was detected


class ArmadilloPlugin:
    """Main pytest plugin for Armadillo framework."""

    def __init__(self) -> None:
        self._session_deployments: Dict[str, InstanceManager] = {}
        self._armadillo_config: Optional[Any] = None
        self._deployment_failed: bool = False
        self._deployment_failure_reason: Optional[str] = None

    def pytest_configure(self, config: pytest.Config) -> None:
        """Configure pytest for Armadillo."""
        # In pytest subprocess, config needs to be loaded from environment variables
        # get_config() will call load_config() if not already loaded
        framework_config = get_config()

        # Initialize config (side effects: create dirs, detect builds if needed)
        framework_config = initialize_config(framework_config)

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
            level=framework_config.log_level,
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
        self._session_deployments.clear()
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
        global _abort_remaining_tests, _crash_detected_during_test
        logger.debug("ArmadilloPlugin: Session start")
        # Config already loaded by CLI and pytest_configure
        # Don't call load_config() again to avoid duplicate build detection
        configure_logging()
        # Note: Session-level directory isolation not currently enabled
        # (would require ApplicationContext integration in pytest fixtures)
        # Clear any crash state from previous runs
        _abort_remaining_tests = False
        _crash_detected_during_test = None
        clear_crash_state()

    def pytest_sessionfinish(self, _session: pytest.Session, exitstatus: int) -> None:
        """Called at the end of the pytest session."""
        logger.debug("ArmadilloPlugin: Session finish with exit status %s", exitstatus)
        for deployment_id, manager in list(self._session_deployments.items()):
            try:
                logger.debug("Stopping session deployment %s", deployment_id)
                manager.shutdown_deployment(timeout=60.0)
            except (OSError, ProcessLookupError, RuntimeError, AttributeError) as e:
                logger.error(
                    "Error stopping session deployment %s: %s", deployment_id, e
                )
        # Note: Automatic cleanup not currently enabled
        # (would require ApplicationContext integration in pytest fixtures)
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
    """Provide a single ArangoDB server for testing using unified infrastructure."""
    from ..instances.manager import get_instance_manager

    deployment_id = "test_single_server_session"
    manager = get_instance_manager(deployment_id)

    try:
        logger.info("Starting session single server")

        plan = manager.create_single_server_plan()
        manager.deploy_servers(plan, timeout=60.0)

        # Store manager for tracking and cleanup
        _plugin._session_deployments[deployment_id] = manager

        # Get the server instance to yield
        servers = manager.get_all_servers()
        server = next(iter(servers.values()))
        logger.info("Session single server ready at %s", server.endpoint)

        yield server
    finally:
        logger.info("Stopping session single server")
        try:
            manager.shutdown_deployment(timeout=30.0)
            logger.debug("Session single server stopped successfully")
        except (OSError, ProcessLookupError, RuntimeError, AttributeError) as e:
            logger.error("Error stopping session server: %s", e)
        finally:
            _plugin._session_deployments.pop(deployment_id, None)
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
        plan = manager.create_deployment_plan(cluster_config)

        try:
            manager.deploy_servers(plan, timeout=300.0)
            logger.info("Session cluster deployment ready")
        except ServerStartupError as e:
            # Check if any servers crashed during deployment
            crash_states = get_crash_state()
            if crash_states:
                crashed_servers = list(crash_states.keys())
                crash_details = []
                for server_id, crash_info in crash_states.items():
                    exit_code = crash_info.get("exit_code", -1)
                    signal_num = crash_info.get("signal", -1)
                    crash_details.append(
                        f"{server_id} (exit code {exit_code}, signal {signal_num})"
                    )

                # Create a cleaner error message
                error_msg = f"Cluster deployment failed due to server crashes: {', '.join(crashed_servers)}"
                logger.error(error_msg)
                for detail in crash_details:
                    logger.error("  %s", detail)
            else:
                error_msg = f"Cluster deployment failed: {str(e)}"
                logger.error(error_msg)

            # Set deployment failure flag instead of raising exception
            self._deployment_failed = True
            self._deployment_failure_reason = error_msg
            return None
        except ArmadilloError as e:
            # Framework errors during deployment - expected failure modes
            error_msg = f"Cluster deployment failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            self._deployment_failed = True
            self._deployment_failure_reason = error_msg
            return None
        except Exception as e:
            # Unexpected errors - boundary must not crash pytest
            error_msg = f"Cluster deployment failed with unexpected error: {str(e)}"
            logger.error(error_msg, exc_info=True)
            self._deployment_failed = True
            self._deployment_failure_reason = error_msg
            return None

        self._session_deployments["cluster"] = manager
    return self._session_deployments["cluster"]


def _get_or_create_single_server(self) -> ArangoServer:
    """Get or create session single server using unified infrastructure."""
    if "single" not in self._session_deployments:
        from ..instances.manager import get_instance_manager

        deployment_id = "test_single_server"
        manager = get_instance_manager(deployment_id)

        logger.info("Starting session single server")

        plan = manager.create_single_server_plan()

        try:
            manager.deploy_servers(plan, timeout=60.0)
        except ServerStartupError as e:
            # Check if server crashed during deployment
            crash_states = get_crash_state()
            if crash_states:
                crashed_servers = list(crash_states.keys())
                crash_details = []
                for server_id, crash_info in crash_states.items():
                    exit_code = crash_info.get("exit_code", -1)
                    signal_num = crash_info.get("signal", -1)
                    crash_details.append(
                        f"{server_id} (exit code {exit_code}, signal {signal_num})"
                    )

                # Create a cleaner error message
                error_msg = f"Single server deployment failed due to server crashes: {', '.join(crashed_servers)}"
                logger.error(error_msg)
                for detail in crash_details:
                    logger.error("  %s", detail)
            else:
                error_msg = f"Single server deployment failed: {str(e)}"
                logger.error(error_msg)

            # Set deployment failure flag instead of raising exception
            self._deployment_failed = True
            self._deployment_failure_reason = error_msg
            return None
        except ArmadilloError as e:
            # Framework errors during deployment - expected failure modes
            error_msg = f"Single server deployment failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            self._deployment_failed = True
            self._deployment_failure_reason = error_msg
            return None
        except Exception as e:
            # Unexpected errors - boundary must not crash pytest
            error_msg = f"Single server deployment failed with unexpected error: {str(e)}"
            logger.error(error_msg, exc_info=True)
            self._deployment_failed = True
            self._deployment_failure_reason = error_msg
            return None

        # Store manager (not individual server) for cleanup
        self._session_deployments["single"] = manager
        logger.info("Session single server ready")

    # Return the single server from the manager
    manager = self._session_deployments["single"]
    servers = manager.get_all_servers()
    if not servers:
        raise RuntimeError("Single server deployment has no servers")
    return next(iter(servers.values()))


ArmadilloPlugin._get_or_create_cluster = _get_or_create_cluster
ArmadilloPlugin._get_or_create_single_server = _get_or_create_single_server


@pytest.fixture(scope="function")
def arango_single_server_function() -> Generator[ArangoServer, None, None]:
    """Provide a function-scoped single ArangoDB server using unified infrastructure."""
    from ..instances.manager import get_instance_manager

    deployment_id = f"test_func_{random_id(8)}"
    manager = get_instance_manager(deployment_id)

    try:
        logger.info("Starting function server %s", deployment_id)

        plan = manager.create_single_server_plan()
        manager.deploy_servers(plan, timeout=30.0)

        # Get the server instance to yield
        servers = manager.get_all_servers()
        server = next(iter(servers.values()))
        logger.info("Function server %s ready at %s", deployment_id, server.endpoint)

        yield server
    finally:
        logger.info("Stopping function server %s", deployment_id)
        try:
            manager.shutdown_deployment(timeout=15.0)
        except (OSError, ProcessLookupError, RuntimeError, AttributeError) as e:
            logger.error("Error stopping function server %s: %s", deployment_id, e)


@pytest.fixture(scope="session")
def arango_cluster() -> Generator[InstanceManager, None, None]:
    """Provide a full ArangoDB cluster for testing."""
    deployment_id = f"cluster_{random_id(8)}"
    manager = get_instance_manager(deployment_id)
    try:
        logger.info("Starting session cluster deployment %s", deployment_id)
        cluster_config = ClusterConfig(agents=3, dbservers=2, coordinators=1)
        plan = manager.create_deployment_plan(cluster_config)
        manager.deploy_servers(plan, timeout=300.0)
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
        plan = manager.create_deployment_plan(cluster_config)
        manager.deploy_servers(plan, timeout=180.0)
        logger.info("Function cluster deployment %s ready", deployment_id)
        yield manager
    finally:
        logger.info("Stopping function cluster deployment %s", deployment_id)
        try:
            manager.shutdown_deployment(timeout=60.0)
        except (OSError, ProcessLookupError, RuntimeError, AttributeError) as e:
            logger.error("Error stopping function cluster %s: %s", deployment_id, e)


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
    """Set up test session and register cleanup handlers."""
    logger.debug("Starting pytest plugin setup")
    logger.info("Test session started")

    # Register cleanup handlers for both normal and abnormal exits
    atexit.register(_emergency_cleanup)

    # Install signal handlers for Ctrl+C and SIGTERM to ensure cleanup
    def _signal_handler(signum, frame):
        """Handle interrupt signals by performing emergency cleanup."""
        signal_name = (
            signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
        )
        logger.warning(f"Received {signal_name}, performing emergency cleanup...")

        # Perform cleanup and wait for it to complete
        _emergency_cleanup()

        # Give cleanup time to work (max 10 seconds)
        logger.info("Waiting for processes to terminate...")
        cleanup_timeout = 10.0
        start_time = time.time()

        # Check if processes are still running
        try:
            from ..core.process import _process_supervisor

            while (time.time() - start_time) < cleanup_timeout:
                if (
                    not hasattr(_process_supervisor, "_processes")
                    or not _process_supervisor._processes
                ):
                    logger.info("All supervised processes terminated successfully")
                    break
                time.sleep(0.5)  # Check every 500ms
            else:
                logger.warning(
                    "Cleanup timeout reached, some processes may still be running"
                )
        except Exception as e:
            # Signal handler must not crash - catch everything
            logger.error("Error during cleanup monitoring: %s", e, exc_info=True)

        # Don't call sys.exit() as it causes pytest INTERNALERROR
        # The cleanup is already working correctly
        logger.info("Emergency cleanup completed, exiting gracefully")

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


def _is_compact_mode_enabled():
    """Check if compact test output mode is enabled."""
    from ..core.config import get_config as get_framework_config

    framework_config = get_framework_config()
    return framework_config.compact_mode


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    """Clean up all resources at the end of test session."""
    logger.debug("Starting pytest plugin cleanup")

    # If deployment failed, set exit status to failure
    if _plugin._deployment_failed:
        logger.error("Setting exit status to 1 due to deployment failure")
        session.exitstatus = 1

    # Capture the test end time BEFORE server shutdown begins
    if not _is_compact_mode_enabled():
        reporter = get_armadillo_reporter()
        reporter.session_finish_time = time.time()
        # Set deployment failed flag on reporter so it shows FAILED status
        reporter.deployment_failed = _plugin._deployment_failed
        # Print the final summary immediately, before any server cleanup
        reporter.print_final_summary()
        reporter.pytest_sessionfinish(session, exitstatus)

        # Export test results
        try:
            from pathlib import Path
            from ..core.config import get_config

            config = get_config()

            # Determine output directory (default to test-results if not set)
            output_dir = Path("./test-results")

            # Export results (JSON by default, JUnit is handled by pytest's --junitxml)
            reporter.export_results(output_dir, formats=["json"])
        except (ResultProcessingError, OSError, IOError) as e:
            logger.error("Failed to export test results: %s", e, exc_info=True)

    try:
        logger.debug("Starting pytest session cleanup")
        _cleanup_all_deployments(emergency=False)
        _cleanup_all_processes(emergency=False)
        logger.debug("Armadillo pytest plugin cleanup completed")
    except (OSError, ProcessLookupError, RuntimeError, AttributeError) as e:
        logger.error("Error during pytest plugin cleanup: %s", e)
    finally:
        try:
            stop_watchdog()
        except (OSError, ProcessLookupError, RuntimeError, AttributeError) as e:
            logger.debug("Error stopping watchdog: %s", e)


def pytest_runtest_setup(item):
    """Handle test setup - check if we should skip due to previous crash or deployment failure."""
    global _abort_remaining_tests, _crash_detected_during_test

    # If deployment failed, skip all tests
    if _plugin._deployment_failed:
        pytest.skip(
            f"Test skipped due to deployment failure: {_plugin._deployment_failure_reason}"
        )

    # If a crash was detected in a previous test, skip all remaining tests
    if _abort_remaining_tests and _crash_detected_during_test != item.nodeid:
        pytest.skip(
            f"Skipping test due to server crash in previous test: {_crash_detected_during_test}"
        )

    # Handle reporter setup
    if not _is_compact_mode_enabled():
        reporter = get_armadillo_reporter()
        reporter.pytest_runtest_setup(item)


def pytest_runtest_call(item):
    """Handle test call start."""
    if not _is_compact_mode_enabled():
        reporter = get_armadillo_reporter()
        reporter.pytest_runtest_call(item)


def pytest_runtest_teardown(item, nextitem):
    """Handle test teardown start."""
    if not _is_compact_mode_enabled():
        reporter = get_armadillo_reporter()
        reporter.pytest_runtest_teardown(item)


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    """Hook to modify test reports and detect crashes."""
    global _abort_remaining_tests, _crash_detected_during_test

    # Let pytest create the report first
    outcome = yield
    report = outcome.get_result()

    # Check for crashes after the test phase completes
    if call.when == "call" and has_any_crash():
        crash_states = get_crash_state()

        # Mark this test as failed due to crash
        report.outcome = "failed"
        _crash_detected_during_test = item.nodeid
        _abort_remaining_tests = True

        # Build comprehensive crash message
        crash_messages = []
        for process_id, crash_info in crash_states.items():
            exit_code = crash_info.get("exit_code", "unknown")
            signal_num = crash_info.get("signal")
            stderr = crash_info.get("stderr", "")

            msg = f"Process {process_id} crashed during test execution"
            if signal_num:
                msg += f" (signal {signal_num})"
            msg += f" with exit code {exit_code}"
            if stderr:
                msg += f"\nStderr: {stderr}"
            crash_messages.append(msg)

        crash_message = "\n\n".join(crash_messages)

        # Update the report
        report.longrepr = crash_message
        report.outcome = "failed"

        # Store crash info in the report for result collection
        if not hasattr(report, "crash_info"):
            report.crash_info = crash_states

        logger.error(
            "Test %s failed due to server crash: %s", item.nodeid, crash_message
        )

        # Record the crash in the result collector
        if not _is_compact_mode_enabled():
            reporter = get_armadillo_reporter()
            # Force record this as a crashed test
            reporter.result_collector.record_test_result(
                nodeid=item.nodeid,
                outcome=ExecutionOutcome.CRASHED,
                duration=getattr(report, "duration", 0.0),
                details=crash_message,
                crash_info=crash_states,
            )


def pytest_runtest_logreport(report):
    """Handle test report."""
    if not _is_compact_mode_enabled():
        reporter = get_armadillo_reporter()
        reporter.pytest_runtest_logreport(report)


def pytest_runtest_logstart(nodeid, location):
    """Override pytest's default test file output to suppress filename printing."""
    if not _is_compact_mode_enabled():
        # Call our reporter but suppress pytest's default filename output
        reporter = get_armadillo_reporter()
        reporter.pytest_runtest_logstart(nodeid, location)
        # Return empty string to suppress pytest's default output
        return ""
    return None


def pytest_report_teststatus(report, config):
    """Override test status reporting to suppress pytest's progress dots and status."""
    if not _is_compact_mode_enabled():
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
    if not _is_compact_mode_enabled():
        reporter = get_armadillo_reporter()
        if not reporter.summary_printed:
            reporter.print_final_summary()
            reporter.summary_printed = True


def _cleanup_all_deployments(emergency=True):
    """Cleanup all tracked deployments with bulletproof shutdown."""
    if hasattr(_plugin, "_session_deployments"):
        deployments = list(_plugin._session_deployments.items())
        logger.debug(
            "_cleanup_all_deployments: found %d deployments, emergency=%s",
            len(deployments),
            emergency,
        )
        if deployments:
            if emergency:
                logger.warning("Emergency cleanup of %s deployments", len(deployments))
            for deployment_id, manager in deployments:
                try:
                    if emergency:
                        logger.info(
                            "Emergency shutdown of deployment: %s", deployment_id
                        )
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
                        # Try to get servers using the public API for force cleanup
                        try:
                            servers = manager.get_all_servers()
                        except (AttributeError, RuntimeError) as get_e:
                            logger.warning(
                                "Could not get servers from manager %s: %s",
                                deployment_id,
                                get_e,
                            )
                            servers = {}

                        if servers:
                            for server_id, server in servers.items():
                                try:
                                    # Use the public API to force stop the server
                                    server.stop(graceful=False, timeout=5.0)
                                    logger.debug("Force stopped server %s", server_id)
                                except (
                                    OSError,
                                    ProcessLookupError,
                                    AttributeError,
                                ) as server_e:
                                    logger.error(
                                        "Failed to force stop server %s: %s",
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
        if emergency:
            logger.info("Emergency deployment cleanup completed")


def _cleanup_all_processes(emergency=True):
    """Cleanup all supervised processes with bulletproof termination."""
    try:
        logger.info("Starting _cleanup_all_processes")
        from ..core.process import _process_supervisor

        if hasattr(_process_supervisor, "_processes"):
            process_ids = list(_process_supervisor._processes.keys())
            logger.info(
                "Found %d processes to cleanup: %s", len(process_ids), process_ids
            )
            if process_ids:
                if emergency:
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
                        # Check if process is already dead before trying to stop it
                        if process_id in _process_supervisor._processes:
                            process = _process_supervisor._processes[process_id]
                            if process.poll() is not None:
                                logger.debug(
                                    "Process %s already dead (exit code: %s), skipping",
                                    process_id,
                                    process.returncode,
                                )
                                # Remove it from tracking since it's already dead
                                _process_supervisor._cleanup_process(process_id)
                                continue

                        logger.debug("Sending SIGTERM to process group %s", process_id)
                        _process_supervisor.stop(process_id, graceful=True, timeout=3.0)
                        logger.debug("Process %s terminated gracefully", process_id)
                    except (OSError, ProcessLookupError) as e:
                        logger.warning(
                            "Graceful termination failed for %s: %s", process_id, e
                        )
                        graceful_failed.append(process_id)
                    except Exception as e:
                        # Emergency cleanup must continue even on unexpected errors
                        logger.error(
                            "Unexpected error during graceful termination of %s: %s",
                            process_id,
                            e,
                            exc_info=True,
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
                            # Check if process is already dead before trying to force kill it
                            if process_id in _process_supervisor._processes:
                                process = _process_supervisor._processes[process_id]
                                if process.poll() is not None:
                                    logger.debug(
                                        "Process %s already dead (exit code: %s), skipping force kill",
                                        process_id,
                                        process.returncode,
                                    )
                                    # Remove it from tracking since it's already dead
                                    _process_supervisor._cleanup_process(process_id)
                                    continue

                            logger.debug(
                                "Sending SIGKILL to process group %s", process_id
                            )
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
                        except Exception as e:
                            # Emergency cleanup must continue even on unexpected errors
                            logger.error(
                                "CRITICAL: Unexpected error force killing process %s: %s",
                                process_id,
                                e,
                                exc_info=True,
                            )
                logger.info("Emergency process cleanup completed")

                # Final verification: check if any processes are still running
                try:
                    remaining_processes = []
                    for process_id in process_ids:
                        if process_id in _process_supervisor._processes:
                            process = _process_supervisor._processes[process_id]
                            try:
                                # Check if process is still alive
                                if process.poll() is None:  # None means still running
                                    remaining_processes.append(process_id)
                            except (OSError, ProcessLookupError, ValueError):
                                # Process might be in inconsistent state - treat as potentially alive
                                remaining_processes.append(process_id)

                    if remaining_processes:
                        logger.error(
                            "CRITICAL: %d processes still running after cleanup: %s",
                            len(remaining_processes),
                            remaining_processes,
                        )
                    else:
                        logger.info("All processes successfully terminated")
                except Exception as e:
                    # Final verification errors should not prevent cleanup completion
                    logger.error("Error during final process verification: %s", e, exc_info=True)
            else:
                logger.debug("No supervised processes to cleanup")
        else:
            logger.debug("Process supervisor not available")
    except (OSError, ProcessLookupError, AttributeError, RuntimeError) as e:
        logger.error("Error during emergency process cleanup: %s", e)
        logger.error("Stack trace: %s", traceback.format_exc())
    except Exception as e:
        # Emergency cleanup is last resort - must complete even on unexpected errors
        logger.error("Unexpected error during emergency process cleanup: %s", e, exc_info=True)
        logger.error("Stack trace: %s", traceback.format_exc())


def _emergency_cleanup():
    """Emergency cleanup function registered with atexit."""
    # Check if there's actually anything to clean up
    has_deployments = (
        hasattr(_plugin, "_session_deployments") and _plugin._session_deployments
    )

    try:
        from ..core.process import _process_supervisor

        has_processes = (
            hasattr(_process_supervisor, "_processes")
            and _process_supervisor._processes
        )
    except (ImportError, AttributeError):
        has_processes = False

    # Only print emergency message if there's actually something left to clean up
    if has_deployments or has_processes:
        logger.warning("Emergency cleanup triggered via atexit")

    try:
        logger.info("Starting emergency cleanup...")
        logger.info(
            "has_deployments: %s, has_processes: %s", has_deployments, has_processes
        )

        try:
            _cleanup_all_deployments(emergency=True)
        except Exception as e:
            logger.error("Error during deployment cleanup: %s", e)

        try:
            _cleanup_all_processes(emergency=True)
        except Exception as e:
            logger.error("Error during process cleanup: %s", e)

        # Only use nuclear option if processes still remain after normal emergency cleanup
        try:
            from ..core.process import _process_supervisor

            if (
                hasattr(_process_supervisor, "_processes")
                and _process_supervisor._processes
            ):
                logger.warning("Some processes still running, using nuclear cleanup...")
                from ..core.process import kill_all_supervised_processes

                kill_all_supervised_processes()
            else:
                logger.info("All processes cleaned up successfully")
        except (OSError, ProcessLookupError, AttributeError, RuntimeError) as nuclear_e:
            logger.error("Nuclear cleanup failed: %s", nuclear_e)
    except (OSError, ProcessLookupError, AttributeError, RuntimeError) as e:
        logger.error("Error in emergency cleanup: %s", e)
        logger.error("Emergency cleanup stack trace: %s", traceback.format_exc())
