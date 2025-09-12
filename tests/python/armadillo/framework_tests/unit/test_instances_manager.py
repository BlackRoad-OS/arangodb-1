"""Tests for InstanceManager cluster deployment functionality."""

import pytest
import time
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from concurrent.futures import ThreadPoolExecutor

from armadillo.instances.manager import (
    InstanceManager, DeploymentPlan, get_instance_manager, cleanup_instance_managers
)
from armadillo.core.types import (
    DeploymentMode, ServerRole, ServerConfig, ClusterConfig
)
from armadillo.core.errors import (
    ServerError, ServerStartupError, ServerShutdownError,
    HealthCheckError, AgencyError
)


class TestDeploymentPlan:
    """Test DeploymentPlan dataclass."""

    def test_deployment_plan_creation(self):
        """Test DeploymentPlan creation."""
        plan = DeploymentPlan(deployment_mode=DeploymentMode.SINGLE_SERVER)

        assert plan.deployment_mode == DeploymentMode.SINGLE_SERVER
        assert len(plan.servers) == 0
        assert len(plan.coordination_endpoints) == 0
        assert len(plan.agency_endpoints) == 0

    def test_get_agents(self):
        """Test getting agent servers from plan."""
        plan = DeploymentPlan(deployment_mode=DeploymentMode.CLUSTER)

        # Add servers with different roles
        agent1 = ServerConfig(ServerRole.AGENT, 8531, Path("/tmp/agent1"), Path("/tmp/agent1.log"))
        agent2 = ServerConfig(ServerRole.AGENT, 8532, Path("/tmp/agent2"), Path("/tmp/agent2.log"))
        coord = ServerConfig(ServerRole.COORDINATOR, 8529, Path("/tmp/coord"), Path("/tmp/coord.log"))

        plan.servers = [agent1, coord, agent2]

        agents = plan.get_agents()
        assert len(agents) == 2
        assert agent1 in agents
        assert agent2 in agents
        assert coord not in agents

    def test_get_coordinators(self):
        """Test getting coordinator servers from plan."""
        plan = DeploymentPlan(deployment_mode=DeploymentMode.CLUSTER)

        agent = ServerConfig(ServerRole.AGENT, 8531, Path("/tmp/agent"), Path("/tmp/agent.log"))
        coord1 = ServerConfig(ServerRole.COORDINATOR, 8529, Path("/tmp/coord1"), Path("/tmp/coord1.log"))
        coord2 = ServerConfig(ServerRole.COORDINATOR, 8530, Path("/tmp/coord2"), Path("/tmp/coord2.log"))

        plan.servers = [agent, coord1, coord2]

        coordinators = plan.get_coordinators()
        assert len(coordinators) == 2
        assert coord1 in coordinators
        assert coord2 in coordinators
        assert agent not in coordinators

    def test_get_dbservers(self):
        """Test getting database servers from plan."""
        plan = DeploymentPlan(deployment_mode=DeploymentMode.CLUSTER)

        agent = ServerConfig(ServerRole.AGENT, 8531, Path("/tmp/agent"), Path("/tmp/agent.log"))
        db1 = ServerConfig(ServerRole.DBSERVER, 8540, Path("/tmp/db1"), Path("/tmp/db1.log"))
        db2 = ServerConfig(ServerRole.DBSERVER, 8541, Path("/tmp/db2"), Path("/tmp/db2.log"))

        plan.servers = [agent, db1, db2]

        dbservers = plan.get_dbservers()
        assert len(dbservers) == 2
        assert db1 in dbservers
        assert db2 in dbservers
        assert agent not in dbservers


class TestInstanceManager:
    """Test InstanceManager functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.deployment_id = "test_deployment"

    def test_instance_manager_creation(self):
        """Test InstanceManager creation."""
        manager = InstanceManager(self.deployment_id)

        assert manager.deployment_id == self.deployment_id
        assert manager._deployment_plan is None
        assert len(manager._servers) == 0
        assert not manager._is_deployed
        assert not manager._is_healthy

    def test_context_manager_support(self):
        """Test context manager functionality."""
        with patch.object(InstanceManager, 'shutdown_deployment') as mock_shutdown:
            manager = InstanceManager(self.deployment_id)
            manager._is_deployed = True

            with manager as mgr:
                assert mgr is manager

            mock_shutdown.assert_called_once()

    def test_create_deployment_plan_single_server(self):
        """Test creating single server deployment plan."""
        manager = InstanceManager(self.deployment_id)

        with patch.object(manager.port_manager, 'allocate_port', return_value=8529):
            with patch('armadillo.instances.manager.server_dir') as mock_server_dir:
                mock_server_dir.return_value = Path("/tmp/servers")

                plan = manager.create_deployment_plan(DeploymentMode.SINGLE_SERVER)

                assert plan.deployment_mode == DeploymentMode.SINGLE_SERVER
                assert len(plan.servers) == 1
                assert plan.servers[0].role == ServerRole.SINGLE
                assert plan.servers[0].port == 8529
                assert len(plan.coordination_endpoints) == 1
                assert plan.coordination_endpoints[0] == "http://127.0.0.1:8529"

    def test_create_deployment_plan_cluster(self):
        """Test creating cluster deployment plan."""
        manager = InstanceManager(self.deployment_id)
        cluster_config = ClusterConfig(agents=3, dbservers=2, coordinators=1)

        ports = [8531, 8532, 8533, 8540, 8541, 8529]  # agents, dbservers, coordinators

        with patch.object(manager.port_manager, 'allocate_port', side_effect=ports):
            with patch('armadillo.instances.manager.server_dir') as mock_server_dir:
                mock_server_dir.return_value = Path("/tmp/servers")

                plan = manager.create_deployment_plan(DeploymentMode.CLUSTER, cluster_config)

                assert plan.deployment_mode == DeploymentMode.CLUSTER
                assert len(plan.servers) == 6  # 3 agents + 2 dbservers + 1 coordinator

                agents = plan.get_agents()
                dbservers = plan.get_dbservers()
                coordinators = plan.get_coordinators()

                assert len(agents) == 3
                assert len(dbservers) == 2
                assert len(coordinators) == 1

                assert len(plan.agency_endpoints) == 3
                assert len(plan.coordination_endpoints) == 1

    def test_create_deployment_plan_invalid_mode(self):
        """Test creating deployment plan with invalid mode."""
        manager = InstanceManager(self.deployment_id)

        with pytest.raises(ValueError, match="Unsupported deployment mode"):
            manager.create_deployment_plan("invalid_mode")

    @patch('armadillo.instances.manager.ArangoServer')
    def test_create_server_instances(self, mock_arango_server):
        """Test creating ArangoServer instances from plan."""
        manager = InstanceManager(self.deployment_id)

        # Create a mock deployment plan
        plan = DeploymentPlan(deployment_mode=DeploymentMode.SINGLE_SERVER)
        server_config = ServerConfig(
            ServerRole.SINGLE, 8529,
            Path("/tmp/data"), Path("/tmp/log.txt")
        )
        plan.servers = [server_config]
        manager._deployment_plan = plan

        mock_server = Mock()
        mock_arango_server.return_value = mock_server

        with patch('armadillo.instances.manager.ensure_dir'):
            manager._create_server_instances()

            assert len(manager._servers) == 1
            assert "single_0" in manager._servers
            assert manager._servers["single_0"] is mock_server

            mock_arango_server.assert_called_once()

    def test_deploy_servers_no_plan(self):
        """Test deploying servers without a plan."""
        manager = InstanceManager(self.deployment_id)

        with pytest.raises(ServerError, match="No deployment plan created"):
            manager.deploy_servers()

    def test_deploy_servers_already_deployed(self):
        """Test deploying servers when already deployed."""
        manager = InstanceManager(self.deployment_id)
        manager._is_deployed = True
        manager._deployment_plan = DeploymentPlan(DeploymentMode.SINGLE_SERVER)

        with pytest.raises(ServerError, match="Deployment already active"):
            manager.deploy_servers()

    @patch('armadillo.instances.manager.ArangoServer')
    def test_start_single_server(self, mock_arango_server):
        """Test starting single server deployment."""
        manager = InstanceManager(self.deployment_id)

        mock_server = Mock()
        mock_server.start = Mock()
        mock_arango_server.return_value = mock_server

        manager._servers = {"single_0": mock_server}

        manager._start_single_server()

        mock_server.start.assert_called_once_with(timeout=60.0)
        assert manager._startup_order == ["single_0"]

    def test_get_server(self):
        """Test getting server by ID."""
        manager = InstanceManager(self.deployment_id)
        mock_server = Mock()
        manager._servers = {"test_server": mock_server}

        result = manager.get_server("test_server")
        assert result is mock_server

        result = manager.get_server("nonexistent")
        assert result is None

    def test_get_servers_by_role(self):
        """Test getting servers by role."""
        manager = InstanceManager(self.deployment_id)

        coordinator1 = Mock()
        coordinator1.role = ServerRole.COORDINATOR
        coordinator2 = Mock()
        coordinator2.role = ServerRole.COORDINATOR
        dbserver = Mock()
        dbserver.role = ServerRole.DBSERVER

        manager._servers = {
            "coord1": coordinator1,
            "coord2": coordinator2,
            "db1": dbserver
        }

        coordinators = manager.get_servers_by_role(ServerRole.COORDINATOR)
        assert len(coordinators) == 2
        assert coordinator1 in coordinators
        assert coordinator2 in coordinators

        dbservers = manager.get_servers_by_role(ServerRole.DBSERVER)
        assert len(dbservers) == 1
        assert dbserver in dbservers

    def test_get_coordination_endpoints(self):
        """Test getting coordination endpoints."""
        manager = InstanceManager(self.deployment_id)

        # No plan
        assert manager.get_coordination_endpoints() == []

        # With plan
        plan = DeploymentPlan(DeploymentMode.CLUSTER)
        plan.coordination_endpoints = ["http://127.0.0.1:8529", "http://127.0.0.1:8530"]
        manager._deployment_plan = plan

        endpoints = manager.get_coordination_endpoints()
        assert endpoints == ["http://127.0.0.1:8529", "http://127.0.0.1:8530"]

    def test_get_agency_endpoints(self):
        """Test getting agency endpoints."""
        manager = InstanceManager(self.deployment_id)

        # No plan
        assert manager.get_agency_endpoints() == []

        # With plan
        plan = DeploymentPlan(DeploymentMode.CLUSTER)
        plan.agency_endpoints = ["tcp://127.0.0.1:8531", "tcp://127.0.0.1:8532"]
        manager._deployment_plan = plan

        endpoints = manager.get_agency_endpoints()
        assert endpoints == ["tcp://127.0.0.1:8531", "tcp://127.0.0.1:8532"]

    def test_check_deployment_health_not_deployed(self):
        """Test health check when not deployed."""
        manager = InstanceManager(self.deployment_id)

        health = manager.check_deployment_health()

        assert not health.is_healthy
        assert health.error_message == "No deployment active"

    def test_check_deployment_health_healthy(self):
        """Test health check with healthy servers."""
        manager = InstanceManager(self.deployment_id)
        manager._is_deployed = True

        mock_server = Mock()
        mock_health = Mock()
        mock_health.is_healthy = True
        mock_health.response_time = 0.1
        mock_server.health_check_sync.return_value = mock_health

        manager._servers = {"server1": mock_server}

        health = manager.check_deployment_health()

        assert health.is_healthy
        assert health.response_time == 0.1
        assert health.details["server_count"] == 1

    def test_check_deployment_health_unhealthy(self):
        """Test health check with unhealthy servers."""
        manager = InstanceManager(self.deployment_id)
        manager._is_deployed = True

        mock_server = Mock()
        mock_health = Mock()
        mock_health.is_healthy = False
        mock_health.response_time = 0.05  # Set as float instead of Mock
        mock_health.error_message = "Connection failed"
        mock_server.health_check_sync.return_value = mock_health

        manager._servers = {"server1": mock_server}

        health = manager.check_deployment_health()

        assert not health.is_healthy
        assert "Unhealthy servers: server1: Connection failed" in health.error_message

    def test_collect_server_stats(self):
        """Test collecting server statistics."""
        manager = InstanceManager(self.deployment_id)

        mock_server1 = Mock()
        mock_stats1 = Mock()
        mock_server1.collect_stats.return_value = mock_stats1

        mock_server2 = Mock()
        mock_server2.collect_stats.side_effect = Exception("Stats failed")

        manager._servers = {"server1": mock_server1, "server2": mock_server2}

        stats = manager.collect_server_stats()

        assert len(stats) == 1  # Only successful stats
        assert "server1" in stats
        assert stats["server1"] is mock_stats1

    def test_shutdown_deployment_not_deployed(self):
        """Test shutting down when not deployed."""
        manager = InstanceManager(self.deployment_id)

        # Should not raise error
        manager.shutdown_deployment()

    def test_is_deployed(self):
        """Test deployment status check."""
        manager = InstanceManager(self.deployment_id)

        assert not manager.is_deployed()

        manager._is_deployed = True
        assert manager.is_deployed()

    def test_is_healthy(self):
        """Test health status check."""
        manager = InstanceManager(self.deployment_id)

        assert not manager.is_healthy()

        manager._is_healthy = True
        assert manager.is_healthy()

    def test_get_server_count(self):
        """Test getting server count."""
        manager = InstanceManager(self.deployment_id)

        assert manager.get_server_count() == 0

        manager._servers = {"s1": Mock(), "s2": Mock()}
        assert manager.get_server_count() == 2

    def test_get_deployment_info(self):
        """Test getting deployment information."""
        manager = InstanceManager(self.deployment_id)
        manager._is_deployed = True
        manager._is_healthy = True
        manager._startup_time = 123.0

        # Add a mock plan
        plan = DeploymentPlan(DeploymentMode.CLUSTER)
        plan.coordination_endpoints = ["http://127.0.0.1:8529"]
        plan.agency_endpoints = ["tcp://127.0.0.1:8531"]
        manager._deployment_plan = plan

        # Add a mock server
        mock_server = Mock()
        mock_server.role = ServerRole.COORDINATOR
        mock_server.endpoint = "http://127.0.0.1:8529"
        mock_server.is_running.return_value = True
        mock_server.get_pid.return_value = 12345
        manager._servers = {"coord1": mock_server}

        info = manager.get_deployment_info()

        assert info["deployment_id"] == self.deployment_id
        assert info["is_deployed"] is True
        assert info["is_healthy"] is True
        assert info["server_count"] == 1
        assert info["startup_time"] == 123.0
        assert info["deployment_mode"] == "cluster"
        assert info["coordination_endpoints"] == ["http://127.0.0.1:8529"]
        assert info["agency_endpoints"] == ["tcp://127.0.0.1:8531"]

        assert "coord1" in info["servers"]
        assert info["servers"]["coord1"]["role"] == "coordinator"
        assert info["servers"]["coord1"]["endpoint"] == "http://127.0.0.1:8529"
        assert info["servers"]["coord1"]["is_running"] is True
        assert info["servers"]["coord1"]["pid"] == 12345


class TestGlobalInstanceManagerFunctions:
    """Test global instance manager functions."""

    def test_get_instance_manager_singleton(self):
        """Test get_instance_manager returns same instance for same ID."""
        deployment_id = "test_global"

        manager1 = get_instance_manager(deployment_id)
        manager2 = get_instance_manager(deployment_id)

        assert manager1 is manager2
        assert manager1.deployment_id == deployment_id

    def test_get_instance_manager_different_ids(self):
        """Test get_instance_manager returns different instances for different IDs."""
        manager1 = get_instance_manager("deployment1")
        manager2 = get_instance_manager("deployment2")

        assert manager1 is not manager2
        assert manager1.deployment_id == "deployment1"
        assert manager2.deployment_id == "deployment2"

    def test_cleanup_instance_managers(self):
        """Test cleaning up instance managers."""
        deployment_id = "test_cleanup"
        manager = get_instance_manager(deployment_id)
        manager._is_deployed = True

        with patch.object(manager, 'shutdown_deployment') as mock_shutdown:
            cleanup_instance_managers()
            mock_shutdown.assert_called_once()

        # Should be able to get a new manager after cleanup
        new_manager = get_instance_manager(deployment_id)
        assert new_manager is not manager  # New instance created


class TestInstanceManagerEdgeCases:
    """Test edge cases and error conditions."""

    def test_deployment_plan_validation(self):
        """Test deployment plan validation."""
        manager = InstanceManager("test")

        # Invalid cluster configuration should work but with warnings
        cluster_config = ClusterConfig(agents=0, dbservers=0, coordinators=0)

        with patch.object(manager.port_manager, 'allocate_port', return_value=8529):
            with patch('armadillo.instances.manager.server_dir') as mock_server_dir:
                mock_server_dir.return_value = Path("/tmp/servers")

                # Should create plan even with unusual config
                plan = manager.create_deployment_plan(DeploymentMode.CLUSTER, cluster_config)
                assert plan.deployment_mode == DeploymentMode.CLUSTER

    def test_concurrent_operations(self):
        """Test thread safety of operations."""
        import threading

        manager = InstanceManager("test_concurrent")
        results = []

        def worker():
            try:
                info = manager.get_deployment_info()
                results.append("success")
            except Exception as e:
                results.append(str(e))

        # Run multiple threads concurrently
        threads = []
        for _ in range(10):
            thread = threading.Thread(target=worker)
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # All operations should succeed
        assert all(result == "success" for result in results)
        assert len(results) == 10

    def test_resource_cleanup_on_error(self):
        """Test resource cleanup when deployment fails."""
        manager = InstanceManager("test_error")

        plan = DeploymentPlan(DeploymentMode.SINGLE_SERVER)
        server_config = ServerConfig(
            ServerRole.SINGLE, 8529,
            Path("/tmp/data"), Path("/tmp/log.txt")
        )
        plan.servers = [server_config]
        manager._deployment_plan = plan

        with patch.object(manager, '_create_server_instances', side_effect=Exception("Deployment failed")):
            with patch.object(manager, 'shutdown_deployment') as mock_shutdown:
                with pytest.raises(ServerStartupError):
                    manager.deploy_servers()

                # Should attempt cleanup
                mock_shutdown.assert_called_once()
