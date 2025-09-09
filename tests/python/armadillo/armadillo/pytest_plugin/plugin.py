"""Main pytest plugin for Armadillo framework integration."""

import pytest
from typing import Generator, Optional, Dict, Any

from ..core.config import load_config, get_config
from ..core.log import configure_logging, get_logger, log_test_event, set_log_context, clear_log_context
from ..core.time import set_global_deadline, stop_watchdog
from ..instances.server import ArangoServer
from ..core.types import ServerRole

logger = get_logger(__name__)


class ArmadilloPlugin:
    """Main pytest plugin for Armadillo framework."""

    def __init__(self) -> None:
        self._session_servers: Dict[str, ArangoServer] = {}

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
            "markers", "slow: Long-running test"
        )
        config.addinivalue_line(
            "markers", "crash_test: Test involves crashes"
        )
        config.addinivalue_line(
            "markers", "rta_suite: RTA test suite marker"
        )

        # Configure Armadillo framework
        armadillo_config = load_config(
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
        set_global_deadline(armadillo_config.test_timeout)

        logger.info("Armadillo pytest plugin configured")

    def pytest_unconfigure(self, config: pytest.Config) -> None:
        """Clean up after pytest run."""
        # Stop any remaining session servers
        for server_id, server in self._session_servers.items():
            try:
                if server.is_running():
                    server.stop()
            except Exception as e:
                logger.error(f"Error stopping session server {server_id}: {e}")

        # Stop timeout watchdog
        stop_watchdog()

        logger.info("Armadillo pytest plugin unconfigured")

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

    def pytest_runtest_call(self, pyfuncitem: pytest.Item) -> None:
        """Handle test execution."""
        test_name = pyfuncitem.nodeid
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


def pytest_runtest_call(pyfuncitem: pytest.Item) -> None:
    """Test call entry point."""
    _plugin.pytest_runtest_call(pyfuncitem)


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
        except Exception as e:
            logger.error(f"Error stopping session server: {e}")

        _plugin._session_servers.pop("single", None)


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


# Marker-based automatic fixture selection
def pytest_fixture_setup(fixturedef, request):
    """Automatic fixture setup based on markers."""
    # This will be expanded in later phases for automatic server provisioning
    pass

