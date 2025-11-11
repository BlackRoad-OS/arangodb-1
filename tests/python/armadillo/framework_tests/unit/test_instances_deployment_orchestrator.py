"""Unit tests for DeploymentOrchestrator (refactored version)."""

import pytest
from unittest.mock import Mock, patch
from armadillo.instances.deployment_orchestrator import DeploymentOrchestrator
from armadillo.instances.deployment_plan import (
    SingleServerDeploymentPlan,
    ClusterDeploymentPlan,
)
from armadillo.core.types import ServerRole
from armadillo.core.errors import ServerError


class TestDeploymentOrchestratorRefactored:
    """Test the refactored DeploymentOrchestrator with strategy pattern."""

    def test_init(self):
        """Test orchestrator initialization."""
        mock_logger = Mock()
        mock_factory = Mock()
        mock_registry = Mock()
        mock_executor = Mock()

        orchestrator = DeploymentOrchestrator(
            mock_logger, mock_factory, mock_registry, mock_executor
        )

        assert orchestrator._logger == mock_logger
        assert orchestrator._server_factory == mock_factory
        assert orchestrator._server_registry == mock_registry
        assert orchestrator._executor == mock_executor
        assert orchestrator._health_monitor is None

    def test_create_strategy_single_server(self):
        """Test creating strategy for single server plan."""
        mock_logger = Mock()
        mock_factory = Mock()
        mock_registry = Mock()
        mock_executor = Mock()

        orchestrator = DeploymentOrchestrator(
            mock_logger, mock_factory, mock_registry, mock_executor
        )

        # Create single server plan
        plan = SingleServerDeploymentPlan(server=Mock())
        strategy = orchestrator._create_strategy(plan)

        # Verify correct strategy type
        from armadillo.instances.deployment_strategy import SingleServerStrategy

        assert isinstance(strategy, SingleServerStrategy)

    def test_create_strategy_cluster(self):
        """Test creating cluster strategy (creates bootstrapper internally)."""
        mock_logger = Mock()
        mock_factory = Mock()
        mock_registry = Mock()
        mock_executor = Mock()

        orchestrator = DeploymentOrchestrator(
            mock_logger,
            mock_factory,
            mock_registry,
            mock_executor,
        )

        # Create cluster plan
        plan = ClusterDeploymentPlan()
        strategy = orchestrator._create_strategy(plan)

        # Verify correct strategy type
        from armadillo.instances.deployment_strategy import ClusterStrategy

        assert isinstance(strategy, ClusterStrategy)

    def test_create_strategy_unsupported_plan(self):
        """Test creating strategy with unsupported plan type."""
        mock_logger = Mock()
        mock_factory = Mock()
        mock_registry = Mock()
        mock_executor = Mock()

        orchestrator = DeploymentOrchestrator(
            mock_logger, mock_factory, mock_registry, mock_executor
        )

        # Use a mock plan that's not a recognized type
        plan = Mock()

        with pytest.raises(ServerError, match="Unsupported deployment plan type"):
            orchestrator._create_strategy(plan)

    def test_create_servers_from_plan_single_server(self):
        """Test creating servers from single server plan."""
        mock_logger = Mock()
        mock_factory = Mock()
        mock_registry = Mock()
        mock_executor = Mock()

        orchestrator = DeploymentOrchestrator(
            mock_logger, mock_factory, mock_registry, mock_executor
        )

        # Create single server plan
        server_config = Mock()
        server_config.role = ServerRole.SINGLE
        plan = SingleServerDeploymentPlan(server=server_config)

        # Mock factory response
        mock_server = Mock()
        mock_factory.create_server_instances.return_value = {"server1": mock_server}

        orchestrator._create_servers_from_plan(plan)

        # Verify factory was called with single server config
        mock_factory.create_server_instances.assert_called_once_with([server_config])
        mock_registry.register_server.assert_called_once_with("server1", mock_server)

    def test_create_servers_from_plan_cluster(self):
        """Test creating servers from cluster plan."""
        mock_logger = Mock()
        mock_factory = Mock()
        mock_registry = Mock()
        mock_executor = Mock()

        orchestrator = DeploymentOrchestrator(
            mock_logger, mock_factory, mock_registry, mock_executor
        )

        # Create cluster plan
        server_configs = [Mock(), Mock(), Mock()]
        plan = ClusterDeploymentPlan(servers=server_configs)

        # Mock factory response
        mock_servers = {"s1": Mock(), "s2": Mock(), "s3": Mock()}
        mock_factory.create_server_instances.return_value = mock_servers

        orchestrator._create_servers_from_plan(plan)

        # Verify factory was called with all server configs
        mock_factory.create_server_instances.assert_called_once_with(server_configs)

        # Verify all servers were registered
        assert mock_registry.register_server.call_count == 3

    def test_shutdown_deployment(self):
        """Test shutting down deployment."""
        mock_logger = Mock()
        mock_factory = Mock()
        mock_registry = Mock()
        mock_executor = Mock()

        orchestrator = DeploymentOrchestrator(
            mock_logger, mock_factory, mock_registry, mock_executor
        )
        orchestrator._startup_order = ["server1", "server2"]

        # Mock servers
        mock_server1 = Mock()
        mock_server1.server_id = "server1"
        mock_server1.role = ServerRole.SINGLE
        mock_server2 = Mock()
        mock_server2.server_id = "server2"
        mock_server2.role = ServerRole.SINGLE
        mock_registry.get_all_servers.return_value = {
            "server1": mock_server1,
            "server2": mock_server2,
        }

        orchestrator.shutdown_deployment(timeout=60.0)

        # Verify servers were stopped in reverse order (timeout divided by number of servers)
        mock_server2.stop.assert_called_once_with(timeout=30.0)  # 60.0 / 2 servers
        mock_server1.stop.assert_called_once_with(timeout=30.0)

    # ------------------------------------------------------------------
    # New lifecycle strategy path tests (armadillo-49 transitional)
    # ------------------------------------------------------------------

    def test_init_lifecycle_flag(self):
        mock_logger = Mock()
        mock_factory = Mock()
        mock_registry = Mock()
        mock_executor = Mock()

        orchestrator = DeploymentOrchestrator(
            mock_logger,
            mock_factory,
            mock_registry,
            mock_executor,
            use_lifecycle_strategies=True,
        )

        assert orchestrator._use_lifecycle is True
        assert isinstance(orchestrator._servers, dict)
        assert orchestrator.get_servers() == {}

    def test_create_lifecycle_strategy_single(self):
        mock_logger = Mock()
        mock_factory = Mock()
        mock_registry = Mock()
        mock_executor = Mock()

        orchestrator = DeploymentOrchestrator(
            mock_logger,
            mock_factory,
            mock_registry,
            mock_executor,
            use_lifecycle_strategies=True,
        )

        plan = SingleServerDeploymentPlan(server=Mock(role=ServerRole.SINGLE))
        lifecycle_strategy = orchestrator._create_lifecycle_strategy(plan)

        from armadillo.instances.deployment_strategy import SingleServerDeploymentStrategy
        assert isinstance(lifecycle_strategy, SingleServerDeploymentStrategy)

    def test_create_lifecycle_strategy_cluster(self):
        mock_logger = Mock()
        mock_factory = Mock()
        mock_registry = Mock()
        mock_executor = Mock()

        orchestrator = DeploymentOrchestrator(
            mock_logger,
            mock_factory,
            mock_registry,
            mock_executor,
            use_lifecycle_strategies=True,
        )

        plan = ClusterDeploymentPlan()
        lifecycle_strategy = orchestrator._create_lifecycle_strategy(plan)

        from armadillo.instances.deployment_strategy import ClusterDeploymentStrategy
        assert isinstance(lifecycle_strategy, ClusterDeploymentStrategy)

    def test_execute_deployment_lifecycle_single(self):
        mock_logger = Mock()
        mock_registry = Mock()
        mock_executor = Mock()

        # Build mock factory that returns a single healthy mock server
        mock_server = Mock()
        mock_server.start = Mock()
        mock_server.health_check_sync = Mock(return_value=Mock(is_healthy=True, error_message=None))
        mock_server.role = ServerRole.SINGLE

        class MockFactory:
            def create_server_instances(self, servers_config):
                # Return dict with a deterministic ServerId-like key
                return {"server_0": mock_server}

        orchestrator = DeploymentOrchestrator(
            mock_logger,
            MockFactory(),
            mock_registry,
            mock_executor,
            use_lifecycle_strategies=True,
        )

        plan = SingleServerDeploymentPlan(server=Mock(role=ServerRole.SINGLE))
        orchestrator.execute_deployment(plan, timeout=5.0)

        # Internal servers dict should be populated
        servers = orchestrator.get_servers()
        assert len(servers) == 1
        assert "server_0" in servers
        mock_server.start.assert_called_once()
        mock_server.health_check_sync.assert_called_once()
        assert orchestrator.get_startup_order() == ["server_0"]

    def test_execute_deployment_lifecycle_cluster(self, monkeypatch):
        mock_logger = Mock()
        mock_registry = Mock()
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

        # Fake bootstrap to append startup order deterministically
        def fake_bootstrap(self, servers, startup_order, timeout=0):
            for sid, srv in servers.items():
                if srv.role == ServerRole.AGENT:
                    startup_order.append(sid)
            for sid, srv in servers.items():
                if srv.role == ServerRole.DBSERVER:
                    startup_order.append(sid)
            for sid, srv in servers.items():
                if srv.role == ServerRole.COORDINATOR:
                    startup_order.append(sid)

        from armadillo.instances.cluster_bootstrapper import ClusterBootstrapper
        monkeypatch.setattr(ClusterBootstrapper, "bootstrap_cluster", fake_bootstrap)

        orchestrator = DeploymentOrchestrator(
            mock_logger,
            MockFactory(),
            mock_registry,
            mock_executor,
            use_lifecycle_strategies=True,
        )

        plan = ClusterDeploymentPlan(servers=[Mock(role=ServerRole.AGENT),
                                              Mock(role=ServerRole.AGENT),
                                              Mock(role=ServerRole.DBSERVER),
                                              Mock(role=ServerRole.COORDINATOR)])
        orchestrator.execute_deployment(plan, timeout=10.0)

        servers = orchestrator.get_servers()
        assert set(servers.keys()) == {"agent_0", "agent_1", "dbserver_0", "coordinator_0"}
        order = orchestrator.get_startup_order()
        assert order[:2] == ["agent_0", "agent_1"]
        assert "dbserver_0" in order[2:3]
        assert order[-1] == "coordinator_0"

    def test_shutdown_deployment_lifecycle(self):
        mock_logger = Mock()
        mock_registry = Mock()
        mock_executor = Mock()

        mock_server1 = Mock()
        mock_server1.server_id = "server_0"
        mock_server1.role = ServerRole.SINGLE
        mock_server1.stop = Mock()

        orchestrator = DeploymentOrchestrator(
            mock_logger,
            Mock(),  # factory unused for shutdown test
            mock_registry,
            mock_executor,
            use_lifecycle_strategies=True,
        )
        orchestrator._servers = {"server_0": mock_server1}
        orchestrator._startup_order = ["server_0"]

        orchestrator.shutdown_deployment(timeout=10.0)

        mock_server1.stop.assert_called_once()
        assert orchestrator.get_servers() == {}
        assert orchestrator.get_startup_order() == []
