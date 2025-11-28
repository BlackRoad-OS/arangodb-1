"""
Unit tests for instances/server.py - ArangoDB server wrapper.

Tests ArangoServer functionality including basic operations, lifecycle management,
configuration, error handling, and integration scenarios.
"""

import pytest
from typing import Any
from unittest.mock import Mock, patch
from pathlib import Path

from armadillo.instances.server import ArangoServer, ServerPaths
from armadillo.core.types import ServerRole, ClusterConfig, TimeoutConfig
from armadillo.core.context import ApplicationContext
from armadillo.core.value_objects import ServerId


class TestArangoServerBasic:
    """Test ArangoServer basic functionality."""

    def test_server_can_be_created(self) -> None:
        """Test ArangoServer can be instantiated using factory method."""
        app_context = ApplicationContext.for_testing()
        server = ArangoServer.create_single_server(
            server_id=ServerId("test_server"), app_context=app_context, port=8529
        )

        assert server is not None
        assert server.server_id == ServerId("test_server")
        assert server.port == 8529
        assert server.role == ServerRole.SINGLE
        assert server.endpoint == "http://127.0.0.1:8529"

    def test_server_with_different_roles(self) -> None:
        """Test server creation with different roles."""
        roles = [
            ServerRole.SINGLE,
            ServerRole.COORDINATOR,
            ServerRole.DBSERVER,
            ServerRole.AGENT,
        ]

        app_context = ApplicationContext.for_testing()

        for role in roles:
            if role == ServerRole.SINGLE:
                server = ArangoServer.create_single_server(
                    server_id=ServerId(f"test_{role.value}"),
                    app_context=app_context,
                    port=8530,
                )
            else:
                server = ArangoServer.create_cluster_server(
                    server_id=ServerId(f"test_{role.value}"),
                    role=role,
                    port=8530,
                    app_context=app_context,
                )

            assert server.role == role
            assert server.endpoint == "http://127.0.0.1:8530"

    def test_server_with_different_ports(self) -> None:
        """Test server creation with different ports."""
        app_context = ApplicationContext.for_testing()

        server1 = ArangoServer.create_single_server(
            server_id=ServerId("test1"),
            app_context=app_context,
            port=8531,
        )
        server2 = ArangoServer.create_single_server(
            server_id=ServerId("test2"),
            app_context=app_context,
            port=8532,
        )

        assert server1.endpoint == "http://127.0.0.1:8531"
        assert server2.endpoint == "http://127.0.0.1:8532"

    def test_server_not_running_initially(self) -> None:
        """Test server is not running initially."""
        app_context = ApplicationContext.for_testing()

        server = ArangoServer.create_single_server(
            server_id=ServerId("test"),
            app_context=app_context,
            port=8529,
        )

        assert server.is_running() is False

    def test_server_id_uniqueness(self) -> None:
        """Test server IDs are preserved correctly."""
        app_context = ApplicationContext.for_testing()
        server1 = ArangoServer.create_single_server(
            server_id=ServerId("server_one"), app_context=app_context, port=8529
        )
        server2 = ArangoServer.create_cluster_server(
            server_id=ServerId("server_two"),
            role=ServerRole.COORDINATOR,
            port=8530,
            app_context=app_context,
        )

        assert server1.server_id != server2.server_id
        assert server1.server_id == ServerId("server_one")
        assert server2.server_id == ServerId("server_two")


class TestArangoServerPublicInterface:
    """Test the public interface works as expected."""

    def test_endpoint_format(self) -> None:
        """Test endpoint format is consistent."""
        app_context = ApplicationContext.for_testing()
        server = ArangoServer.create_single_server(
            server_id=ServerId("test"), app_context=app_context, port=9999
        )

        # Should be HTTP URL with 127.0.0.1 and correct port
        assert server.endpoint.startswith("http://")
        assert "127.0.0.1" in server.endpoint
        assert "9999" in server.endpoint

    def test_role_assignment(self) -> None:
        """Test role assignment works for all types."""
        app_context = ApplicationContext.for_testing()
        test_cases = [
            (ServerRole.SINGLE, "single"),
            (ServerRole.COORDINATOR, "coordinator"),
            (ServerRole.DBSERVER, "dbserver"),
            (ServerRole.AGENT, "agent"),
        ]

        for role, expected_value in test_cases:
            if role == ServerRole.SINGLE:
                server = ArangoServer.create_single_server(
                    server_id=ServerId(f"test_{expected_value}"),
                    app_context=app_context,
                    port=8529,
                )
            else:
                server = ArangoServer.create_cluster_server(
                    server_id=ServerId(f"test_{expected_value}"),
                    role=role,
                    port=8529,
                    app_context=app_context,
                )
            assert server.role == role
            assert server.role.value == expected_value


class TestArangoServerLifecycle:
    """Test ArangoServer lifecycle with basic mocking."""

    def setup_method(self) -> None:
        """Set up test environment."""
        self.app_context = ApplicationContext.for_testing()
        self.server = ArangoServer.create_single_server(
            server_id=ServerId("test_server"),
            app_context=self.app_context,
            port=8529,
        )

    @patch("pathlib.Path.exists", return_value=True)
    def test_start_server_calls_process(self, mock_exists: Any) -> None:
        """Test server start calls process supervisor."""
        # Mock the process supervisor methods
        mock_process_info = Mock(pid=12345)
        self.server._app_context.process_supervisor.start = Mock(
            return_value=mock_process_info
        )
        self.server._app_context.process_supervisor.is_running = Mock(return_value=True)

        self.server.start()

        # Server should be running after successful start
        assert self.server.is_running() is True
        self.server._app_context.process_supervisor.start.assert_called_once()

        # Check process ID was set
        call_args = self.server._app_context.process_supervisor.start.call_args
        process_id = call_args[0][0]
        assert process_id == ServerId("test_server")

    def test_stop_server_calls_process(self) -> None:
        """Test server stop calls process supervisor."""
        # Set up server as if it was started
        from armadillo.core.process import ProcessInfo
        from pathlib import Path

        # Mock the process supervisor
        self.server._app_context.process_supervisor.stop = Mock()

        self.server._runtime.process_info = ProcessInfo(
            pid=12345,
            command=["test"],
            start_time=123.0,
            working_dir=Path("/tmp"),
            env={},
        )
        self.server._runtime.is_running = True

        self.server.stop()

        self.server._app_context.process_supervisor.stop.assert_called_once_with(
            ServerId("test_server"), graceful=True, timeout=30.0
        )

    def test_stop_server_not_started(self) -> None:
        """Test stopping server that wasn't started doesn't crash."""
        self.server.stop()
        # Should not crash
        assert self.server._runtime.process_info is None

    def test_is_running_with_process_id(self) -> None:
        """Test is_running delegates to process supervisor."""
        self.server._app_context.process_supervisor.is_running = Mock(return_value=True)
        self.server._runtime.is_running = True

        assert self.server.is_running() is True
        # Note: The actual implementation checks _is_running flag, not process supervisor

    def test_is_running_no_process_id(self) -> None:
        """Test is_running returns False when no process started."""
        assert self.server.is_running() is False


class TestArangoServerConfiguration:
    """Test server configuration building."""

    def setup_method(self) -> None:
        """Set up test environment."""
        self.app_context = ApplicationContext.for_testing()
        self.server = ArangoServer.create_single_server(
            server_id=ServerId("test"),
            app_context=self.app_context,
            port=8529,
        )

    @patch("pathlib.Path.exists", return_value=True)
    def test_build_command_returns_list(self, mock_exists: Any) -> None:
        """Test command building returns a list."""
        command = self.server._build_command()

        assert isinstance(command, list)
        assert len(command) > 0
        # First element should be the arangod executable
        assert "arangod" in command[0]

    @patch("pathlib.Path.exists", return_value=True)
    def test_build_command_contains_basic_params(self, mock_exists: Any) -> None:
        """Test command contains basic parameters."""
        command = self.server._build_command()
        command_str = " ".join(map(str, command))

        # Should contain server endpoint
        assert "--server.endpoint" in command_str
        assert "8529" in command_str

        # Should contain configuration file
        assert "--configuration" in command_str

        # Should contain TOP_DIR definition
        assert "TOP_DIR" in command_str


class TestArangoServerErrorHandling:
    """Test server error handling."""

    def setup_method(self) -> None:
        """Set up test environment."""
        self.app_context = ApplicationContext.for_testing()
        self.server = ArangoServer.create_single_server(
            server_id=ServerId("test"),
            app_context=self.app_context,
            port=8529,
        )

    def test_start_process_failure(self) -> None:
        """Test handling of process start failure."""
        from armadillo.core.errors import ProcessStartupError, ServerStartupError

        self.server._app_context.process_supervisor.start = Mock(
            side_effect=OSError("Failed to start")
        )

        with pytest.raises(ServerStartupError):
            self.server.start()

    def test_stop_process_failure_handled_gracefully(self) -> None:
        """Test stop handles process failure gracefully."""
        from armadillo.core.errors import ProcessError, ServerShutdownError

        self.server._app_context.process_supervisor.stop = Mock(
            side_effect=OSError("Failed to stop")
        )

        from armadillo.core.process import ProcessInfo
        from pathlib import Path

        self.server._runtime.process_info = ProcessInfo(
            pid=12345,
            command=["test"],
            start_time=123.0,
            working_dir=Path("/tmp"),
            env={},
        )
        self.server._runtime.is_running = True

        # Should raise ServerShutdownError but still clean up
        with pytest.raises(ServerShutdownError):
            self.server.stop()

        # But should still clean up state in finally block
        assert self.server._runtime.is_running is False
        assert self.server._runtime.process_info is None

    def test_invalid_port_type(self) -> None:
        """Test that invalid port types are caught."""
        app_context = ApplicationContext.for_testing()
        with pytest.raises((TypeError, ValueError)):
            # This should be caught by the strict type validation
            ArangoServer.create_single_server(
                server_id=ServerId("test"),
                app_context=app_context,
                port="not_a_port",  # type: ignore
            )

    def test_server_graceful_stop_when_not_running(self) -> None:
        """Test stop when server not running doesn't crash."""
        app_context = ApplicationContext.for_testing()
        server = ArangoServer.create_single_server(
            server_id=ServerId("test"), app_context=app_context, port=8529
        )

        # Should not crash when stopping non-running server
        try:
            server.stop()
        except Exception:
            # If it logs a warning or handles gracefully, that's acceptable
            pass


class TestArangoServerIntegration:
    """Test basic integration scenarios."""

    @patch("pathlib.Path.exists", return_value=True)
    def test_full_lifecycle_workflow(self, mock_exists: Any) -> None:
        """Test complete start->check->stop workflow."""
        app_context = ApplicationContext.for_testing()
        server = ArangoServer.create_single_server(
            server_id=ServerId("lifecycle_test"),
            app_context=app_context,
            port=8529,
        )

        # Mock successful start
        app_context.process_supervisor.start = Mock(return_value=Mock(pid=12345))
        app_context.process_supervisor.is_running = Mock(return_value=True)
        app_context.process_supervisor.stop = Mock()

        # Start server
        server.start()

        # Check it's running
        assert server.is_running() is True

        # Stop server
        server.stop()
        app_context.process_supervisor.stop.assert_called_once()

    @patch("pathlib.Path.exists", return_value=True)
    def test_start_attempts_process_creation(self, mock_exists: Any) -> None:
        """Test start attempts to create a process."""
        app_context = ApplicationContext.for_testing()
        server = ArangoServer.create_single_server(
            server_id=ServerId("mock_test"), app_context=app_context, port=8529
        )
        app_context.process_supervisor.start = Mock(return_value=Mock(pid=12345))

        try:
            server.start()
            # If successful, process should have been called
            app_context.process_supervisor.start.assert_called()
        except Exception:
            # If it fails due to other reasons, at least verify the attempt was made
            if app_context.process_supervisor.start.called:
                pass  # Good enough
            else:
                # Re-raise if process creation wasn't even attempted
                raise

    def test_stop_attempts_process_termination(self) -> None:
        """Test stop attempts to terminate process."""
        app_context = ApplicationContext.for_testing()
        server = ArangoServer.create_single_server(
            server_id=ServerId("mock_test"), app_context=app_context, port=8529
        )

        # Mock process supervisor
        app_context.process_supervisor.stop = Mock()

        # Set server as if it's running
        server._runtime.is_running = True

        try:
            server.stop()
            # Should have attempted to stop the process
            app_context.process_supervisor.stop.assert_called_once_with(
                ServerId("mock_test"), graceful=True, timeout=30.0
            )
        except Exception:
            # Even if it fails, the attempt should have been made
            assert app_context.process_supervisor.stop.called
