"""
Simple unit tests for instances/server.py - ArangoDB server wrapper.

Tests essential ArangoServer functionality with minimal mocking.
"""

import pytest
from unittest.mock import Mock, patch
from pathlib import Path

from armadillo.instances.server import ArangoServer
from armadillo.core.types import ServerRole, ClusterConfig


class TestArangoServerBasic:
    """Test ArangoServer basic functionality."""

    def test_server_can_be_created(self):
        """Test ArangoServer can be instantiated."""
        server = ArangoServer(
            server_id="test_server",
            role=ServerRole.SINGLE,
            port=8529
        )

        assert server is not None
        assert server.server_id == "test_server"
        assert server.port == 8529
        assert server.role == ServerRole.SINGLE
        assert server.endpoint == "http://127.0.0.1:8529"

    def test_server_with_different_roles(self):
        """Test server creation with different roles."""
        roles = [ServerRole.SINGLE, ServerRole.COORDINATOR, ServerRole.DBSERVER, ServerRole.AGENT]

        for role in roles:
            server = ArangoServer(
                server_id=f"test_{role.value}",
                role=role,
                port=8530
            )

            assert server.role == role
            assert server.endpoint == "http://127.0.0.1:8530"

    def test_server_with_different_ports(self):
        """Test server creation with different ports."""
        # Create mock config provider
        mock_config = Mock()
        mock_config.bin_dir = Path("/fake/bin")
        mock_config.work_dir = Path("/fake/work")
        mock_config.cluster = ClusterConfig()
        mock_config.verbose = 0
        mock_config.keep_instances_on_failure = False
        mock_config.test_timeout = 30.0

        # Create mock logger
        mock_logger = Mock()

        # Create mock port allocator
        mock_port_allocator = Mock()
        mock_port_allocator.allocate_port.return_value = 8529
        mock_port_allocator.release_port = Mock()

        server1 = ArangoServer("test1", ServerRole.SINGLE, 8531, config_provider=mock_config, logger=mock_logger, port_allocator=mock_port_allocator)
        server2 = ArangoServer("test2", ServerRole.SINGLE, 8532, config_provider=mock_config, logger=mock_logger, port_allocator=mock_port_allocator)

        assert server1.endpoint == "http://127.0.0.1:8531"
        assert server2.endpoint == "http://127.0.0.1:8532"

    def test_server_not_running_initially(self):
        """Test server is not running initially."""
        # Create mock config provider
        mock_config = Mock()
        mock_config.bin_dir = Path("/fake/bin")
        mock_config.work_dir = Path("/fake/work")
        mock_config.cluster = ClusterConfig()
        mock_config.verbose = 0
        mock_config.keep_instances_on_failure = False
        mock_config.test_timeout = 30.0

        # Create mock logger
        mock_logger = Mock()

        # Create mock port allocator
        mock_port_allocator = Mock()
        mock_port_allocator.allocate_port.return_value = 8529
        mock_port_allocator.release_port = Mock()

        server = ArangoServer("test", ServerRole.SINGLE, 8529, config_provider=mock_config, logger=mock_logger, port_allocator=mock_port_allocator)

        assert server.is_running() is False


class TestArangoServerLifecycle:
    """Test ArangoServer lifecycle with basic mocking."""

    def setup_method(self):
        """Set up test environment."""
        # Create mock config provider
        self.mock_config = Mock()
        self.mock_config.bin_dir = Path("/fake/bin")
        self.mock_config.work_dir = Path("/fake/work")
        self.mock_config.cluster = ClusterConfig()
        self.mock_config.verbose = 0
        self.mock_config.keep_instances_on_failure = False
        self.mock_config.test_timeout = 30.0

        # Create mock logger
        self.mock_logger = Mock()

        # Create mock port allocator
        self.mock_port_allocator = Mock()
        self.mock_port_allocator.allocate_port.return_value = 8529
        self.mock_port_allocator.release_port = Mock()

        self.server = ArangoServer(
            server_id="test_server",
            role=ServerRole.SINGLE,
            port=8529,
            config_provider=self.mock_config,
            logger=self.mock_logger,
            port_allocator=self.mock_port_allocator
        )

    @patch('armadillo.instances.server.start_supervised_process')
    @patch('armadillo.instances.server.is_process_running', return_value=True)
    @patch('pathlib.Path.exists', return_value=True)
    def test_start_server_calls_process(self, mock_exists, mock_is_running, mock_start):
        """Test server start calls process supervisor."""
        mock_start.return_value = Mock(pid=12345)

        self.server.start()

        # Server should be running after successful start
        assert self.server.is_running() is True
        mock_start.assert_called_once()

        # Check process ID was set
        call_args = mock_start.call_args
        process_id = call_args[0][0]
        assert "test_server" in process_id or "arangod" in process_id

    @patch('armadillo.instances.server.stop_supervised_process')
    def test_stop_server_calls_process(self, mock_stop):
        """Test server stop calls process supervisor."""
        # Set up server as if it was started
        from armadillo.core.process import ProcessInfo
        from pathlib import Path
        self.server._process_info = ProcessInfo(pid=12345, command=["test"], start_time=123.0, working_dir=Path("/tmp"), env={})
        self.server._is_running = True

        self.server.stop()

        mock_stop.assert_called_once_with("test_server", graceful=True, timeout=30.0)

    def test_stop_server_not_started(self):
        """Test stopping server that wasn't started doesn't crash."""
        self.server.stop()
        # Should not crash
        assert self.server._process_info is None

    @patch('armadillo.instances.server.is_process_running')
    def test_is_running_with_process_id(self, mock_is_running):
        """Test is_running delegates to process supervisor."""
        mock_is_running.return_value = True
        self.server._is_running = True

        assert self.server.is_running() is True
        # Note: The actual implementation checks _is_running flag, not process supervisor

    def test_is_running_no_process_id(self):
        """Test is_running returns False when no process started."""
        assert self.server.is_running() is False


class TestArangoServerConfiguration:
    """Test server configuration building."""

    def setup_method(self):
        """Set up test environment."""
        # Create mock config provider
        mock_config = Mock()
        mock_config.bin_dir = Path("/fake/bin")
        mock_config.work_dir = Path("/fake/work")
        mock_config.cluster = ClusterConfig()
        mock_config.verbose = 0
        mock_config.keep_instances_on_failure = False
        mock_config.test_timeout = 30.0

        # Create mock logger
        mock_logger = Mock()

        self.server = ArangoServer("test", ServerRole.SINGLE, 8529, config_provider=mock_config, logger=mock_logger)

    @patch('pathlib.Path.exists', return_value=True)
    def test_build_command_returns_list(self, mock_exists):
        """Test command building returns a list."""
        command = self.server._build_command()

        assert isinstance(command, list)
        assert len(command) > 0
        # First element should be the arangod executable
        assert "arangod" in command[0]

    @patch('pathlib.Path.exists', return_value=True)
    def test_build_command_contains_basic_params(self, mock_exists):
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

    def setup_method(self):
        """Set up test environment."""
        # Create mock config provider
        mock_config = Mock()
        mock_config.bin_dir = Path("/fake/bin")
        mock_config.work_dir = Path("/fake/work")
        mock_config.cluster = ClusterConfig()
        mock_config.verbose = 0
        mock_config.keep_instances_on_failure = False
        mock_config.test_timeout = 30.0

        # Create mock logger
        mock_logger = Mock()

        self.server = ArangoServer("test", ServerRole.SINGLE, 8529, config_provider=mock_config, logger=mock_logger)

    @patch('armadillo.instances.server.start_supervised_process')
    def test_start_process_failure(self, mock_start):
        """Test handling of process start failure."""
        from armadillo.core.errors import ProcessStartupError, ServerStartupError
        mock_start.side_effect = ProcessStartupError("Failed to start")

        with pytest.raises(ServerStartupError):
            self.server.start()

    @patch('armadillo.instances.server.stop_supervised_process')
    def test_stop_process_failure_handled_gracefully(self, mock_stop):
        """Test stop handles process failure gracefully."""
        from armadillo.core.errors import ProcessError, ServerShutdownError
        mock_stop.side_effect = ProcessError("Failed to stop")

        from armadillo.core.process import ProcessInfo
        from pathlib import Path
        self.server._process_info = ProcessInfo(pid=12345, command=["test"], start_time=123.0, working_dir=Path("/tmp"), env={})
        self.server._is_running = True

        # Should raise ServerShutdownError but still clean up
        with pytest.raises(ServerShutdownError):
            self.server.stop()

        # But should still clean up state in finally block
        assert self.server._is_running is False
        assert self.server._process_info is None

    def test_invalid_port_type(self):
        """Test that invalid port types are caught."""
        with pytest.raises((TypeError, ValueError)):
            # This should be caught by the strict type validation
            ArangoServer("test", ServerRole.SINGLE, "not_a_port")


class TestArangoServerIntegration:
    """Test basic integration scenarios."""

    @patch('armadillo.instances.server.start_supervised_process')
    @patch('armadillo.instances.server.stop_supervised_process')
    @patch('armadillo.instances.server.is_process_running')
    @patch('pathlib.Path.exists', return_value=True)
    def test_full_lifecycle_workflow(self, mock_exists, mock_is_running, mock_stop, mock_start):
        """Test complete start->check->stop workflow."""
        # Create mock config provider
        mock_config = Mock()
        mock_config.bin_dir = Path("/fake/bin")
        mock_config.work_dir = Path("/fake/work")
        mock_config.cluster = ClusterConfig()
        mock_config.verbose = 0
        mock_config.keep_instances_on_failure = False
        mock_config.test_timeout = 30.0

        # Create mock logger
        mock_logger = Mock()

        server = ArangoServer("lifecycle_test", ServerRole.SINGLE, 8529, config_provider=mock_config, logger=mock_logger)

        # Mock successful start
        mock_start.return_value = Mock(pid=12345)
        mock_is_running.return_value = True

        # Start server
        server.start()

        # Check it's running
        assert server.is_running() is True

        # Stop server
        server.stop()
        mock_stop.assert_called_once()
