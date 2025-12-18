"""Main pytest plugin for Armadillo framework integration."""

import atexit
import logging
import signal
import time
import traceback
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Optional, Dict, Union

import pytest
from pytest import StashKey
from _pytest.config import Config
from _pytest.main import Session
from _pytest.nodes import Item
from _pytest.fixtures import FixtureDef
from _pytest.fixtures import FixtureRequest
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
from ..core.process import ProcessSupervisor, kill_all_supervised_processes
from ..core.errors import ResultProcessingError
from ..instances.deployment_controller import DeploymentController
from .reporter import ArmadilloReporter
from ..utils.crypto import random_id

logger = get_logger(__name__)


class PluginRegistry:
    """
    Manages global access to the ArmadilloPlugin instance for pytest hooks.

    Why this exists:
    Some pytest hooks (pytest_runtest_logreport, pytest_runtest_logstart) don't
    receive config/session parameters, so they cannot access the plugin via stash.
    This registry provides explicit, fail-loud access to the plugin for those hooks.

    Lifecycle:
    - register() called in pytest_sessionstart
    - unregister() called in pytest_sessionfinish
    - get() fails loudly if plugin not registered

    This is the standard pytest pattern for plugins that need global access.
    """

    _instance: Optional["ArmadilloPlugin"] = None
    _registered: bool = False

    @classmethod
    def register(cls, plugin: "ArmadilloPlugin") -> None:
        """Register plugin instance for global access.

        Args:
            plugin: The ArmadilloPlugin instance to register

        Raises:
            RuntimeError: If plugin already registered (prevents double-registration)
        """
        if cls._registered:
            raise RuntimeError(
                "ArmadilloPlugin already registered. "
                "This indicates pytest_sessionstart was called twice without cleanup."
            )
        cls._instance = plugin
        cls._registered = True
        logger.debug("ArmadilloPlugin registered in global registry")

    @classmethod
    def unregister(cls) -> None:
        """Unregister plugin instance.

        Called during pytest_sessionfinish to clean up global state.
        """
        cls._instance = None
        cls._registered = False
        logger.debug("ArmadilloPlugin unregistered from global registry")

    @classmethod
    def get(cls) -> "ArmadilloPlugin":
        """Get the registered plugin instance.

        Returns:
            The registered ArmadilloPlugin instance

        Raises:
            RuntimeError: If no plugin registered (fail-loud, not silent)
        """
        if not cls._registered or cls._instance is None:
            raise RuntimeError(
                "ArmadilloPlugin not available. "
                "This hook requires an active pytest session. "
                "Ensure pytest_sessionstart has been called."
            )
        return cls._instance

    @classmethod
    def is_registered(cls) -> bool:
        """Check if plugin is registered."""
        return cls._registered


@dataclass
class SessionExecutionState:
    """Encapsulates session-level execution state for test abortion logic.

    This state tracks critical failures (crashes, timeouts, deployment issues)
    that require aborting remaining tests to prevent unreliable results.

    Why abort remaining tests?
    - After a timeout: System may be in unknown state (similar to crash)
    - After a crash: Database state is corrupted and unreliable
    - These failures invalidate assumptions that subsequent tests rely on

    Black Box Design:
    - This component owns all test abortion state and logic
    - External code calls methods, doesn't manipulate state directly
    - Can be tested independently of pytest machinery
    """

    abort_remaining_tests: bool = False
    crash_detected_in_test: Optional[str] = None  # nodeid where crash occurred
    timeout_detected_in_test: Optional[str] = None  # nodeid where timeout occurred

    def should_abort_test(self, test_nodeid: str) -> tuple[bool, Optional[str]]:
        """Determine if a test should be aborted and why.

        Args:
            test_nodeid: The pytest node ID of the test being checked

        Returns:
            (should_abort, reason_message): Tuple of whether to abort and why
        """
        if not self.abort_remaining_tests:
            return False, None

        # Don't skip the test that caused the timeout/crash itself
        if (
            self.timeout_detected_in_test
            and self.timeout_detected_in_test != test_nodeid
        ):
            reason = (
                f"Skipping test due to timeout in previous test: {self.timeout_detected_in_test}\n"
                f"System may be in unknown state after timeout."
            )
            return True, reason

        if self.crash_detected_in_test and self.crash_detected_in_test != test_nodeid:
            reason = f"Skipping test due to server crash in previous test: {self.crash_detected_in_test}"
            return True, reason

        return False, None

    def record_timeout(self, test_nodeid: str) -> None:
        """Record that a timeout occurred in a test.

        Args:
            test_nodeid: The pytest node ID where the timeout occurred
        """
        self.timeout_detected_in_test = test_nodeid
        self.abort_remaining_tests = True
        logger.error(
            "Timeout recorded for test %s - aborting remaining tests", test_nodeid
        )

    def record_crash(self, test_nodeid: str) -> None:
        """Record that a crash occurred in a test.

        Args:
            test_nodeid: The pytest node ID where the crash occurred
        """
        self.crash_detected_in_test = test_nodeid
        self.abort_remaining_tests = True
        logger.error(
            "Crash recorded for test %s - aborting remaining tests", test_nodeid
        )

    def reset(self) -> None:
        """Reset state for a new test session."""
        self.abort_remaining_tests = False
        self.crash_detected_in_test = None
        self.timeout_detected_in_test = None
        logger.debug("Session execution state reset")


class ArmadilloPlugin:
    """Main pytest plugin for Armadillo framework."""

    def __init__(self) -> None:
        self._package_deployments: Dict[DeploymentId, DeploymentController] = {}
        self._server_health: Dict[DeploymentId, ServerHealthInfo] = (
            {}
        )  # deployment_id -> health info
        self._armadillo_config: Optional[ArmadilloConfig] = None
        self._deployment_failed: bool = False
        self._deployment_failure_reason: Optional[str] = None
        self._session_app_context: Optional[ApplicationContext] = (
            None  # Shared context for all package deployments
        )
        self.reporter: Optional["ArmadilloReporter"] = None  # Created in sessionstart

        # Session-wide ProcessSupervisor for crash tracking across all deployments
        self._process_supervisor: Optional[ProcessSupervisor] = None

        # Session execution state - encapsulates test abortion logic
        self.execution_state = SessionExecutionState()

        # Track failures across all pytest phases for complete failure information
        self._test_failures: Dict[str, list] = {}  # nodeid -> List[TestFailureInfo]

        # Registry for crash info by test nodeid (instead of dynamic report attributes)
        self._crash_info_registry: Dict[str, Dict[str, Any]] = {}  # nodeid -> crash_states

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
        for deployment_id, controller in deployments_to_clean:
            try:
                if controller.deployment.is_deployed():
                    logger.info(
                        "Plugin safety cleanup: shutting down deployment %s",
                        deployment_id,
                    )
                    controller.stop()
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
        logger.debug("ArmadilloPlugin: Session start")
        # Config already loaded by CLI and pytest_configure
        # Don't call load_config() again to avoid duplicate build detection
        configure_logging()
        # Note: Session-level directory isolation not currently enabled
        # (would require ApplicationContext integration in pytest fixtures)

        # Create session-wide ProcessSupervisor for crash tracking
        self._process_supervisor = ProcessSupervisor()

        # Clear any crash/timeout state from previous runs
        self.execution_state.reset()
        self._process_supervisor.clear_crash_state()

    def pytest_sessionfinish(self, _session: pytest.Session, exitstatus: int) -> None:
        """Called at the end of the pytest session."""
        logger.debug("ArmadilloPlugin: Session finish with exit status %s", exitstatus)
        for deployment_id, controller in list(self._package_deployments.items()):
            try:
                logger.debug("Stopping session deployment %s", deployment_id)
                controller.stop(timeout=60.0)
                # Capture server health (exit codes, crashes) after shutdown
                _capture_deployment_health(controller, deployment_id)
            except (OSError, ProcessLookupError, RuntimeError, AttributeError) as e:
                logger.error(
                    "Error stopping session deployment %s: %s", deployment_id, e
                )
                # Try to capture health even if shutdown failed
                try:
                    _capture_deployment_health(controller, deployment_id)
                except Exception as health_err:
                    logger.debug(
                        "Could not capture health for %s: %s", deployment_id, health_err
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


# Stash key for plugin instance (type-safe access to plugin state)
# Note: Defined after ArmadilloPlugin class to avoid forward reference issues
plugin_key = StashKey["ArmadilloPlugin"]()


def pytest_configure(config: pytest.Config) -> None:
    """Plugin entry point - create and store plugin in stash."""
    plugin = ArmadilloPlugin()
    config.stash[plugin_key] = plugin
    plugin.pytest_configure(config)


def pytest_unconfigure(config: pytest.Config) -> None:
    """Plugin cleanup entry point."""
    plugin = config.stash[plugin_key]
    plugin.pytest_unconfigure(config)


def _get_plugin(obj: Union[Config, Session, Item]) -> ArmadilloPlugin:
    """Get plugin from pytest object (config, session, or item).

    Helper to retrieve plugin from stash regardless of hook object type.

    Pytest's hook objects have inconsistent APIs. Session and Item objects have
    a 'config' attribute that we need to access to get the stash, while Config
    objects store the stash directly. This is a documented pytest pattern.
    """
    if hasattr(obj, "config"):
        plugin: ArmadilloPlugin = obj.config.stash[plugin_key]
        return plugin
    plugin = obj.stash[plugin_key]
    return plugin


def pytest_fixture_setup(
    fixturedef: FixtureDef[Any], request: FixtureRequest
) -> None:  # pylint: disable=unused-argument
    """Automatic fixture setup based on markers."""
    # Reserved for future automatic fixture setup based on markers


def pytest_collection_modifyitems(
    session: Session, config: Config, items: list[Item]
) -> None:  # pylint: disable=unused-argument
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


def pytest_addoption(parser: Any) -> None:
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
def pytest_sessionstart(session: Session) -> None:
    """Set up test session and register cleanup handlers."""
    logger.debug("Starting pytest plugin setup")
    logger.info("Test session started")

    # Get plugin and reset execution state for new session
    plugin = _get_plugin(session)

    # Register plugin in global registry for hooks that don't receive session
    PluginRegistry.register(plugin)

    # Create session-wide ProcessSupervisor (if not already created by pytest_sessionstart)
    if plugin._process_supervisor is None:
        plugin._process_supervisor = ProcessSupervisor()

    plugin.execution_state.reset()
    plugin._process_supervisor.clear_crash_state()

    # Register cleanup handlers for both normal and abnormal exits
    atexit.register(_emergency_cleanup, session)

    # Install signal handlers for Ctrl+C and SIGTERM to ensure cleanup
    def _signal_handler(signum: int, _frame: Any) -> None:
        """Handle interrupt signals by performing emergency cleanup."""
        signal_name = (
            signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
        )
        logger.warning("Received %s, performing emergency cleanup...", signal_name)

        # Perform cleanup and wait for it to complete
        _emergency_cleanup(session)

        # Give cleanup time to work (max 10 seconds)
        logger.info("Waiting for processes to terminate...")
        cleanup_timeout = 10.0
        start_time = time.time()

        # Check if processes are still running
        try:
            plugin = _get_plugin(session)
            if plugin._process_supervisor:
                while (time.time() - start_time) < cleanup_timeout:
                    if not plugin._process_supervisor._processes:
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
    # Pass the session-wide ProcessSupervisor for crash tracking across all deployments
    session_id = random_id(8)
    plugin._session_app_context = ApplicationContext.create(
        framework_config, process_supervisor=plugin._process_supervisor
    )
    plugin._session_app_context.filesystem.set_test_session_id(session_id)

    # Note: With package-scoped fixtures, deployments are created lazily per-package,
    # not at session start. This allows each test package to have its own deployment.
    deployment_mode = framework_config.deployment_mode
    logger.info(
        "Session initialized for %s deployment mode (deployments will be created per-package)",
        deployment_mode.value,
    )

    # Print test artifacts directory (clean access via shared context)
    from ..utils.output import print_status

    artifacts_dir = plugin._session_app_context.filesystem.work_dir()
    print_status(f"📁 Test artifacts: {artifacts_dir}")
    logger.info("Test artifacts directory: %s", artifacts_dir)

    # Enable detailed file logging now that we have a temp directory
    # Console stays at INFO/WARNING level, but file captures DEBUG for debugging
    framework_log_file = artifacts_dir / "armadillo.log"
    add_file_logging(framework_log_file, level="DEBUG")
    logger.info("Framework debug logging enabled: %s", framework_log_file)

    # Always create reporter (with result collector) even in compact mode
    # The reporter's verbose console output is only used when NOT in compact mode,
    # but the result collector is always needed for JSON/JUnit export
    plugin.reporter = ArmadilloReporter(
        process_supervisor=plugin._process_supervisor,
        result_collector=plugin._session_app_context.result_collector,
    )

    if not framework_config.compact_mode:
        # Only initialize reporter's console output features in verbose mode
        plugin.reporter.pytest_sessionstart(session)
        # Set the actual test start time AFTER server deployment is complete
        plugin.reporter.session_start_time = time.time()


def _is_compact_mode_enabled() -> bool:
    """Check if compact test output mode is enabled."""
    from ..core.config import get_config as get_framework_config

    framework_config = get_framework_config()
    return framework_config.compact_mode


def _cleanup_temp_dir_if_needed(_session: Session, exitstatus: int) -> None:
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
        # Note: _session_app_context is initialized to None in __init__, but only
        # populated in pytest_sessionstart hook, so it may still be None during early cleanup
        plugin = _get_plugin(_session)
        if plugin._session_app_context is None:
            logger.debug("No session app context - skipping temp cleanup")
            return

        session_work_dir = plugin._session_app_context.filesystem.work_dir()
        config = plugin._session_app_context.config

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
def pytest_sessionfinish(session: Session, exitstatus: int) -> None:
    """Clean up all resources at the end of test session."""
    logger.debug("Starting pytest plugin cleanup")

    # Get plugin instance
    plugin = _get_plugin(session)

    # Check if deployment already failed
    if plugin._deployment_failed:
        logger.error("Setting exit status to 1 due to deployment failure")
        session.exitstatus = 1

    # Stop servers FIRST to capture exit codes
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

    # NOW check for server health issues (AFTER servers stopped and exit codes captured)
    if plugin._server_health:
        logger.error(
            "Server health issues detected in %d deployment(s)",
            len(plugin._server_health),
        )
        for deployment_id, health_info in plugin._server_health.items():
            logger.error(
                "Deployment %s: %s", deployment_id, health_info.get_failure_summary()
            )
        logger.error("Setting exit status to 1 due to server health issues")
        session.exitstatus = 1

    # Print summary and export results AFTER we know final health status
    if plugin.reporter:
        plugin.reporter.session_finish_time = time.time()
        # Set deployment failed flag on reporter if either deployment or health failed
        plugin.reporter.deployment_failed = plugin._deployment_failed or bool(
            plugin._server_health
        )

        # Print summary only in verbose mode
        if not _is_compact_mode_enabled():
            plugin.reporter.print_final_summary()
            plugin.reporter.pytest_sessionfinish(session, exitstatus)

        # Print post-analysis summary if health issues detected (works in both modes)
        if plugin._server_health:
            # Perform sanitizer matching for console output
            from ..utils.sanitizer_matcher import match_all_sanitizers

            # Extract sanitizer file paths from ServerHealthInfo.sanitizer_errors
            sanitizer_files = {}
            for dep_id, health in plugin._server_health.items():
                for server_id, san_errors in health.sanitizer_errors.items():
                    if san_errors:
                        sanitizer_files[server_id] = [err.file_path for err in san_errors]

            sanitizer_matches = {}
            if sanitizer_files and plugin.reporter.result_collector:
                results = plugin.reporter.result_collector.finalize_results()
                sanitizer_matches = match_all_sanitizers(
                    sanitizer_files,
                    results.get("test_suites", {}),
                    min_confidence="high",
                )

            # Print summary (works in both verbose and compact mode)
            plugin.reporter.print_post_analysis_summary(
                plugin._server_health, sanitizer_matches
            )

        # Export test results ALWAYS (regardless of compact mode)
        # We always need JSON and JUnit XML for CI/CD integration
        try:
            # Determine output directory (default to test-results if not set)
            output_dir = Path("./test-results")

            # Export results (JSON and custom JUnit XML with server health info)
            # Note: This creates Armadillo's enhanced JUnit XML that includes
            # sanitizer errors, crashes, and other server health information
            plugin.reporter.export_results(
                output_dir,
                formats=["json", "junit"],
                server_health=plugin._server_health,
            )
        except (OSError, IOError) as e:
            logger.error("Failed to export test results: %s", e, exc_info=True)

    # Final cleanup: stop watchdog and unregister plugin
    try:
        stop_watchdog()
    except (OSError, RuntimeError, AttributeError) as e:
        logger.debug("Error stopping watchdog: %s", e)
    finally:
        # Unregister plugin from global registry
        PluginRegistry.unregister()


def pytest_runtest_setup(item: Item) -> None:
    """Handle test setup - check if we should skip due to previous crash, timeout, or deployment failure."""
    plugin = _get_plugin(item)

    # If deployment failed, skip all tests
    if plugin._deployment_failed:
        pytest.skip(
            f"Test skipped due to deployment failure: {plugin._deployment_failure_reason}"
        )

    # Check if we should abort this test due to previous failures
    should_abort, reason = plugin.execution_state.should_abort_test(item.nodeid)
    if should_abort:
        assert (
            reason is not None
        ), "Abort reason should be set when should_abort is True"
        pytest.skip(reason)

    # Handle reporter setup
    if not _is_compact_mode_enabled() and plugin.reporter:
        plugin.reporter.pytest_runtest_setup(item)


def pytest_runtest_call(item: Item) -> None:
    """Handle test call start."""
    plugin = _get_plugin(item)
    if not _is_compact_mode_enabled() and plugin.reporter:
        plugin.reporter.pytest_runtest_call(item)


def pytest_runtest_teardown(
    item: Item, nextitem: Optional[Item]
) -> None:  # pylint: disable=unused-argument
    """Handle test teardown start."""
    plugin = _get_plugin(item)
    if not _is_compact_mode_enabled() and plugin.reporter:
        plugin.reporter.pytest_runtest_teardown(item)


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item: Item, call: Any) -> Any:
    """Hook to modify test reports and detect crashes/timeouts."""
    plugin = _get_plugin(item)

    # Let pytest create the report first
    outcome = yield
    report = outcome.get_result()

    # Collect failure info from ALL phases (setup, call, teardown)
    if report.failed and call.when in ("setup", "call", "teardown"):
        _record_failure_info(item, report, call, plugin)

    # Record test results to ResultCollector (even in compact mode)
    # This ensures we have data for JSON/JUnit export regardless of output mode
    if call.when == "teardown" and plugin.reporter:
        _record_test_to_collector(item, report, plugin)

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
            plugin.execution_state.record_timeout(item.nodeid)

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

            # Record as timeout in the result collector
            if not _is_compact_mode_enabled() and plugin.reporter:
                plugin.reporter.result_collector.record_test_result(
                    nodeid=item.nodeid,
                    outcome=ExecutionOutcome.TIMEOUT,
                    duration=getattr(report, "duration", 0.0),
                    details=timeout_message,
                    crash_info=None,
                )

    # Check for crashes after the test phase completes
    if (
        call.when == "call"
        and plugin._process_supervisor
        and plugin._process_supervisor.has_any_crash()
    ):
        crash_states = plugin._process_supervisor.get_crash_state()

        # Mark this test as failed due to crash
        report.outcome = "failed"
        plugin.execution_state.record_crash(item.nodeid)

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

        plugin._crash_info_registry[item.nodeid] = crash_states

        logger.error(
            "Test %s failed due to server crash: %s", item.nodeid, crash_message
        )

        # Record the crash in the result collector
        if not _is_compact_mode_enabled() and plugin.reporter:
            # Force record this as a crashed test
            plugin.reporter.result_collector.record_test_result(
                nodeid=item.nodeid,
                outcome=ExecutionOutcome.CRASHED,
                duration=getattr(report, "duration", 0.0),
                details=crash_message,
                crash_info=crash_states,
            )


def pytest_runtest_logreport(report: Any) -> None:
    """Handle test report."""
    if not _is_compact_mode_enabled():
        try:
            plugin = PluginRegistry.get()
            if plugin and plugin.reporter:
                plugin.reporter.pytest_runtest_logreport(report)
        except RuntimeError as e:
            logger.error("pytest_runtest_logreport called without active plugin: %s", e)


def pytest_runtest_logstart(
    nodeid: str, location: Optional[tuple[str, Optional[int], str]]
) -> Optional[str]:
    """Override pytest's default test file output to suppress filename printing."""
    if not _is_compact_mode_enabled():
        try:
            plugin = PluginRegistry.get()
            if plugin and plugin.reporter:
                # Call our reporter but suppress pytest's default filename output
                plugin.reporter.pytest_runtest_logstart(nodeid, location)
                # Return empty string to suppress pytest's default output
                return ""
        except RuntimeError as e:
            logger.error("pytest_runtest_logstart called without active plugin: %s", e)
    return None


def pytest_report_teststatus(
    report: Any, config: Config
) -> Optional[tuple[str, str, str]]:  # pylint: disable=unused-argument
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


def pytest_terminal_summary(
    terminalreporter: Any, exitstatus: int, config: Config
) -> None:  # pylint: disable=unused-argument
    """Override terminal summary - print our summary AFTER all cleanup is complete."""
    plugin = _get_plugin(config)
    if not _is_compact_mode_enabled() and plugin.reporter:
        if not plugin.reporter.summary_printed:
            plugin.reporter.print_final_summary()
            plugin.reporter.summary_printed = True


def _cleanup_all_deployments(emergency: bool = True) -> None:
    """Cleanup all tracked deployments with bulletproof shutdown."""
    try:
        plugin = PluginRegistry.get()
    except RuntimeError as e:
        logger.debug("No plugin available for deployment cleanup: %s", e)
        return
    deployments = list(plugin._package_deployments.items())
    if deployments:
        logger.debug(
            "_cleanup_all_deployments: found %d deployments, emergency=%s",
            len(deployments),
            emergency,
        )
        if emergency:
            logger.warning("Emergency cleanup of %s deployments", len(deployments))
        for deployment_id, controller in deployments:
            try:
                if emergency:
                    logger.info("Emergency shutdown of deployment: %s", deployment_id)
                controller.stop(timeout=15.0)
                logger.debug("Deployment %s shutdown completed", deployment_id)
                # Always capture health, even in emergency cleanup
                _capture_deployment_health(controller, deployment_id)
            except (OSError, ProcessLookupError, RuntimeError, AttributeError) as e:
                logger.error(
                    "Failed emergency cleanup of deployment %s: %s",
                    deployment_id,
                    e,
                )
                # Even if shutdown failed, try to capture health
                try:
                    _capture_deployment_health(controller, deployment_id)
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
                        servers = controller.deployment.get_servers()
                    except (AttributeError, RuntimeError) as get_e:
                        logger.warning(
                            "Could not get servers from controller %s: %s",
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
        plugin._package_deployments.clear()
        if emergency:
            logger.info("Emergency deployment cleanup completed")


def _cleanup_all_processes(emergency: bool = True) -> None:
    """Cleanup all supervised processes with bulletproof termination."""
    try:
        logger.info("Starting _cleanup_all_processes")
        try:
            plugin = PluginRegistry.get()
        except RuntimeError as e:
            logger.debug("No plugin available for process cleanup: %s", e)
            return
        if not plugin._process_supervisor:
            logger.debug("No process supervisor available - cannot cleanup processes")
            return

        process_supervisor = plugin._process_supervisor
        server_ids = list(process_supervisor._processes.keys())
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
                        if server_id in process_supervisor._processes:
                            process = process_supervisor._processes[server_id]
                            if process.poll() is not None:
                                logger.debug(
                                    "Process %s already dead (exit code: %s), skipping",
                                    server_id,
                                    process.returncode,
                                )
                                # Remove it from tracking since it's already dead
                                process_supervisor._cleanup_process(server_id)
                                continue

                        logger.debug("Sending SIGTERM to process group %s", server_id)
                        process_supervisor.stop(server_id, graceful=True, timeout=3.0)
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
                            if server_id in process_supervisor._processes:
                                process = process_supervisor._processes[server_id]
                                if process.poll() is not None:
                                    logger.debug(
                                        "Process %s already dead (exit code: %s), skipping force kill",
                                        server_id,
                                        process.returncode,
                                    )
                                    # Remove it from tracking since it's already dead
                                    process_supervisor._cleanup_process(server_id)
                                    continue

                            logger.debug(
                                "Sending SIGKILL to process group %s", server_id
                            )
                            process_supervisor.stop(
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
                        if server_id in process_supervisor._processes:
                            process = process_supervisor._processes[server_id]
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


def _emergency_cleanup(session: Optional[Session] = None) -> None:
    """Emergency cleanup function registered with atexit.

    Args:
        session: Optional session object. If not provided, uses registry.
    """
    # Check if there's actually anything to clean up
    if session:
        plugin = _get_plugin(session)
    else:
        try:
            plugin = PluginRegistry.get()
        except RuntimeError:
            # No plugin registered, nothing to clean up
            return
    if not plugin:
        return
    has_deployments = bool(plugin._package_deployments)

    has_processes = False
    if plugin._process_supervisor:
        has_processes = bool(plugin._process_supervisor._processes)

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
            if plugin._process_supervisor and plugin._process_supervisor._processes:
                logger.warning("Some processes still running, using nuclear cleanup...")
                kill_all_supervised_processes(plugin._process_supervisor)
            else:
                logger.info("All processes cleaned up successfully")
        except (OSError, ProcessLookupError, AttributeError, RuntimeError) as nuclear_e:
            logger.error("Nuclear cleanup failed: %s", nuclear_e)
    except (OSError, ProcessLookupError, AttributeError, RuntimeError) as e:
        logger.error("Error in emergency cleanup: %s", e)
        logger.error("Emergency cleanup stack trace: %s", traceback.format_exc())


def _record_failure_info(
    item: Item, report: Any, call: Any, plugin: ArmadilloPlugin
) -> None:
    """Extract and record complete failure information from pytest report.

    Called for each phase (setup, call, teardown) that fails, building up
    a complete picture of what went wrong.

    Args:
        item: The pytest test item
        report: The test report for this phase
        call: The call object with exception info
        plugin: The plugin instance
    """
    from ..results.collector import TestFailureInfo

    # Initialize failure list for this test if needed
    if item.nodeid not in plugin._test_failures:
        plugin._test_failures[item.nodeid] = []

    # Extract exception details
    exc_type = ""
    exc_message = ""
    traceback_text = ""

    if call.excinfo:
        exc_type = call.excinfo.type.__name__ if call.excinfo.type else ""
        exc_message = str(call.excinfo.value)
        # Get full traceback representation
        traceback_text = str(call.excinfo.getrepr(style="long"))

    # Create failure info for this phase
    failure_info = TestFailureInfo(
        phase=call.when,
        exception_type=exc_type,
        exception_message=exc_message,
        traceback=traceback_text,
        longrepr=str(report.longrepr) if report.longrepr else "",
    )

    plugin._test_failures[item.nodeid].append(failure_info)
    logger.debug(
        "Recorded failure in %s phase for %s: %s: %s",
        call.when,
        item.nodeid,
        exc_type,
        exc_message,
    )


def _record_test_to_collector(item: Item, report: Any, plugin: ArmadilloPlugin) -> None:
    """Record test result to ResultCollector (works in both compact and verbose modes).

    This function is called for ALL tests regardless of output mode, ensuring we
    have data for JSON/JUnit export even when the verbose reporter is disabled.

    Args:
        item: The pytest test item
        report: The test report from teardown phase
        plugin: The plugin instance containing the result collector
    """
    if not plugin.reporter or not plugin.reporter.result_collector:
        return

    # Determine outcome - CHECK FAILURE TRACKING FIRST
    # The teardown report might say "passed" even if the call phase failed
    # We need to check if we recorded any failures for this test
    has_failure = (
        item.nodeid in plugin._test_failures and plugin._test_failures[item.nodeid]
    )

    outcome_map = {
        "passed": ExecutionOutcome.PASSED,
        "failed": ExecutionOutcome.FAILED,
        "skipped": ExecutionOutcome.SKIPPED,
        "error": ExecutionOutcome.ERROR,
    }

    # Check for crashes or timeouts that override everything
    # Look up crash info from registry
    crash_info = plugin._crash_info_registry.get(item.nodeid)
    if crash_info:
        exec_outcome = ExecutionOutcome.CRASHED
    elif plugin.execution_state.timeout_detected_in_test == item.nodeid:
        exec_outcome = ExecutionOutcome.TIMEOUT
    # If we recorded failures, use FAILED outcome regardless of what teardown says
    elif has_failure:
        exec_outcome = ExecutionOutcome.FAILED
    else:
        exec_outcome = outcome_map.get(report.outcome, ExecutionOutcome.ERROR)

    # Get timing from report
    duration = getattr(report, "duration", 0.0)

    # Get details from report (fallback if no failure_info)
    details = None
    if report.longrepr:
        details = str(report.longrepr)

    # Get markers (keywords attribute may not exist on all report types)
    keywords = getattr(report, "keywords", {})
    markers = [key for key in keywords if not key.startswith("_")]

    # Get timestamps from reporter if available
    started_at = None
    finished_at = None
    if plugin.reporter:
        started_at = plugin.reporter._test_start_times.get(item.nodeid)
        if started_at:
            finished_at = started_at + timedelta(seconds=duration)

    # Get aggregated failure info from all phases
    failure_info = None
    if has_failure:
        failures = plugin._test_failures[item.nodeid]
        # Prefer call phase failure, otherwise use first failure
        failure_info = next(
            (f for f in failures if f.phase == "call"),
            failures[0] if failures else None,
        )

    # Record to collector with complete failure information
    plugin.reporter.result_collector.record_test_result(
        nodeid=item.nodeid,
        outcome=exec_outcome,
        duration=duration,
        markers=markers,
        details=details,
        crash_info=crash_info,
        started_at=started_at,
        finished_at=finished_at,
        failure_info=failure_info,
    )

    # Clean up failure tracking and crash info for this test
    if item.nodeid in plugin._test_failures:
        del plugin._test_failures[item.nodeid]
    if item.nodeid in plugin._crash_info_registry:
        del plugin._crash_info_registry[item.nodeid]


def _capture_deployment_health(
    controller: DeploymentController, deployment_id: DeploymentId
) -> None:
    """Capture and store server health after deployment shutdown.

    Args:
        controller: The deployment controller that was shut down
        deployment_id: Identifier for this deployment
    """
    try:
        plugin = PluginRegistry.get()
    except RuntimeError:
        logger.debug("_capture_deployment_health: no plugin available")
        return
    health = controller.get_health_info()
    if health.has_issues():
        # Convert string to DeploymentId value object
        plugin._server_health[deployment_id] = health
        logger.warning(
            "Server health issues detected in %s: %s",
            str(deployment_id),
            health.get_failure_summary(),
        )


def create_package_deployment(package_name: str) -> Any:
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
    framework_config = get_config()
    deployment_mode = framework_config.deployment_mode

    try:
        plugin = PluginRegistry.get()
    except RuntimeError as e:
        raise RuntimeError("Cannot create deployment: no session available") from e

    if deployment_mode == DeploymentMode.CLUSTER:
        # Create cluster deployment for this package
        deployment_id = DeploymentId(f"cluster_{package_name}_{random_id(6)}")
        if plugin._session_app_context is None:
            raise RuntimeError(
                "Cannot create deployment: no session app context available"
            )
        cluster_config = ClusterConfig(agents=3, dbservers=2, coordinators=1)
        controller = DeploymentController.create_cluster(
            deployment_id, plugin._session_app_context, cluster_config
        )
        try:
            logger.info(
                "Starting package cluster deployment %s for %s",
                deployment_id,
                package_name,
            )
            controller.start(timeout=300.0)
            logger.info("Package cluster deployment %s ready", deployment_id)
            plugin._package_deployments[deployment_id] = controller

            coordinators = controller.deployment.get_servers_by_role(
                ServerRole.COORDINATOR
            )
            if not coordinators:
                raise RuntimeError("No coordinators available in cluster")
            yield coordinators[0]
        finally:
            logger.info("Stopping package cluster deployment %s", deployment_id)
            try:
                # Stop the servers first - this causes process exit and sanitizer files to be written
                controller.stop(timeout=120.0)

                # Capture health info AFTER stopping - process_info is preserved for sanitizer collection
                _capture_deployment_health(controller, deployment_id)
            except (OSError, ProcessLookupError, RuntimeError, AttributeError) as e:
                logger.error(
                    "Error stopping cluster deployment %s: %s", deployment_id, e
                )
            finally:
                plugin._package_deployments.pop(deployment_id, None)
    else:
        # Single server mode
        deployment_id = DeploymentId(f"single_{package_name}_{random_id(6)}")
        if plugin._session_app_context is None:
            raise RuntimeError(
                "Cannot create deployment: no session app context available"
            )
        controller = DeploymentController.create_single_server(
            deployment_id, plugin._session_app_context
        )
        try:
            logger.info("Starting package single server for %s", package_name)
            controller.start(timeout=60.0)
            plugin._package_deployments[deployment_id] = controller

            servers = controller.deployment.get_servers()
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
                # Stop the server first - this causes process exit and sanitizer files to be written
                controller.stop(timeout=30.0)

                # Capture health info AFTER stopping - process_info is preserved for sanitizer collection
                _capture_deployment_health(controller, deployment_id)
            except (OSError, ProcessLookupError, RuntimeError, AttributeError) as e:
                logger.error("Error stopping package server: %s", e)
            finally:
                plugin._package_deployments.pop(deployment_id, None)
