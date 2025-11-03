"""Unit tests for ServerHealthChecker."""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch

from armadillo.core.types import HealthStatus
from armadillo.core.value_objects import ServerId
from armadillo.instances.health_checker import ServerHealthChecker


class TestServerHealthChecker:
    """Test server health checking functionality."""

    def setup_method(self):
        """Set up test environment."""
        # Create mock logger
        self.mock_logger = Mock()

        # Create mock auth provider
        self.mock_auth_provider = Mock()
        self.mock_auth_provider.get_auth_headers.return_value = {
            "Authorization": "Bearer test-token"
        }

        self.health_checker = ServerHealthChecker(
            logger=self.mock_logger, auth_provider=self.mock_auth_provider
        )

    @patch("armadillo.instances.health_checker.is_process_running", return_value=True)
    def test_check_readiness_success(self, mock_is_running):
        """Test successful readiness check."""
        # Mock successful health check
        with patch.object(self.health_checker, "check_health") as mock_check_health:
            mock_check_health.return_value = HealthStatus(
                is_healthy=True, response_time=0.1
            )

            result = self.health_checker.check_readiness(
                ServerId("test_server"), "http://localhost:8529"
            )

            assert result is True
            mock_is_running.assert_called_once_with(ServerId("test_server"))
            mock_check_health.assert_called_once_with(
                "http://localhost:8529", timeout=2.0
            )

    @patch("armadillo.instances.health_checker.is_process_running", return_value=False)
    def test_check_readiness_process_not_running(self, mock_is_running):
        """Test readiness check when process is not running."""
        result = self.health_checker.check_readiness(
            ServerId("test_server"), "http://localhost:8529"
        )

        assert result is False
        self.mock_logger.debug.assert_called_with(
            "Readiness check failed for %s: Process not running", "test_server"
        )

    @patch("armadillo.instances.health_checker.is_process_running", return_value=True)
    def test_check_readiness_health_check_fails(self, mock_is_running):
        """Test readiness check when health check fails."""
        with patch.object(self.health_checker, "check_health") as mock_check_health:
            mock_check_health.return_value = HealthStatus(
                is_healthy=False, response_time=1.0, error_message="Connection failed"
            )

            result = self.health_checker.check_readiness(
                "test_server", "http://localhost:8529"
            )

            assert result is False
            self.mock_logger.debug.assert_called_with(
                "Readiness check failed for %s: %s", "test_server", "Connection failed"
            )

    @patch(
        "armadillo.instances.health_checker.is_process_running",
        side_effect=Exception("Process check error"),
    )
    def test_check_readiness_exception_handling(self, mock_is_running):
        """Test readiness check exception handling."""
        result = self.health_checker.check_readiness(
            "test_server", "http://localhost:8529"
        )

        assert result is False
        # Check the lazy formatting call with the actual exception object
        call_args = self.mock_logger.debug.call_args
        assert call_args[0][0] == "Readiness check exception for %s: %s"
        assert (
            call_args[0][1] == "test_server"
        )  # String log message, not ServerId object
        assert str(call_args[0][2]) == "Process check error"

    @patch("asyncio.run")
    def test_check_health_success(self, mock_asyncio_run):
        """Test successful health check."""
        expected_status = HealthStatus(
            is_healthy=True, response_time=0.2, details={"version": "3.9.0"}
        )

        # Mock asyncio.run to return expected status without awaiting coroutine
        def mock_run(coro):
            # Close the coroutine to prevent "never awaited" warning
            coro.close()
            return expected_status

        mock_asyncio_run.side_effect = mock_run
        result = self.health_checker.check_health("http://localhost:8529", timeout=5.0)

        assert result == expected_status
        mock_asyncio_run.assert_called_once()

    @patch("asyncio.run")
    def test_check_health_exception_handling(self, mock_asyncio_run):
        """Test health check exception handling."""

        # Mock asyncio.run to raise exception without awaiting coroutine
        def mock_run(coro):
            # Close the coroutine to prevent "never awaited" warning
            coro.close()
            raise Exception("Async error")

        mock_asyncio_run.side_effect = mock_run
        result = self.health_checker.check_health("http://localhost:8529", timeout=5.0)

        assert result.is_healthy is False
        assert "Health check error: Async error" in result.error_message
        assert result.response_time >= 0
        mock_asyncio_run.assert_called_once()

    # NOTE: Async health check tests are skipped due to conflicts with global socket mocking
    # in unit test environment. Real async health checking is covered by integration tests.

    def test_health_checker_protocol_compliance(self):
        """Test that ServerHealthChecker implements HealthChecker protocol."""
        # This test verifies that the class implements the expected interface
        assert hasattr(self.health_checker, "check_readiness")
        assert hasattr(self.health_checker, "check_health")
        assert callable(self.health_checker.check_readiness)
        assert callable(self.health_checker.check_health)

    @patch("asyncio.run")
    def test_health_checker_integration_with_dependencies(self, mock_asyncio_run):
        """Test health checker integration with injected dependencies."""
        # Test logger integration
        result = self.health_checker.check_readiness(
            "test_server", "http://localhost:8529"
        )
        # Logger should be called (either success or failure)
        assert self.mock_logger.debug.called

        # Test auth provider integration with proper mocking
        mock_status = HealthStatus(is_healthy=True, response_time=0.1)

        def mock_run(coro):
            # Close the coroutine to prevent "never awaited" warning
            coro.close()
            return mock_status

        mock_asyncio_run.side_effect = mock_run
        result = self.health_checker.check_health("http://localhost:8529")
        assert result == mock_status
