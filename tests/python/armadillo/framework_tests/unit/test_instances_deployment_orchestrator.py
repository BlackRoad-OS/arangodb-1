"""Unit tests for DeploymentOrchestrator."""

import pytest
from unittest.mock import Mock, patch
from armadillo.instances.deployment_orchestrator import DeploymentOrchestrator
from armadillo.core.types import DeploymentMode, ServerRole
from armadillo.core.errors import ServerError, ClusterError


class TestDeploymentOrchestrator:
    """Test DeploymentOrchestrator functionality."""

    def test_init(self):
        """Test DeploymentOrchestrator initialization."""
        mock_logger = Mock()
        mock_factory = Mock()
        mock_registry = Mock()

        orchestrator = DeploymentOrchestrator(mock_logger, mock_factory, mock_registry)

        assert orchestrator._logger == mock_logger
        assert orchestrator._server_factory == mock_factory
        assert orchestrator._server_registry == mock_registry

    def test_create_servers_from_plan(self):
        """Test creating servers from deployment plan."""
        mock_logger = Mock()
        mock_factory = Mock()
        mock_registry = Mock()

        orchestrator = DeploymentOrchestrator(mock_logger, mock_factory, mock_registry)

        # Create mock plan
        mock_plan = Mock()
        mock_config1 = Mock()
        mock_config1.role = ServerRole.SINGLE
        mock_plan.servers = [mock_config1]

        # Mock server creation - factory returns dict of servers
        mock_server = Mock()
        mock_server.role = ServerRole.SINGLE
        mock_factory.create_server_instances.return_value = {"server1": mock_server}

        orchestrator._create_servers_from_plan(mock_plan)

        # Verify factory was called with server configs
        mock_factory.create_server_instances.assert_called_once_with([mock_config1])
        # Verify server was registered
        mock_registry.register_server.assert_called_once_with("server1", mock_server)

    def test_start_single_server(self):
        """Test starting single server."""
        mock_logger = Mock()
        mock_factory = Mock()
        mock_registry = Mock()

        orchestrator = DeploymentOrchestrator(mock_logger, mock_factory, mock_registry)

        # Mock single server
        mock_server = Mock()
        mock_server.server_id = "server1"
        mock_registry.get_all_servers.return_value = {"server1": mock_server}

        orchestrator._start_single_server(timeout=60.0)

        # Verify server was started
        mock_server.start.assert_called_once_with(timeout=60.0)
        assert orchestrator.get_startup_order() == ["server1"]

    def test_start_single_server_wrong_count(self):
        """Test starting single server with wrong server count."""
        mock_logger = Mock()
        mock_factory = Mock()
        mock_registry = Mock()

        orchestrator = DeploymentOrchestrator(mock_logger, mock_factory, mock_registry)

        # Mock multiple servers (wrong for single mode)
        mock_registry.get_all_servers.return_value = {"s1": Mock(), "s2": Mock()}

        with pytest.raises(ServerError, match="Expected 1 server"):
            orchestrator._start_single_server(timeout=60.0)

    def test_start_cluster_without_bootstrapper(self):
        """Test starting cluster without bootstrapper."""
        mock_logger = Mock()
        mock_factory = Mock()
        mock_registry = Mock()

        orchestrator = DeploymentOrchestrator(mock_logger, mock_factory, mock_registry)

        with pytest.raises(ClusterError, match="ClusterBootstrapper required"):
            orchestrator._start_cluster(timeout=60.0)

    def test_start_cluster_with_bootstrapper(self):
        """Test starting cluster with bootstrapper."""
        mock_logger = Mock()
        mock_factory = Mock()
        mock_registry = Mock()
        mock_bootstrapper = Mock()

        orchestrator = DeploymentOrchestrator(
            mock_logger,
            mock_factory,
            mock_registry,
            cluster_bootstrapper=mock_bootstrapper,
        )

        # Mock cluster servers
        servers = {"agent1": Mock(), "db1": Mock(), "coord1": Mock()}
        mock_registry.get_all_servers.return_value = servers

        orchestrator._start_cluster(timeout=300.0)

        # Verify bootstrapper was called
        mock_bootstrapper.bootstrap_cluster.assert_called_once()
        call_args = mock_bootstrapper.bootstrap_cluster.call_args
        assert call_args[0][0] == servers  # First arg is servers dict

    def test_shutdown_deployment(self):
        """Test shutting down deployment."""
        mock_logger = Mock()
        mock_factory = Mock()
        mock_registry = Mock()

        orchestrator = DeploymentOrchestrator(mock_logger, mock_factory, mock_registry)
        orchestrator._startup_order = ["server1", "server2"]

        # Mock servers
        server1 = Mock()
        server1.server_id = "server1"
        server1.role = ServerRole.COORDINATOR
        server2 = Mock()
        server2.server_id = "server2"
        server2.role = ServerRole.DBSERVER

        mock_registry.get_all_servers.return_value = {
            "server1": server1,
            "server2": server2,
        }

        orchestrator.shutdown_deployment(timeout=120.0)

        # Verify both servers were stopped
        server1.stop.assert_called_once()
        server2.stop.assert_called_once()

        # Verify registry was cleared
        mock_registry.clear.assert_called_once()
        assert orchestrator.get_startup_order() == []

    def test_shutdown_deployment_agents_last(self):
        """Test shutdown orders agents last."""
        mock_logger = Mock()
        mock_factory = Mock()
        mock_registry = Mock()

        orchestrator = DeploymentOrchestrator(mock_logger, mock_factory, mock_registry)
        orchestrator._startup_order = ["agent1", "db1", "coord1"]

        # Mock cluster servers
        agent = Mock()
        agent.server_id = "agent1"
        agent.role = ServerRole.AGENT
        db = Mock()
        db.server_id = "db1"
        db.role = ServerRole.DBSERVER
        coord = Mock()
        coord.server_id = "coord1"
        coord.role = ServerRole.COORDINATOR

        stop_order = []
        agent.stop.side_effect = lambda **kw: stop_order.append("agent1")
        db.stop.side_effect = lambda **kw: stop_order.append("db1")
        coord.stop.side_effect = lambda **kw: stop_order.append("coord1")

        mock_registry.get_all_servers.return_value = {
            "agent1": agent,
            "db1": db,
            "coord1": coord,
        }

        orchestrator.shutdown_deployment(timeout=120.0)

        # Verify agent was stopped last
        assert stop_order[-1] == "agent1"
        assert "db1" in stop_order or "coord1" in stop_order

    def test_execute_deployment_single_server(self):
        """Test executing single server deployment."""
        mock_logger = Mock()
        mock_factory = Mock()
        mock_registry = Mock()

        orchestrator = DeploymentOrchestrator(mock_logger, mock_factory, mock_registry)

        # Create mock plan
        mock_plan = Mock()
        mock_plan.deployment_mode = DeploymentMode.SINGLE_SERVER
        mock_config = Mock()
        mock_config.role = ServerRole.SINGLE
        mock_plan.servers = [mock_config]

        # Mock server
        mock_server = Mock()
        mock_server.server_id = "server1"
        mock_factory.create_server_instances.return_value = {"server1": mock_server}
        mock_registry.get_all_servers.return_value = {"server1": mock_server}

        orchestrator.execute_deployment(mock_plan, timeout=300.0)

        # Verify server was created and started
        mock_factory.create_server_instances.assert_called_once()
        mock_server.start.assert_called_once()

    def test_execute_deployment_with_health_check(self):
        """Test executing deployment with health monitoring."""
        mock_logger = Mock()
        mock_factory = Mock()
        mock_registry = Mock()
        mock_health_monitor = Mock()

        orchestrator = DeploymentOrchestrator(
            mock_logger, mock_factory, mock_registry, health_monitor=mock_health_monitor
        )

        # Create mock plan
        mock_plan = Mock()
        mock_plan.deployment_mode = DeploymentMode.SINGLE_SERVER
        mock_config = Mock()
        mock_config.role = ServerRole.SINGLE
        mock_plan.servers = [mock_config]

        # Mock server and health
        mock_server = Mock()
        mock_factory.create_server_instances.return_value = {"server1": mock_server}
        mock_registry.get_all_servers.return_value = {"server1": mock_server}

        mock_health_status = Mock()
        mock_health_status.is_healthy = True
        mock_health_monitor.check_deployment_health.return_value = mock_health_status

        orchestrator.execute_deployment(mock_plan, timeout=300.0)

        # Verify health check was performed
        mock_health_monitor.check_deployment_health.assert_called_once()
