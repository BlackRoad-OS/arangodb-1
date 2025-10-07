"""Unit tests for ServerRegistry."""

import pytest
from unittest.mock import Mock
from armadillo.instances.server_registry import ServerRegistry
from armadillo.core.types import ServerRole


class TestServerRegistry:
    """Test ServerRegistry basic functionality."""

    def test_register_and_get_server(self):
        """Test registering and retrieving a server."""
        registry = ServerRegistry()
        mock_server = Mock()
        mock_server.role = ServerRole.SINGLE

        registry.register_server("server1", mock_server)

        assert registry.get_server("server1") == mock_server
        assert registry.count() == 1

    def test_register_duplicate_server_raises_error(self):
        """Test that registering duplicate server ID raises ValueError."""
        registry = ServerRegistry()
        mock_server1 = Mock()
        mock_server2 = Mock()

        registry.register_server("server1", mock_server1)

        with pytest.raises(ValueError, match="already registered"):
            registry.register_server("server1", mock_server2)

    def test_get_nonexistent_server_returns_none(self):
        """Test getting a non-existent server returns None."""
        registry = ServerRegistry()

        assert registry.get_server("nonexistent") is None

    def test_unregister_server(self):
        """Test unregistering a server."""
        registry = ServerRegistry()
        mock_server = Mock()

        registry.register_server("server1", mock_server)
        removed = registry.unregister_server("server1")

        assert removed == mock_server
        assert registry.get_server("server1") is None
        assert registry.count() == 0

    def test_unregister_nonexistent_server_returns_none(self):
        """Test unregistering non-existent server returns None."""
        registry = ServerRegistry()

        assert registry.unregister_server("nonexistent") is None

    def test_get_all_servers(self):
        """Test getting all servers."""
        registry = ServerRegistry()
        mock_server1 = Mock()
        mock_server2 = Mock()

        registry.register_server("server1", mock_server1)
        registry.register_server("server2", mock_server2)

        all_servers = registry.get_all_servers()

        assert len(all_servers) == 2
        assert all_servers["server1"] == mock_server1
        assert all_servers["server2"] == mock_server2

    def test_get_servers_by_role(self):
        """Test filtering servers by role."""
        registry = ServerRegistry()

        agent1 = Mock()
        agent1.role = ServerRole.AGENT
        agent2 = Mock()
        agent2.role = ServerRole.AGENT
        coordinator = Mock()
        coordinator.role = ServerRole.COORDINATOR

        registry.register_server("agent1", agent1)
        registry.register_server("agent2", agent2)
        registry.register_server("coord1", coordinator)

        agents = registry.get_servers_by_role(ServerRole.AGENT)
        coordinators = registry.get_servers_by_role(ServerRole.COORDINATOR)

        assert len(agents) == 2
        assert agent1 in agents
        assert agent2 in agents
        assert len(coordinators) == 1
        assert coordinator in coordinators

    def test_get_server_ids_by_role(self):
        """Test getting server IDs by role."""
        registry = ServerRegistry()

        agent = Mock()
        agent.role = ServerRole.AGENT
        coordinator = Mock()
        coordinator.role = ServerRole.COORDINATOR

        registry.register_server("agent1", agent)
        registry.register_server("coord1", coordinator)

        agent_ids = registry.get_server_ids_by_role(ServerRole.AGENT)

        assert agent_ids == ["agent1"]

    def test_get_endpoints_by_role(self):
        """Test getting endpoints by role."""
        registry = ServerRegistry()

        agent1 = Mock()
        agent1.role = ServerRole.AGENT
        agent1.get_endpoint.return_value = "http://localhost:8529"

        agent2 = Mock()
        agent2.role = ServerRole.AGENT
        agent2.get_endpoint.return_value = "http://localhost:8539"

        coordinator = Mock()
        coordinator.role = ServerRole.COORDINATOR
        coordinator.get_endpoint.return_value = "http://localhost:8549"

        registry.register_server("agent1", agent1)
        registry.register_server("agent2", agent2)
        registry.register_server("coord1", coordinator)

        agent_endpoints = registry.get_endpoints_by_role(ServerRole.AGENT)

        assert len(agent_endpoints) == 2
        assert "http://localhost:8529" in agent_endpoints
        assert "http://localhost:8539" in agent_endpoints

    def test_has_server(self):
        """Test checking if server exists."""
        registry = ServerRegistry()
        mock_server = Mock()

        assert not registry.has_server("server1")

        registry.register_server("server1", mock_server)

        assert registry.has_server("server1")

    def test_count_by_role(self):
        """Test counting servers by role."""
        registry = ServerRegistry()

        agent1 = Mock()
        agent1.role = ServerRole.AGENT
        agent2 = Mock()
        agent2.role = ServerRole.AGENT
        coordinator = Mock()
        coordinator.role = ServerRole.COORDINATOR

        registry.register_server("agent1", agent1)
        registry.register_server("agent2", agent2)
        registry.register_server("coord1", coordinator)

        assert registry.count_by_role(ServerRole.AGENT) == 2
        assert registry.count_by_role(ServerRole.COORDINATOR) == 1
        assert registry.count_by_role(ServerRole.DBSERVER) == 0

    def test_clear(self):
        """Test clearing all servers."""
        registry = ServerRegistry()

        registry.register_server("server1", Mock())
        registry.register_server("server2", Mock())

        assert registry.count() == 2

        registry.clear()

        assert registry.count() == 0
        assert registry.get_all_servers() == {}

    def test_get_server_ids(self):
        """Test getting all server IDs."""
        registry = ServerRegistry()

        registry.register_server("server1", Mock())
        registry.register_server("server2", Mock())

        server_ids = registry.get_server_ids()

        assert len(server_ids) == 2
        assert "server1" in server_ids
        assert "server2" in server_ids


class TestServerRegistryIntegration:
    """Test ServerRegistry integration scenarios."""

    def test_mixed_operations(self):
        """Test mixed registration, lookup, and unregistration."""
        registry = ServerRegistry()

        # Register servers of different roles
        agent = Mock()
        agent.role = ServerRole.AGENT
        agent.get_endpoint.return_value = "http://localhost:8529"

        coordinator = Mock()
        coordinator.role = ServerRole.COORDINATOR
        coordinator.get_endpoint.return_value = "http://localhost:8539"

        dbserver = Mock()
        dbserver.role = ServerRole.DBSERVER
        dbserver.get_endpoint.return_value = "http://localhost:8549"

        # Register
        registry.register_server("agent1", agent)
        registry.register_server("coord1", coordinator)
        registry.register_server("db1", dbserver)

        # Verify count and queries work
        assert registry.count() == 3
        assert len(registry.get_servers_by_role(ServerRole.AGENT)) == 1
        assert len(registry.get_servers_by_role(ServerRole.COORDINATOR)) == 1
        assert len(registry.get_servers_by_role(ServerRole.DBSERVER)) == 1

        # Unregister one
        removed = registry.unregister_server("coord1")
        assert removed == coordinator
        assert registry.count() == 2

        # Verify queries updated
        assert len(registry.get_servers_by_role(ServerRole.COORDINATOR)) == 0
        assert len(registry.get_endpoints_by_role(ServerRole.AGENT)) == 1
