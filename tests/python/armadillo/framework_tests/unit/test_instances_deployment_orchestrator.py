"""Unit tests for DeploymentOrchestrator."""

import pytest
from unittest.mock import Mock, patch
from armadillo.instances.deployment_orchestrator import DeploymentOrchestrator
from armadillo.instances.deployment_plan import (
    SingleServerDeploymentPlan,
    ClusterDeploymentPlan,
)
from armadillo.core.types import ServerRole
from armadillo.core.errors import ServerError


class TestDeploymentOrchestrator:
    """Test DeploymentOrchestrator with lifecycle executors."""

    def test_init(self):
        """Test orchestrator initialization."""
        mock_logger = Mock()
        mock_factory = Mock()
        mock_executor = Mock()

        orchestrator = DeploymentOrchestrator(mock_logger, mock_factory, mock_executor)

        assert orchestrator._logger == mock_logger
        assert orchestrator._server_factory == mock_factory
        assert orchestrator._executor == mock_executor
        assert orchestrator._servers == {}

    def test_create_executor_single_server(self):
        """Test creating executor for single server plan."""
        mock_logger = Mock()
        mock_factory = Mock()
        mock_executor = Mock()

        orchestrator = DeploymentOrchestrator(mock_logger, mock_factory, mock_executor)

        # Create single server plan
        plan = SingleServerDeploymentPlan(server=Mock())
        executor = orchestrator._create_executor(plan)

        # Verify correct executor type
        from armadillo.instances.deployment_executor import SingleServerExecutor

        assert isinstance(executor, SingleServerExecutor)

    def test_create_executor_cluster(self):
        """Test creating cluster executor (creates bootstrapper internally)."""
        mock_logger = Mock()
        mock_factory = Mock()
        mock_executor = Mock()

        orchestrator = DeploymentOrchestrator(
            mock_logger,
            mock_factory,
            mock_executor,
        )

        # Create cluster plan
        plan = ClusterDeploymentPlan()
        executor = orchestrator._create_executor(plan)

        # Verify correct executor type
        from armadillo.instances.deployment_executor import ClusterExecutor

        assert isinstance(executor, ClusterExecutor)

    def test_create_executor_unsupported_plan(self):
        """Test creating executor with unsupported plan type."""
        mock_logger = Mock()
        mock_factory = Mock()
        mock_executor = Mock()

        orchestrator = DeploymentOrchestrator(mock_logger, mock_factory, mock_executor)

        # Use a mock plan that's not a recognized type
        plan = Mock()

        with pytest.raises(ServerError, match="Unsupported deployment plan type"):
            orchestrator._create_executor(plan)

    def test_execute_deployment_single(self):
        """Test executing single server deployment."""
        mock_logger = Mock()
        mock_executor = Mock()

        # Build mock factory that returns a single healthy mock server
        mock_server = Mock()
        mock_server.start = Mock()
        mock_server.health_check_sync = Mock(
            return_value=Mock(is_healthy=True, error_message=None)
        )
        mock_server.role = ServerRole.SINGLE

        class MockFactory:
            def create_server_instances(self, servers_config):
                # Return dict with a deterministic ServerId-like key
                return {"server_0": mock_server}

        orchestrator = DeploymentOrchestrator(
            mock_logger,
            MockFactory(),
            mock_executor,
        )

        plan = SingleServerDeploymentPlan(server=Mock(role=ServerRole.SINGLE))
        orchestrator.execute_deployment(plan, timeout=5.0)

        # Internal servers dict should be populated
        servers = orchestrator.get_servers()
        assert len(servers) == 1
        assert "server_0" in servers
        mock_server.start.assert_called_once()
        mock_server.health_check_sync.assert_called_once()

    def test_execute_deployment_cluster(self, monkeypatch):
        """Test executing cluster deployment."""
        mock_logger = Mock()
        mock_executor = Mock()

        # Prepare mock servers with roles
        agent1 = Mock(role=ServerRole.AGENT)
        agent2 = Mock(role=ServerRole.AGENT)
        db1 = Mock(role=ServerRole.DBSERVER)
        coord1 = Mock(role=ServerRole.COORDINATOR)

        class MockFactory:
            def create_server_instances(self, servers_config):
                return {
                    "agent_0": agent1,
                    "agent_1": agent2,
                    "dbserver_0": db1,
                    "coordinator_0": coord1,
                }

        # Fake bootstrap
        def fake_bootstrap(self, servers, timeout=0):
            # Just verify servers dict is passed correctly
            assert len(servers) == 4

        from armadillo.instances.cluster_bootstrapper import ClusterBootstrapper

        monkeypatch.setattr(ClusterBootstrapper, "bootstrap_cluster", fake_bootstrap)

        orchestrator = DeploymentOrchestrator(
            mock_logger,
            MockFactory(),
            mock_executor,
        )

        plan = ClusterDeploymentPlan(
            servers=[
                Mock(role=ServerRole.AGENT),
                Mock(role=ServerRole.AGENT),
                Mock(role=ServerRole.DBSERVER),
                Mock(role=ServerRole.COORDINATOR),
            ]
        )
        orchestrator.execute_deployment(plan, timeout=10.0)

        servers = orchestrator.get_servers()
        assert set(servers.keys()) == {
            "agent_0",
            "agent_1",
            "dbserver_0",
            "coordinator_0",
        }

    def test_shutdown_deployment(self):
        """Test shutting down deployment via executor."""
        mock_logger = Mock()
        mock_executor = Mock()

        mock_server1 = Mock()
        mock_server1.server_id = "server_0"
        mock_server1.role = ServerRole.SINGLE
        mock_server1.stop = Mock()

        # Mock executor with shutdown method
        mock_executor_instance = Mock()
        mock_executor_instance.shutdown = Mock()

        orchestrator = DeploymentOrchestrator(
            mock_logger,
            Mock(),  # factory unused for shutdown test
            mock_executor,
        )
        orchestrator._servers = {"server_0": mock_server1}
        orchestrator._current_executor = mock_executor_instance

        orchestrator.shutdown_deployment(timeout=10.0)

        # Verify executor.shutdown was called
        mock_executor_instance.shutdown.assert_called_once_with(
            {"server_0": mock_server1}, 10.0
        )
        assert orchestrator.get_servers() == {}
        assert orchestrator._current_executor is None
