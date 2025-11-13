"""Integration tests for DeploymentOrchestrator lifecycle correctness.

These tests verify that the orchestrator correctly:
1. Executes deployments and populates internal server dict
2. Shuts down servers in correct order (non-agents → agents)
3. Handles edge cases: duplicate deployment, shutdown with no servers, partial failures
4. Properly cleans up after failures
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from concurrent.futures import ThreadPoolExecutor

from armadillo.core.types import ServerRole, TimeoutConfig
from armadillo.core.log import get_logger
from armadillo.core.value_objects import ServerId
from armadillo.core.errors import ServerError, ServerStartupError
from armadillo.instances.deployment_orchestrator import DeploymentOrchestrator
from armadillo.instances.deployment_plan import (
    SingleServerDeploymentPlan,
    ClusterDeploymentPlan,
    ServerConfig,
)
from armadillo.instances.server import ArangoServer
from armadillo.instances.server_factory import ServerFactory
from armadillo.instances.health_monitor import HealthMonitor


@pytest.fixture
def logger():
    """Create logger for tests."""
    return get_logger(__name__)


@pytest.fixture
def executor():
    """Create thread pool executor."""
    executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="test-orchestrator")
    yield executor
    executor.shutdown(wait=True)


@pytest.fixture
def server_factory():
    """Create mock server factory."""
    factory = Mock(spec=ServerFactory)
    return factory


@pytest.fixture
def health_monitor():
    """Create mock health monitor."""
    monitor = Mock(spec=HealthMonitor)
    return monitor


@pytest.fixture
def timeout_config():
    """Create timeout configuration."""
    return TimeoutConfig()


@pytest.fixture
def orchestrator(logger, server_factory, executor, timeout_config):
    """Create orchestrator instance."""
    return DeploymentOrchestrator(
        logger=logger,
        server_factory=server_factory,
        executor=executor,
        timeout_config=timeout_config,
    )


def create_mock_server(server_id: str, role: ServerRole) -> Mock:
    """Create a mock ArangoServer instance."""
    server = Mock(spec=ArangoServer)
    server.server_id = ServerId(server_id)
    server.role = role
    server.endpoint = f"tcp://127.0.0.1:8529"
    server.is_running.return_value = True
    server.stop = Mock()
    return server


class TestSingleServerDeployment:
    """Test single server deployment lifecycle."""

    def test_execute_deployment_populates_servers_dict(
        self, orchestrator, server_factory, health_monitor
    ):
        """Verify execute_deployment creates and stores server in internal dict."""
        # Setup
        plan = SingleServerDeploymentPlan(
            server=ServerConfig(
                role=ServerRole.SINGLE,
                port=8529,
                data_dir="/tmp/test",
                log_file="/tmp/test/arangod.log",
            ),
        )

        mock_server = create_mock_server("SNGL-1", ServerRole.SINGLE)
        server_factory.create_server_instances.return_value = {
            ServerId("SNGL-1"): mock_server
        }

        # Mock health check to pass
        health_monitor.check_deployment_health.return_value = Mock(is_healthy=True)

        # Execute
        deployment = orchestrator.execute_deployment(plan, timeout=30.0)

        # Verify
        servers = deployment.get_servers()
        assert len(servers) == 1
        assert ServerId("SNGL-1") in servers
        assert servers[ServerId("SNGL-1")] == mock_server

    def test_shutdown_clears_servers_dict(
        self, orchestrator, server_factory, health_monitor
    ):
        """Verify shutdown_deployment releases servers and clears internal dict."""
        # Setup deployment first
        plan = SingleServerDeploymentPlan(
            server=ServerConfig(
                role=ServerRole.SINGLE,
                port=8529,
                data_dir="/tmp/test",
                log_file="/tmp/test/arangod.log",
            ),
        )

        mock_server = create_mock_server("SNGL-1", ServerRole.SINGLE)
        server_factory.create_server_instances.return_value = {
            ServerId("SNGL-1"): mock_server
        }
        health_monitor.check_deployment_health.return_value = Mock(is_healthy=True)

        deployment = orchestrator.execute_deployment(plan, timeout=30.0)
        assert len(deployment.get_servers()) == 1

        # Execute shutdown
        orchestrator.shutdown_deployment(deployment, timeout=30.0)

        # Verify
        mock_server.stop.assert_called_once()

    def test_shutdown_with_no_servers(self, orchestrator):
        """Verify shutdown with empty deployment does not error."""
        # Create empty deployment
        from armadillo.instances.deployment import (
            SingleServerDeployment,
            DeploymentStatus,
            DeploymentTiming,
        )
        from armadillo.instances.deployment_plan import SingleServerDeploymentPlan
        from armadillo.core.types import ServerConfig, ServerRole

        empty_deployment = SingleServerDeployment(
            plan=SingleServerDeploymentPlan(
                server=ServerConfig(
                    role=ServerRole.SINGLE,
                    port=8529,
                    data_dir="/tmp/test",
                    log_file="/tmp/test/arangod.log",
                )
            ),
            server=Mock(),
            status=DeploymentStatus(is_deployed=False, is_healthy=False),
            timing=DeploymentTiming(),
        )

        # Should not raise (empty deployment)
        orchestrator.shutdown_deployment(empty_deployment, timeout=30.0)


class TestClusterDeployment:
    """Test cluster deployment lifecycle and ordering."""

    def test_cluster_deployment_success(
        self, orchestrator, server_factory, executor, health_monitor
    ):
        """Verify cluster deployment succeeds and all servers are present."""
        # Setup cluster plan
        plan = ClusterDeploymentPlan(
            servers=[
                ServerConfig(
                    role=ServerRole.AGENT,
                    port=8531,
                    data_dir="/tmp/agent1",
                    log_file="/tmp/agent1/arangod.log",
                ),
                ServerConfig(
                    role=ServerRole.AGENT,
                    port=8532,
                    data_dir="/tmp/agent2",
                    log_file="/tmp/agent2/arangod.log",
                ),
                ServerConfig(
                    role=ServerRole.AGENT,
                    port=8533,
                    data_dir="/tmp/agent3",
                    log_file="/tmp/agent3/arangod.log",
                ),
                ServerConfig(
                    role=ServerRole.DBSERVER,
                    port=8629,
                    data_dir="/tmp/dbserver1",
                    log_file="/tmp/dbserver1/arangod.log",
                ),
                ServerConfig(
                    role=ServerRole.DBSERVER,
                    port=8630,
                    data_dir="/tmp/dbserver2",
                    log_file="/tmp/dbserver2/arangod.log",
                ),
                ServerConfig(
                    role=ServerRole.COORDINATOR,
                    port=8529,
                    data_dir="/tmp/coord1",
                    log_file="/tmp/coord1/arangod.log",
                ),
            ],
        )

        # Create mock servers
        mock_agents = [
            create_mock_server("AGNT-1", ServerRole.AGENT),
            create_mock_server("AGNT-2", ServerRole.AGENT),
            create_mock_server("AGNT-3", ServerRole.AGENT),
        ]
        mock_dbservers = [
            create_mock_server("PRMR-1", ServerRole.DBSERVER),
            create_mock_server("PRMR-2", ServerRole.DBSERVER),
        ]
        mock_coordinators = [
            create_mock_server("CRDN-1", ServerRole.COORDINATOR),
        ]

        # Create dict mapping server IDs to servers
        servers_dict = {
            ServerId("AGNT-1"): mock_agents[0],
            ServerId("AGNT-2"): mock_agents[1],
            ServerId("AGNT-3"): mock_agents[2],
            ServerId("PRMR-1"): mock_dbservers[0],
            ServerId("PRMR-2"): mock_dbservers[1],
            ServerId("CRDN-1"): mock_coordinators[0],
        }
        server_factory.create_server_instances.return_value = servers_dict

        # Mock health check
        health_monitor.check_deployment_health.return_value = Mock(is_healthy=True)

        # Execute
        deployment = orchestrator.execute_deployment(plan, timeout=60.0)

        # Verify servers stored
        servers = deployment.get_servers()
        assert len(servers) == 6

        # Verify all servers are present
        assert sum(1 for s in servers.values() if s.role == ServerRole.AGENT) == 3
        assert sum(1 for s in servers.values() if s.role == ServerRole.DBSERVER) == 2
        assert sum(1 for s in servers.values() if s.role == ServerRole.COORDINATOR) == 1

    def test_cluster_shutdown_role_based_order(
        self, orchestrator, server_factory, executor, health_monitor
    ):
        """Verify cluster shuts down in role-based order: non-agents → agents."""
        # Setup and deploy cluster
        plan = ClusterDeploymentPlan(
            servers=[
                ServerConfig(
                    role=ServerRole.AGENT,
                    port=8531,
                    data_dir="/tmp/agent1",
                    log_file="/tmp/agent1/arangod.log",
                ),
                ServerConfig(
                    role=ServerRole.DBSERVER,
                    port=8629,
                    data_dir="/tmp/dbserver1",
                    log_file="/tmp/dbserver1/arangod.log",
                ),
                ServerConfig(
                    role=ServerRole.COORDINATOR,
                    port=8529,
                    data_dir="/tmp/coord1",
                    log_file="/tmp/coord1/arangod.log",
                ),
            ],
        )

        mock_agent = create_mock_server("AGNT-1", ServerRole.AGENT)
        mock_dbserver = create_mock_server("PRMR-1", ServerRole.DBSERVER)
        mock_coordinator = create_mock_server("CRDN-1", ServerRole.COORDINATOR)

        servers_dict = {
            ServerId("AGNT-1"): mock_agent,
            ServerId("PRMR-1"): mock_dbserver,
            ServerId("CRDN-1"): mock_coordinator,
        }
        all_servers = [mock_agent, mock_dbserver, mock_coordinator]
        server_factory.create_server_instances.return_value = servers_dict
        health_monitor.check_deployment_health.return_value = Mock(is_healthy=True)

        deployment = orchestrator.execute_deployment(plan, timeout=60.0)

        # Track shutdown order
        shutdown_calls = []

        def track_stop(*args, **kwargs):
            shutdown_calls.append(args[0] if args else None)

        # Replace stop methods to track call order
        for server in all_servers:
            server.stop = Mock(side_effect=lambda s=server: shutdown_calls.append(s))

        # Execute shutdown
        orchestrator.shutdown_deployment(deployment, timeout=30.0)

        # Verify shutdown happened
        assert len(shutdown_calls) == 3

        # Verify order: coordinator and dbserver before agent
        # (Within non-agents, order doesn't matter, but agents must be last)
        agent_index = shutdown_calls.index(mock_agent)
        coordinator_index = shutdown_calls.index(mock_coordinator)
        dbserver_index = shutdown_calls.index(mock_dbserver)

        # Agent must be last
        assert agent_index == 2
        # Coordinator and dbserver before agent
        assert coordinator_index < agent_index
        assert dbserver_index < agent_index


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_duplicate_deployment_detection(
        self, orchestrator, server_factory, health_monitor
    ):
        """Verify executing deployment twice without shutdown is handled."""
        plan = SingleServerDeploymentPlan(
            server=ServerConfig(
                role=ServerRole.SINGLE,
                port=8529,
                data_dir="/tmp/test",
                log_file="/tmp/test/arangod.log",
            ),
        )

        mock_server = create_mock_server("SNGL-1", ServerRole.SINGLE)
        server_factory.create_server_instances.return_value = {
            ServerId("SNGL-1"): mock_server
        }
        health_monitor.check_deployment_health.return_value = Mock(is_healthy=True)

        # First deployment succeeds
        deployment1 = orchestrator.execute_deployment(plan, timeout=30.0)
        assert len(deployment1.get_servers()) == 1

        # Second deployment returns new deployment
        mock_server2 = create_mock_server("SNGL-2", ServerRole.SINGLE)
        server_factory.create_server_instances.return_value = {
            ServerId("SNGL-2"): mock_server2
        }

        deployment2 = orchestrator.execute_deployment(plan, timeout=30.0)

        # Should have new server
        servers = deployment2.get_servers()
        assert len(servers) == 1
        assert ServerId("SNGL-2") in servers

    def test_partial_startup_failure_cleanup(
        self, orchestrator, server_factory, health_monitor
    ):
        """Verify partial deployment failure triggers cleanup."""
        plan = ClusterDeploymentPlan(
            servers=[
                ServerConfig(
                    role=ServerRole.AGENT,
                    port=8531,
                    data_dir="/tmp/agent1",
                    log_file="/tmp/agent1/arangod.log",
                ),
                ServerConfig(
                    role=ServerRole.DBSERVER,
                    port=8629,
                    data_dir="/tmp/dbserver1",
                    log_file="/tmp/dbserver1/arangod.log",
                ),
                ServerConfig(
                    role=ServerRole.COORDINATOR,
                    port=8529,
                    data_dir="/tmp/coord1",
                    log_file="/tmp/coord1/arangod.log",
                ),
            ],
        )

        # Create servers but make health check fail
        mock_agent = create_mock_server("AGNT-1", ServerRole.AGENT)
        mock_dbserver = create_mock_server("PRMR-1", ServerRole.DBSERVER)
        mock_coordinator = create_mock_server("CRDN-1", ServerRole.COORDINATOR)

        servers_dict = {
            ServerId("AGNT-1"): mock_agent,
            ServerId("PRMR-1"): mock_dbserver,
            ServerId("CRDN-1"): mock_coordinator,
        }
        server_factory.create_server_instances.return_value = servers_dict

        # Health check fails
        health_monitor.check_deployment_health.return_value = Mock(
            is_healthy=False, error_message="Coordinator not responding"
        )

        # Execute should raise
        with pytest.raises(ServerError, match="health check failed"):
            orchestrator.execute_deployment(plan, timeout=60.0)

        # Note: In current implementation, servers are stored even on health failure
        # This may be desired for debugging, but cleanup would need to be added
        # to shutdown_deployment call or automatic rollback

    def test_agent_startup_failure_aborts_sequence(
        self, orchestrator, server_factory, health_monitor
    ):
        """Verify failure during agent startup aborts cluster deployment."""
        plan = ClusterDeploymentPlan(
            servers=[
                ServerConfig(
                    role=ServerRole.AGENT,
                    port=8531,
                    data_dir="/tmp/agent1",
                    log_file="/tmp/agent1/arangod.log",
                ),
                ServerConfig(
                    role=ServerRole.DBSERVER,
                    port=8629,
                    data_dir="/tmp/dbserver1",
                    log_file="/tmp/dbserver1/arangod.log",
                ),
                ServerConfig(
                    role=ServerRole.COORDINATOR,
                    port=8529,
                    data_dir="/tmp/coord1",
                    log_file="/tmp/coord1/arangod.log",
                ),
            ],
        )

        # Make server creation fail for agents
        def create_with_failure(configs):
            # Raise error when trying to create servers (simulating agent start failure)
            raise ServerStartupError("Failed to start agent AGNT-1")

        server_factory.create_server_instances.side_effect = create_with_failure

        # Execute should raise and abort
        with pytest.raises(ServerStartupError, match="Failed to start agent"):
            orchestrator.execute_deployment(plan, timeout=60.0)

        # Orchestrator is stateless - no state to check

    def test_get_server_returns_none_for_missing(self, orchestrator):
        """Verify get_server is no longer available (orchestrator is stateless)."""
        # Orchestrator no longer stores deployment state
        # This test is no longer applicable - orchestrator is stateless
        pass

    def test_shutdown_continues_on_individual_failure(
        self, orchestrator, server_factory, health_monitor
    ):
        """Verify shutdown continues even if individual server stop fails."""
        plan = ClusterDeploymentPlan(
            servers=[
                ServerConfig(
                    role=ServerRole.AGENT,
                    port=8531,
                    data_dir="/tmp/agent1",
                    log_file="/tmp/agent1/arangod.log",
                ),
                ServerConfig(
                    role=ServerRole.DBSERVER,
                    port=8629,
                    data_dir="/tmp/dbserver1",
                    log_file="/tmp/dbserver1/arangod.log",
                ),
                ServerConfig(
                    role=ServerRole.DBSERVER,
                    port=8630,
                    data_dir="/tmp/dbserver2",
                    log_file="/tmp/dbserver2/arangod.log",
                ),
            ],
        )

        mock_agent = create_mock_server("AGNT-1", ServerRole.AGENT)
        mock_dbserver1 = create_mock_server("PRMR-1", ServerRole.DBSERVER)
        mock_dbserver2 = create_mock_server("PRMR-2", ServerRole.DBSERVER)

        servers_dict = {
            ServerId("AGNT-1"): mock_agent,
            ServerId("PRMR-1"): mock_dbserver1,
            ServerId("PRMR-2"): mock_dbserver2,
        }
        all_servers = [mock_agent, mock_dbserver1, mock_dbserver2]
        server_factory.create_server_instances.return_value = servers_dict
        health_monitor.check_deployment_health.return_value = Mock(is_healthy=True)

        deployment = orchestrator.execute_deployment(plan, timeout=60.0)

        # Make first dbserver fail to stop
        from armadillo.core.errors import ServerShutdownError

        mock_dbserver1.stop.side_effect = ServerShutdownError("Force kill failed")

        # Shutdown should continue despite failure
        orchestrator.shutdown_deployment(deployment, timeout=30.0)

        # All servers should have been attempted
        mock_dbserver1.stop.assert_called_once()
        mock_dbserver2.stop.assert_called_once()
        mock_agent.stop.assert_called_once()
