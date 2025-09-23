"""Unit tests for StandardServerFactory."""

import pytest
from pathlib import Path
from unittest.mock import Mock

from armadillo.core.types import ServerRole, ServerConfig
from armadillo.core.errors import ServerError
from armadillo.instances.server_factory import StandardServerFactory


class TestStandardServerFactory:
    """Test server factory functionality."""

    def setup_method(self):
        """Set up test environment."""
        # Create mock config provider
        self.mock_config = Mock()
        self.mock_config.bin_dir = Path("/fake/bin")

        # Create mock logger
        self.mock_logger = Mock()

        # Create mock port allocator
        self.mock_port_allocator = Mock()

        self.factory = StandardServerFactory(
            config_provider=self.mock_config,
            logger=self.mock_logger,
            port_allocator=self.mock_port_allocator
        )

    def test_create_single_server_instance(self):
        """Test creating a single server instance."""
        server_config = ServerConfig(
            role=ServerRole.SINGLE,
            port=8529,
            data_dir=Path("/fake/data"),
            log_file=Path("/fake/log"),
            args={"test": "value"}
        )

        servers = self.factory.create_server_instances([server_config])

        assert len(servers) == 1
        assert "server_0" in servers

        server = servers["server_0"]
        assert server.server_id == "server_0"
        assert server.role == ServerRole.SINGLE
        assert server.port == 8529
        assert server.data_dir == Path("/fake/data")
        assert server.log_file == Path("/fake/log")

        # Verify debug logging
        self.mock_logger.debug.assert_called_with(
            "Created server instance %s with role %s on port %s", "server_0", "single", 8529
        )

    def test_create_cluster_instances(self):
        """Test creating multiple server instances for a cluster."""
        servers_config = [
            ServerConfig(
                role=ServerRole.AGENT,
                port=8530,
                data_dir=Path("/fake/agent/data"),
                log_file=Path("/fake/agent/log"),
                args={"agency.activate": "true"}
            ),
            ServerConfig(
                role=ServerRole.DBSERVER,
                port=8531,
                data_dir=Path("/fake/db/data"),
                log_file=Path("/fake/db/log"),
                args={"cluster.my-role": "PRIMARY"}
            ),
            ServerConfig(
                role=ServerRole.COORDINATOR,
                port=8532,
                data_dir=Path("/fake/coord/data"),
                log_file=Path("/fake/coord/log"),
                args={"cluster.my-role": "COORDINATOR"}
            )
        ]

        servers = self.factory.create_server_instances(servers_config)

        assert len(servers) == 3
        assert "agent_0" in servers
        assert "dbserver_1" in servers
        assert "coordinator_2" in servers

        # Check agent
        agent = servers["agent_0"]
        assert agent.role == ServerRole.AGENT
        assert agent.port == 8530

        # Check dbserver
        dbserver = servers["dbserver_1"]
        assert dbserver.role == ServerRole.DBSERVER
        assert dbserver.port == 8531

        # Check coordinator
        coordinator = servers["coordinator_2"]
        assert coordinator.role == ServerRole.COORDINATOR
        assert coordinator.port == 8532

        # Should have logged creation of all 3 servers
        assert self.mock_logger.debug.call_count == 3

    def test_generate_server_id(self):
        """Test server ID generation for different roles."""
        assert self.factory._generate_server_id(ServerRole.AGENT, 0) == "agent_0"
        assert self.factory._generate_server_id(ServerRole.AGENT, 2) == "agent_2"
        assert self.factory._generate_server_id(ServerRole.DBSERVER, 1) == "dbserver_1"
        assert self.factory._generate_server_id(ServerRole.COORDINATOR, 3) == "coordinator_3"
        assert self.factory._generate_server_id(ServerRole.SINGLE, 0) == "server_0"

    def test_invalid_port_type_error(self):
        """Test error handling for invalid port types."""
        server_config = ServerConfig(
            role=ServerRole.SINGLE,
            port="invalid_port",  # String instead of int
            data_dir=Path("/fake/data"),
            log_file=Path("/fake/log")
        )

        with pytest.raises(ServerError, match="Invalid port type for server_0.*expected int"):
            self.factory.create_server_instances([server_config])

    def test_minimal_config_creation(self):
        """Test that MinimalConfig is created with correct values."""
        server_config = ServerConfig(
            role=ServerRole.SINGLE,
            port=8529,
            data_dir=Path("/fake/data"),
            log_file=Path("/fake/log"),
            args={"custom": "arg", "memory": "1G"},
            memory_limit_mb=512,
            startup_timeout=45.0
        )

        servers = self.factory.create_server_instances([server_config])
        server = servers["server_0"]

        # Check that the minimal config was passed correctly
        # We can't directly access it, but we can verify the server was created successfully
        assert server.server_id == "server_0"
        assert server.paths.config.args["custom"] == "arg"

        # Verify that data_dir and log_file from ServerConfig are preserved
        assert server.paths.data_dir == Path("/fake/data")
        assert server.paths.log_file == Path("/fake/log")
        assert server.paths.config.args["memory"] == "1G"
        assert server.paths.config.memory_limit_mb == 512
        assert server.paths.config.startup_timeout == 45.0

    def test_post_creation_configuration(self):
        """Test that servers are configured after creation."""
        server_config = ServerConfig(
            role=ServerRole.SINGLE,
            port=8529,
            data_dir=Path("/custom/data/dir"),
            log_file=Path("/custom/log/file.log")
        )

        servers = self.factory.create_server_instances([server_config])
        server = servers["server_0"]

        # Check that directories were set
        assert server.data_dir == Path("/custom/data/dir")
        assert server.log_file == Path("/custom/log/file.log")

        # Check that ServerConfig was stored for reference
        assert hasattr(server, '_server_config')
        assert server._server_config == server_config

    def test_dependency_creation(self):
        """Test that dependencies are created for each server."""
        server_config = ServerConfig(
            role=ServerRole.SINGLE,
            port=8529,
            data_dir=Path("/fake/data"),
            log_file=Path("/fake/log")
        )

        servers = self.factory.create_server_instances([server_config])
        server = servers["server_0"]

        # Check that server has the expected dependencies
        # These are tested by verifying the server was created successfully with all required components
        assert server._command_builder is not None
        assert server._health_checker is not None
        assert server._config_provider == self.mock_config
        assert server._logger == self.mock_logger

    def test_empty_server_list(self):
        """Test handling empty server configuration list."""
        servers = self.factory.create_server_instances([])

        assert len(servers) == 0
        assert isinstance(servers, dict)

        # Should not have logged any server creation
        self.mock_logger.debug.assert_not_called()

    def test_server_factory_protocol_compliance(self):
        """Test that StandardServerFactory implements ServerFactory protocol."""
        # This test verifies that the class implements the expected interface
        assert hasattr(self.factory, 'create_server_instances')
        assert callable(self.factory.create_server_instances)

    def test_multiple_agents_indexing(self):
        """Test that multiple servers of same role get proper indexing."""
        servers_config = [
            ServerConfig(role=ServerRole.AGENT, port=8530, data_dir=Path("/agent0"), log_file=Path("/log0")),
            ServerConfig(role=ServerRole.AGENT, port=8531, data_dir=Path("/agent1"), log_file=Path("/log1")),
            ServerConfig(role=ServerRole.AGENT, port=8532, data_dir=Path("/agent2"), log_file=Path("/log2"))
        ]

        servers = self.factory.create_server_instances(servers_config)

        assert len(servers) == 3
        assert "agent_0" in servers
        assert "agent_1" in servers
        assert "agent_2" in servers

        # Check that they have different ports as expected
        assert servers["agent_0"].port == 8530
        assert servers["agent_1"].port == 8531
        assert servers["agent_2"].port == 8532

    def test_args_copying(self):
        """Test that server config args are properly copied."""
        server_config = ServerConfig(
            role=ServerRole.SINGLE,
            port=8529,
            data_dir=Path("/fake/data"),
            log_file=Path("/fake/log"),
            args={"original": "value"}
        )

        servers = self.factory.create_server_instances([server_config])
        server = servers["server_0"]

        # Original args should be copied, not referenced
        assert server.paths.config.args == {"original": "value"}

        # Modifying server config args should not affect original
        server.paths.config.args["modified"] = "new_value"
        assert "modified" not in server_config.args
