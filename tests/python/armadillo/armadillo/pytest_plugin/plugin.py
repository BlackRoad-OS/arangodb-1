"""Main pytest plugin for Armadillo framework integration."""

import atexit
import logging
import signal
import time
import traceback
from pathlib import Path
from typing import Optional, Dict

import pytest
from ..core.config import get_config
from ..core.config_initializer import initialize_config
from ..core.context import ApplicationContext
from ..core.log import (
    configure_logging,
    add_file_logging,
    get_logger,
    log_test_event,
    set_log_context,
    clear_log_context,
)
from ..core.time import set_global_deadline, stop_watchdog
from ..core.types import (
    ServerRole,
    DeploymentMode,
    ClusterConfig,
    ExecutionOutcome,
    ArmadilloConfig,
    ServerHealthInfo,
)
from ..core.value_objects import DeploymentId
from ..core.process import has_any_crash, get_crash_state, clear_crash_state
from ..core.errors import ResultProcessingError
from ..instances.manager import InstanceManager
from .reporter import get_armadillo_reporter
from ..utils.crypto import random_id

logger = get_logger(__name__)

# Global flags to track if we should abort remaining tests
_ABORT_REMAINING_TESTS = False
_CRASH_DETECTED_DURING_TEST = None  # Store nodeid of test where crash was detected
_TIMEOUT_DETECTED_DURING_TEST = None  # Store nodeid of test where timeout was detected


class ArmadilloPlugin:
    """Main pytest plugin for Armadillo framework."""

    def __init__(self) -> None:
        self._package_deployments: Dict[DeploymentId, InstanceManager] = {}
        self._server_health: Dict[DeploymentId, ServerHealthInfo] = (
            {}
        )  # deployment_id -> health info
        self._armadillo_config: Optional[ArmadilloConfig] = None
        self._deployment_failed: bool = False
        self._deployment_failure_reason: Optional[str] = None
        self._session_app_context: Optional[ApplicationContext] = (
            None  # Shared context for all package deployments
        )

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
        deployments_to_clean = list(self._package_deployments.items())
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
        self._package_deployments.clear()
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
        global _ABORT_REMAINING_TESTS, _CRASH_DETECTED_DURING_TEST, _TIMEOUT_DETECTED_DURING_TEST
        logger.debug("ArmadilloPlugin: Session start")
        # Config already loaded by CLI and pytest_configure
        # Don't call load_config() again to avoid duplicate build detection
        configure_logging()
        # Note: Session-level directory isolation not currently enabled
        # (would require ApplicationContext integration in pytest fixtures)
        # Clear any crash/timeout state from previous runs
        _ABORT_REMAINING_TESTS = False
        _CRASH_DETECTED_DURING_TEST = None
        _TIMEOUT_DETECTED_DURING_TEST = None
        clear_crash_state()

    def pytest_sessionfinish(self, _session: pytest.Session, exitstatus: int) -> None:
        """Called at the end of the pytest session."""
        logger.debug("ArmadilloPlugin: Session finish with exit status %s", exitstatus)
        for deployment_id, manager in list(self._package_deployments.items()):
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


def pytest_fixture_setup(_fixturedef, _request):
    """Automatic fixture setup based on markers."""
    # Reserved for future automatic fixture setup based on markers


def pytest_collection_modifyitems(_session, _config, items):
    """Modify test collection based on markers and configuration."""
    # Validate package structure - all tests must be in a package (directory with conftest.py)
    for item in items:
        # Check if test uses deployment fixtures
        uses_deployment_fixtures = any(
            fixture in ["adb", "base_url", "_package_deployment"]
            for fixture in getattr(item, "fixturenames", [])
        )

        if uses_deployment_fixtures:
            test_path = Path(item.fspath)
            parent_dir = test_path.parent

            # Check if parent directory has a conftest.py (i.e., it's a package)
            conftest_path = parent_dir / "conftest.py"

            if not conftest_path.exists():
                pytest.fail(
                    f"Test {item.nodeid} uses deployment fixtures but is not in a package.\n"
                    f"All tests using deployment fixtures must be organized in packages (directories with conftest.py).\n"
                    f"Please create {conftest_path} in the test directory.",
                    pytrace=False,
                )

            # Check for nested packages (parent packages above this one)
            # This creates separate deployments which may be intentional (isolation) or accidental (cost)
            current = parent_dir.parent
            nested_packages = []
            # Walk up the directory tree looking for additional conftest.py files
            while current != current.parent:  # Stop at filesystem root
                parent_conftest = current / "conftest.py"
                if parent_conftest.exists():
                    nested_packages.append(str(current.relative_to(Path.cwd())))
                current = current.parent

            if nested_packages:
                logger.warning(
                    "Test package %s is nested within parent package(s): %s. "
                    "Each package gets its own deployment (this may be intentional for isolation).",
                    parent_dir.name,
                    ", ".join(nested_packages),
                )

        # Add markers based on test names
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
    def _signal_handler(signum, _frame):
        """Handle interrupt signals by performing emergency cleanup."""
        signal_name = (
            signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
        )
        logger.warning("Received %s, performing emergency cleanup...", signal_name)

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
                if not _process_supervisor._processes:
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
    from ..core.context import ApplicationContext

    framework_config = get_framework_config()

    # Create shared ApplicationContext for the entire pytest session
    # This ensures all deployments share the same context (port allocator, filesystem, etc.)
    session_id = random_id(8)
    _plugin._session_app_context = ApplicationContext.create(framework_config)
    _plugin._session_app_context.filesystem.set_test_session_id(session_id)

    # Note: With package-scoped fixtures, deployments are created lazily per-package,
    # not at session start. This allows each test package to have its own deployment.
    deployment_mode = framework_config.deployment_mode
    logger.info(
        "Session initialized for %s deployment mode (deployments will be created per-package)",
        deployment_mode.value,
    )

    # Print test artifacts directory (clean access via shared context)
    from ..utils.output import print_status

    artifacts_dir = _plugin._session_app_context.filesystem.work_dir()
    print_status(f"📁 Test artifacts: {artifacts_dir}")
    logger.info("Test artifacts directory: %s", artifacts_dir)

    # Enable detailed file logging now that we have a temp directory
    # Console stays at INFO/WARNING level, but file captures DEBUG for debugging
    framework_log_file = artifacts_dir / "armadillo.log"
    add_file_logging(framework_log_file, level="DEBUG")
    logger.info("Framework debug logging enabled: %s", framework_log_file)

    if not framework_config.compact_mode:
        # Pass result collector from context to reporter
        reporter = get_armadillo_reporter(
            result_collector=_plugin._session_app_context.result_collector
        )
        reporter.pytest_sessionstart(session)
        # Set the actual test start time AFTER server deployment is complete
        reporter.session_start_time = time.time()


def _is_compact_mode_enabled():
    """Check if compact test output mode is enabled."""
    from ..core.config import get_config as get_framework_config

    framework_config = get_framework_config()
    return framework_config.compact_mode


def _cleanup_temp_dir_if_needed(_session, exitstatus):
    """Clean up session work directory based on test results and configuration.

    Cleanup logic:
    - On failure (exitstatus != 0): always keep work_dir (for debugging)
    - On success with --keep-temp-dir: keep work_dir
    - On success without flag: cleanup session work_dir

    Note: This cleans up the session-specific work directory (e.g., /tmp/armadillo/work/session_XXX),
    not the entire temp_dir, to avoid interfering with other concurrent test sessions.
    """
    import shutil
    import os
    from ..utils.output import print_status

    try:
        # Get the session work directory from the plugin's app context
        # Note: hasattr check is legitimate here - _session_app_context is created
        # in pytest_sessionstart hook, so it may not exist during early cleanup
        if (
            not hasattr(_plugin, "_session_app_context")
            or _plugin._session_app_context is None
        ):
            logger.debug("No session app context - skipping temp cleanup")
            return

        session_work_dir = _plugin._session_app_context.filesystem.work_dir()
        config = _plugin._session_app_context.config

        # Check if tests were successful
        tests_passed = exitstatus == 0

        # Check if keep_temp_dir is set (either from CLI or environment)
        keep_temp_dir = (
            config.keep_temp_dir or os.getenv("ARMADILLO_KEEP_TEMP_DIR") == "1"
        )

        # Determine if we should cleanup
        should_cleanup = tests_passed and not keep_temp_dir

        if should_cleanup and session_work_dir and session_work_dir.exists():
            # Use dim/gray for cleanup (less prominent)
            print_status(
                f"\033[2m🧹 Cleaning up test artifacts: {session_work_dir}\033[0m"
            )
            logger.info("Cleaning up session work directory: %s", session_work_dir)
            try:
                shutil.rmtree(session_work_dir)
                logger.info("Session work directory cleaned up successfully")
            except (OSError, PermissionError) as e:
                logger.warning(
                    "Failed to clean up session work directory %s: %s",
                    session_work_dir,
                    e,
                )
                print_status(f"\033[91m⚠️  Failed to clean up: {e}\033[0m")
        elif tests_passed and keep_temp_dir:
            # Use yellow for explicit preservation (user requested)
            print_status(
                f"\033[93m📦 Preserving test artifacts: {session_work_dir}\033[0m"
            )
            logger.info("Preserving session work directory at: %s", session_work_dir)
        elif not tests_passed:
            # Use yellow for preservation on failure (important for debugging)
            print_status(
                f"\033[93m📦 Preserving test artifacts for debugging: {session_work_dir}\033[0m"
            )
            logger.info(
                "Tests failed - preserving session work directory for debugging at: %s",
                session_work_dir,
            )

    except Exception as e:
        logger.error("Error in session work directory cleanup: %s", e, exc_info=True)


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    """Clean up all resources at the end of test session."""
    logger.debug("Starting pytest plugin cleanup")

    # If deployment failed, set exit status to failure
    if _plugin._deployment_failed:
        logger.error("Setting exit status to 1 due to deployment failure")
        session.exitstatus = 1

    # Check for server health issues (e.g., sanitizer failures)
    if _plugin._server_health:
        logger.error(
            "Server health issues detected in %d deployment(s)",
            len(_plugin._server_health),
        )
        for deployment_id, health_info in _plugin._server_health.items():
            logger.error(
                "Deployment %s: %s", deployment_id, health_info.get_failure_summary()
            )
        logger.error("Setting exit status to 1 due to server health issues")
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
            # Determine output directory (default to test-results if not set)
            output_dir = Path("./test-results")

            # Export results (JSON by default, JUnit is handled by pytest's --junitxml)
            # Include server health info for post-test validation reporting
            reporter.export_results(
                output_dir, formats=["json"], server_health=_plugin._server_health
            )
        except (ResultProcessingError, OSError, IOError) as e:
            logger.error("Failed to export test results: %s", e, exc_info=True)

    try:
        logger.debug("Starting pytest session cleanup")
        _cleanup_all_deployments(emergency=False)
        _cleanup_all_processes(emergency=False)
        logger.debug("Armadillo pytest plugin cleanup completed")

        # Cleanup session work directory AFTER servers are shut down
        # Only runs if cleanup was successful (we're still in try block)
        _cleanup_temp_dir_if_needed(session, exitstatus)
    except (OSError, ProcessLookupError, RuntimeError, AttributeError) as e:
        logger.error("Error during pytest plugin cleanup: %s", e)
    finally:
        try:
            stop_watchdog()
        except (OSError, ProcessLookupError, RuntimeError, AttributeError) as e:
            logger.debug("Error stopping watchdog: %s", e)


def pytest_runtest_setup(item):
    """Handle test setup - check if we should skip due to previous crash, timeout, or deployment failure."""
    # If deployment failed, skip all tests
    if _plugin._deployment_failed:
        pytest.skip(
            f"Test skipped due to deployment failure: {_plugin._deployment_failure_reason}"
        )

    # If a timeout was detected in a previous test, skip all remaining tests
    # (timeout means system is in unknown state, similar to crash)
    if (
        _ABORT_REMAINING_TESTS
        and _TIMEOUT_DETECTED_DURING_TEST
        and _TIMEOUT_DETECTED_DURING_TEST != item.nodeid
    ):
        pytest.skip(
            f"Skipping test due to timeout in previous test: {_TIMEOUT_DETECTED_DURING_TEST}\n"
            f"System may be in unknown state after timeout."
        )

    # If a crash was detected in a previous test, skip all remaining tests
    if (
        _ABORT_REMAINING_TESTS
        and _CRASH_DETECTED_DURING_TEST
        and _CRASH_DETECTED_DURING_TEST != item.nodeid
    ):
        pytest.skip(
            f"Skipping test due to server crash in previous test: {_CRASH_DETECTED_DURING_TEST}"
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


def pytest_runtest_teardown(item, _nextitem):
    """Handle test teardown start."""
    if not _is_compact_mode_enabled():
        reporter = get_armadillo_reporter()
        reporter.pytest_runtest_teardown(item)


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    """Hook to modify test reports and detect crashes/timeouts."""
    global _ABORT_REMAINING_TESTS, _CRASH_DETECTED_DURING_TEST, _TIMEOUT_DETECTED_DURING_TEST

    # Let pytest create the report first
    outcome = yield
    report = outcome.get_result()

    # Check for timeout during test execution
    # We use pytest-timeout for per-test timeouts, but it only aborts the current
    # test and continues with remaining tests. We need to abort ALL remaining tests
    # because after forcefully killing a test, the database state is unknown (similar
    # to a server crash). pytest-timeout doesn't provide a hook API for this, so we
    # detect its failure by checking the exception message.
    if call.when == "call" and call.excinfo is not None:
        exc_type = call.excinfo.type
        exc_typename = exc_type.__name__ if exc_type else ""

        # pytest-timeout calls pytest.fail() with message: "Timeout (>Xs) from pytest-timeout."
        # We detect this by checking for the characteristic message prefix
        is_timeout = exc_typename == "Failed" and "from pytest-timeout" in str(
            call.excinfo.value
        )

        if is_timeout:
            _TIMEOUT_DETECTED_DURING_TEST = item.nodeid
            _ABORT_REMAINING_TESTS = True

            timeout_message = (
                f"Test timed out and was terminated.\n\n"
                f"⚠️  WARNING: System may be in unknown state after timeout.\n"
                f"   Aborting remaining tests to prevent unreliable results.\n\n"
                f"   This is similar to a server crash - we cannot trust the state\n"
                f"   of the database after forcefully killing a running test.\n\n"
                f"Original timeout error:\n{call.excinfo.exconly()}"
            )

            # Update the report with clear timeout message
            report.longrepr = timeout_message
            report.outcome = "failed"

            logger.error(
                "Test %s timed out - aborting remaining tests to prevent unreliable results",
                item.nodeid,
            )

            # Record as timeout in the result collector
            if not _is_compact_mode_enabled():
                reporter = get_armadillo_reporter()
                reporter.result_collector.record_test_result(
                    nodeid=item.nodeid,
                    outcome=ExecutionOutcome.TIMEOUT,
                    duration=getattr(report, "duration", 0.0),
                    details=timeout_message,
                    crash_info=None,
                )

    # Check for crashes after the test phase completes
    if call.when == "call" and has_any_crash():
        crash_states = get_crash_state()

        # Mark this test as failed due to crash
        report.outcome = "failed"
        _CRASH_DETECTED_DURING_TEST = item.nodeid
        _ABORT_REMAINING_TESTS = True

        # Build comprehensive crash message
        crash_messages = []
        for server_id, crash_info in crash_states.items():
            exit_code = crash_info.exit_code
            signal_num = crash_info.signal
            stderr = crash_info.stderr or ""

            msg = f"Server {server_id} crashed during test execution"
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


def pytest_report_teststatus(report, _config):
    """Override test status reporting to suppress pytest's progress dots and status."""
    if not _is_compact_mode_enabled():
        if report.when == "call":
            if report.passed:
                return ("passed", "", "")
            if report.failed:
                return ("failed", "", "")
            if report.skipped:
                return ("skipped", "", "")
        return ("", "", "")
    return None


def pytest_terminal_summary(_terminalreporter, _exitstatus, _config):
    """Override terminal summary - print our summary AFTER all cleanup is complete."""
    if not _is_compact_mode_enabled():
        reporter = get_armadillo_reporter()
        if not reporter.summary_printed:
            reporter.print_final_summary()
            reporter.summary_printed = True


def _cleanup_all_deployments(emergency=True):
    """Cleanup all tracked deployments with bulletproof shutdown."""
    deployments = list(_plugin._package_deployments.items())
    if deployments:
        logger.debug(
            "_cleanup_all_deployments: found %d deployments, emergency=%s",
            len(deployments),
            emergency,
        )
        if emergency:
            logger.warning("Emergency cleanup of %s deployments", len(deployments))
        for deployment_id, manager in deployments:
            try:
                if emergency:
                    logger.info("Emergency shutdown of deployment: %s", deployment_id)
                manager.shutdown_deployment(timeout=15.0)
                logger.debug("Deployment %s shutdown completed", deployment_id)
                # Always capture health, even in emergency cleanup
                _capture_deployment_health(manager, deployment_id)
            except (OSError, ProcessLookupError, RuntimeError, AttributeError) as e:
                logger.error(
                    "Failed emergency cleanup of deployment %s: %s",
                    deployment_id,
                    e,
                )
                # Even if shutdown failed, try to capture health
                try:
                    _capture_deployment_health(manager, deployment_id)
                except Exception as health_err:
                    logger.debug(
                        "Could not capture health for %s: %s", deployment_id, health_err
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
        _plugin._package_deployments.clear()
        if emergency:
            logger.info("Emergency deployment cleanup completed")


def _cleanup_all_processes(emergency=True):
    """Cleanup all supervised processes with bulletproof termination."""
    try:
        logger.info("Starting _cleanup_all_processes")
        from ..core.process import _process_supervisor

        server_ids = list(_process_supervisor._processes.keys())
        if server_ids:
            logger.info(
                "Found %d processes to cleanup: %s", len(server_ids), server_ids
            )
            if server_ids:
                if emergency:
                    logger.warning(
                        "Emergency cleanup of %s processes: %s",
                        len(server_ids),
                        server_ids,
                    )
                logger.info(
                    "Phase 1: Attempting graceful shutdown (SIGTERM, 3s timeout)"
                )
                graceful_failed = []
                for server_id in server_ids:
                    try:
                        # Check if process is already dead before trying to stop it
                        if server_id in _process_supervisor._processes:
                            process = _process_supervisor._processes[server_id]
                            if process.poll() is not None:
                                logger.debug(
                                    "Process %s already dead (exit code: %s), skipping",
                                    server_id,
                                    process.returncode,
                                )
                                # Remove it from tracking since it's already dead
                                _process_supervisor._cleanup_process(server_id)
                                continue

                        logger.debug("Sending SIGTERM to process group %s", server_id)
                        _process_supervisor.stop(server_id, graceful=True, timeout=3.0)
                        logger.debug("Process %s terminated gracefully", server_id)
                    except (OSError, ProcessLookupError) as e:
                        logger.warning(
                            "Graceful termination failed for %s: %s", server_id, e
                        )
                        graceful_failed.append(server_id)
                    except Exception as e:
                        # Emergency cleanup must continue even on unexpected errors
                        logger.error(
                            "Unexpected error during graceful termination of %s: %s",
                            server_id,
                            e,
                            exc_info=True,
                        )
                        graceful_failed.append(server_id)
                if graceful_failed:
                    logger.warning(
                        "Phase 2: Force killing %s stubborn processes: %s",
                        len(graceful_failed),
                        graceful_failed,
                    )
                    for server_id in graceful_failed:
                        try:
                            # Check if process is already dead before trying to force kill it
                            if server_id in _process_supervisor._processes:
                                process = _process_supervisor._processes[server_id]
                                if process.poll() is not None:
                                    logger.debug(
                                        "Process %s already dead (exit code: %s), skipping force kill",
                                        server_id,
                                        process.returncode,
                                    )
                                    # Remove it from tracking since it's already dead
                                    _process_supervisor._cleanup_process(server_id)
                                    continue

                            logger.debug(
                                "Sending SIGKILL to process group %s", server_id
                            )
                            _process_supervisor.stop(
                                server_id, graceful=False, timeout=2.0
                            )
                            logger.debug("Process %s force killed", server_id)
                        except (OSError, ProcessLookupError) as e:
                            logger.error(
                                "CRITICAL: Failed to force kill process %s: %s",
                                server_id,
                                e,
                            )
                        except Exception as e:
                            # Emergency cleanup must continue even on unexpected errors
                            logger.error(
                                "CRITICAL: Unexpected error force killing process %s: %s",
                                server_id,
                                e,
                                exc_info=True,
                            )
                logger.info("Emergency process cleanup completed")

                # Final verification: check if any processes are still running
                try:
                    remaining_processes = []
                    for server_id in server_ids:
                        if server_id in _process_supervisor._processes:
                            process = _process_supervisor._processes[server_id]
                            try:
                                # Check if process is still alive
                                if process.poll() is None:  # None means still running
                                    remaining_processes.append(server_id)
                            except (OSError, ProcessLookupError, ValueError):
                                # Process might be in inconsistent state - treat as potentially alive
                                remaining_processes.append(server_id)

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
                    logger.error(
                        "Error during final process verification: %s", e, exc_info=True
                    )
            else:
                logger.debug("No supervised processes to cleanup")
        else:
            logger.debug("Process supervisor not available")
    except (OSError, ProcessLookupError, AttributeError, RuntimeError) as e:
        logger.error("Error during emergency process cleanup: %s", e)
        logger.error("Stack trace: %s", traceback.format_exc())
    except Exception as e:
        # Emergency cleanup is last resort - must complete even on unexpected errors
        logger.error(
            "Unexpected error during emergency process cleanup: %s", e, exc_info=True
        )
        logger.error("Stack trace: %s", traceback.format_exc())


def _emergency_cleanup():
    """Emergency cleanup function registered with atexit."""
    # Check if there's actually anything to clean up
    has_deployments = bool(_plugin._package_deployments)

    try:
        from ..core.process import _process_supervisor

        has_processes = bool(_process_supervisor._processes)
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

            if _process_supervisor._processes:
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


def _capture_deployment_health(manager: InstanceManager, deployment_id: str) -> None:
    """Capture and store server health after deployment shutdown.

    Args:
        manager: The instance manager that was shut down
        deployment_id: Identifier for this deployment (string)
    """
    health = manager.get_server_health()
    if health.has_issues():
        # Convert string to DeploymentId value object
        _plugin._server_health[DeploymentId(deployment_id)] = health
        logger.warning(
            "Server health issues detected in %s: %s",
            deployment_id,
            health.get_failure_summary(),
        )


def create_package_deployment(package_name: str):
    """Helper function to create a deployment for a test package.

    This is intended to be called from package conftest.py files to create
    package-scoped deployments. Plugin fixtures don't scope per-package correctly,
    so each package must define its own fixture that calls this helper.

    Example usage in tests/mypackage/conftest.py:
        @pytest.fixture(scope="package")
        def _package_deployment(request):
            from pathlib import Path
            from armadillo.pytest_plugin.plugin import create_package_deployment
            package_name = Path(__file__).parent.name
            yield from create_package_deployment(package_name)

    Args:
        package_name: Name of the test package (directory name)

    Yields:
        ServerInstance: The deployment's server/coordinator instance
    """
    from ..instances.manager import get_instance_manager

    framework_config = get_config()
    deployment_mode = framework_config.deployment_mode

    if deployment_mode == DeploymentMode.CLUSTER:
        # Create cluster deployment for this package
        deployment_id = DeploymentId(f"cluster_{package_name}_{random_id(6)}")
        manager = get_instance_manager(deployment_id, _plugin._session_app_context)
        try:
            logger.info(
                "Starting package cluster deployment %s for %s",
                deployment_id,
                package_name,
            )
            cluster_config = ClusterConfig(agents=3, dbservers=2, coordinators=1)
            plan = manager.create_deployment_plan(cluster_config)
            manager.deploy_servers(plan, timeout=300.0)
            logger.info("Package cluster deployment %s ready", deployment_id)
            _plugin._package_deployments[deployment_id] = manager

            coordinators = manager.get_servers_by_role(ServerRole.COORDINATOR)
            if not coordinators:
                raise RuntimeError("No coordinators available in cluster")
            yield coordinators[0]
        finally:
            logger.info("Stopping package cluster deployment %s", deployment_id)
            try:
                manager.shutdown_deployment(timeout=120.0)
                # Capture server health for post-test validation
                _capture_deployment_health(manager, str(deployment_id))
            except (OSError, ProcessLookupError, RuntimeError, AttributeError) as e:
                logger.error(
                    "Error stopping cluster deployment %s: %s", deployment_id, e
                )
            finally:
                _plugin._package_deployments.pop(deployment_id, None)
    else:
        # Single server mode
        deployment_id = DeploymentId(f"single_{package_name}_{random_id(6)}")
        manager = get_instance_manager(deployment_id, _plugin._session_app_context)
        try:
            logger.info("Starting package single server for %s", package_name)
            plan = manager.create_single_server_plan()
            manager.deploy_servers(plan, timeout=60.0)
            _plugin._package_deployments[deployment_id] = manager

            servers = manager.get_all_servers()
            if not servers:
                raise RuntimeError(f"No servers deployed for package {package_name}")
            server = next(iter(servers.values()))
            logger.info(
                "Package single server ready at %s (package: %s)",
                server.endpoint,
                package_name,
            )
            yield server
        finally:
            logger.info("Stopping package single server for %s", package_name)
            try:
                manager.shutdown_deployment(timeout=30.0)
                # Capture server health for post-test validation
                _capture_deployment_health(manager, str(deployment_id))
            except (OSError, ProcessLookupError, RuntimeError, AttributeError) as e:
                logger.error("Error stopping package server: %s", e)
            finally:
                _plugin._package_deployments.pop(deployment_id, None)
