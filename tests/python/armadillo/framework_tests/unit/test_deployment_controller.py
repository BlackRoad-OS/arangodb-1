"""Tests for DeploymentController.

Tests the new minimal architecture with:
- Factory methods for creating deployments
- Direct health checking (no HealthMonitor)
- Crash callbacks for instant notification
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from pathlib import Path
import time

from armadillo.instances.deployment_controller import DeploymentController
from armadillo.instances.deployment import SingleServerDeployment, ClusterDeployment
from armadillo.instances.server import ArangoServer
from armadillo.core.context import ApplicationContext
from armadillo.core.value_objects import ServerId, DeploymentId
from armadillo.core.types import (
    ServerRole,
    ClusterConfig,
    HealthStatus,
    ArmadilloConfig,
    DeploymentMode,
    CrashInfo,
)


class TestDeploymentControllerFactoryMethods:
    """Test factory methods for creating deployments."""

    def test_create_single_server_creates_controller(self, app_context):
        """Test that create_single_server returns a controller with single server deployment."""
        deployment_id = DeploymentId("test-single")

        controller = DeploymentController.create_single_server(
            deployment_id, app_context
        )

        assert controller is not None
        assert controller.deployment_id == deployment_id
        assert isinstance(controller.deployment, SingleServerDeployment)
        assert controller.deployment.get_server_count() == 1

    def test_create_single_server_auto_allocates_port(self, app_context):
        """Test that create_single_server auto-allocates a port."""
        deployment_id = DeploymentId("test-port")

        controller = DeploymentController.create_single_server(
            deployment_id, app_context
        )

        servers = controller.deployment.get_servers()
        server = next(iter(servers.values()))
        assert server.port > 0

    def test_create_cluster_creates_all_servers(self, app_context):
        """Test that create_cluster creates all server types."""
        deployment_id = DeploymentId("test-cluster")
        cluster_config = ClusterConfig(agents=3, dbservers=2, coordinators=1)

        controller = DeploymentController.create_cluster(
            deployment_id, app_context, cluster_config
        )

        assert controller is not None
        assert isinstance(controller.deployment, ClusterDeployment)
        assert controller.deployment.get_server_count() == 6  # 3 + 2 + 1

        # Verify server roles
        servers = controller.deployment.get_servers()
        agents = [s for s in servers.values() if s.role == ServerRole.AGENT]
        dbservers = [s for s in servers.values() if s.role == ServerRole.DBSERVER]
        coordinators = [s for s in servers.values() if s.role == ServerRole.COORDINATOR]

        assert len(agents) == 3
        assert len(dbservers) == 2
        assert len(coordinators) == 1

    def test_create_cluster_assigns_unique_server_ids(self, app_context):
        """Test that cluster servers have unique IDs."""
        deployment_id = DeploymentId("test-ids")
        cluster_config = ClusterConfig(agents=2, dbservers=2, coordinators=2)

        controller = DeploymentController.create_cluster(
            deployment_id, app_context, cluster_config
        )

        servers = controller.deployment.get_servers()
        server_ids = list(servers.keys())

        # All IDs should be unique
        assert len(server_ids) == len(set(server_ids))


class TestDeploymentControllerLifecycle:
    """Test lifecycle methods."""

    def test_start_marks_deployment_as_deployed(self, app_context):
        """Test that start() marks deployment as deployed."""
        deployment_id = DeploymentId("test-start")
        controller = DeploymentController.create_single_server(
            deployment_id, app_context
        )

        # Mock server start to avoid actual process
        server = next(iter(controller.deployment.get_servers().values()))
        server.start = Mock()
        server.health_check_sync = Mock(
            return_value=HealthStatus(is_healthy=True, response_time=0.1)
        )

        controller.start(timeout=10.0)

        assert controller.deployment.is_deployed()
        server.start.assert_called_once()

    def test_start_registers_crash_callbacks(self, app_context):
        """Test that start() registers crash callbacks."""
        deployment_id = DeploymentId("test-callbacks")
        controller = DeploymentController.create_single_server(
            deployment_id, app_context
        )

        # Mock server
        server = next(iter(controller.deployment.get_servers().values()))
        server.start = Mock()
        server.health_check_sync = Mock(
            return_value=HealthStatus(is_healthy=True, response_time=0.1)
        )

        controller.start(timeout=10.0)

        # Verify callback was registered
        app_context.process_supervisor.register_crash_callback.assert_called()
        assert controller._crash_callbacks_registered

    def test_stop_unregisters_crash_callbacks(self, app_context):
        """Test that stop() unregisters crash callbacks."""
        deployment_id = DeploymentId("test-stop")
        controller = DeploymentController.create_single_server(
            deployment_id, app_context
        )

        # Mock server
        server = next(iter(controller.deployment.get_servers().values()))
        server.start = Mock()
        server.stop = Mock()
        server.health_check_sync = Mock(
            return_value=HealthStatus(is_healthy=True, response_time=0.1)
        )

        controller.start(timeout=10.0)
        controller.stop(timeout=10.0)

        # Verify callback was unregistered
        app_context.process_supervisor.unregister_crash_callback.assert_called()
        assert not controller._crash_callbacks_registered

    def test_stop_marks_deployment_as_shutdown(self, app_context):
        """Test that stop() marks deployment as shutdown."""
        deployment_id = DeploymentId("test-shutdown")
        controller = DeploymentController.create_single_server(
            deployment_id, app_context
        )

        # Mock server
        server = next(iter(controller.deployment.get_servers().values()))
        server.start = Mock()
        server.stop = Mock()
        server.health_check_sync = Mock(
            return_value=HealthStatus(is_healthy=True, response_time=0.1)
        )

        controller.start(timeout=10.0)
        controller.stop(timeout=10.0)

        assert not controller.deployment.is_deployed()

    def test_cluster_stop_order(self, app_context):
        """Test that cluster stop follows correct order (non-agents first, then agents)."""
        deployment_id = DeploymentId("test-order")
        cluster_config = ClusterConfig(agents=1, dbservers=1, coordinators=1)
        controller = DeploymentController.create_cluster(
            deployment_id, app_context, cluster_config
        )

        # Track stop order
        stop_order = []
        for server in controller.deployment.get_servers().values():
            server.start = Mock()
            # Use a wrapper that accepts any kwargs but captures the role
            def make_stop_handler(s):
                def stop_handler(**kwargs):
                    stop_order.append(s.role)
                return stop_handler
            server.stop = Mock(side_effect=make_stop_handler(server))
            server.health_check_sync = Mock(
                return_value=HealthStatus(is_healthy=True, response_time=0.1)
            )

        # Mock cluster bootstrapper
        app_context.cluster_bootstrapper.bootstrap_cluster = Mock()

        controller.start(timeout=60.0)
        controller.stop(timeout=60.0)

        # Verify agents stopped last
        agent_index = stop_order.index(ServerRole.AGENT)
        for i, role in enumerate(stop_order):
            if role != ServerRole.AGENT:
                assert i < agent_index, f"{role} should be stopped before agents"


class TestDeploymentControllerHealthChecking:
    """Test health checking functionality."""

    def test_check_health_returns_healthy_when_all_servers_healthy(self, app_context):
        """Test that check_health returns healthy status when all servers are healthy."""
        deployment_id = DeploymentId("test-healthy")
        controller = DeploymentController.create_single_server(
            deployment_id, app_context
        )

        # Mock healthy server
        server = next(iter(controller.deployment.get_servers().values()))
        server.health_check_sync = Mock(
            return_value=HealthStatus(is_healthy=True, response_time=0.05)
        )

        health = controller.check_health(timeout=5.0)

        assert health.is_healthy
        assert health.response_time > 0

    def test_check_health_returns_unhealthy_when_server_unhealthy(self, app_context):
        """Test that check_health returns unhealthy status when server is unhealthy."""
        deployment_id = DeploymentId("test-unhealthy")
        controller = DeploymentController.create_single_server(
            deployment_id, app_context
        )

        # Mock unhealthy server
        server = next(iter(controller.deployment.get_servers().values()))
        server.health_check_sync = Mock(
            return_value=HealthStatus(
                is_healthy=False, response_time=0.0, error_message="Connection refused"
            )
        )

        health = controller.check_health(timeout=5.0)

        assert not health.is_healthy
        assert health.error_message is not None
        assert "unhealthy" in health.error_message.lower()

    def test_check_health_updates_deployment_health_status(self, app_context):
        """Test that check_health updates deployment health status."""
        deployment_id = DeploymentId("test-update")
        controller = DeploymentController.create_single_server(
            deployment_id, app_context
        )

        # Initially should be unhealthy (not started)
        server = next(iter(controller.deployment.get_servers().values()))
        server.health_check_sync = Mock(
            return_value=HealthStatus(is_healthy=True, response_time=0.05)
        )

        controller.check_health()

        assert controller.deployment.is_healthy()

    def test_get_health_info_returns_filtered_data(self, app_context):
        """Test that get_health_info returns data filtered to this deployment."""
        deployment_id = DeploymentId("test-filter")
        controller = DeploymentController.create_single_server(
            deployment_id, app_context
        )

        # Mock process supervisor to return some exit codes
        server_id = next(iter(controller.deployment.get_servers().keys()))
        app_context.process_supervisor.get_exit_codes.return_value = {
            server_id: 0,
            ServerId("other-server"): 1,  # Should be filtered out
        }
        app_context.process_supervisor.get_crash_state.return_value = {}

        health_info = controller.get_health_info()

        # Should only contain this deployment's server
        assert str(server_id) in health_info.exit_codes
        assert "other-server" not in health_info.exit_codes


class TestDeploymentControllerCrashHandling:
    """Test crash callback functionality."""

    def test_handle_crash_marks_deployment_unhealthy(self, app_context):
        """Test that crash callback marks deployment as unhealthy."""
        deployment_id = DeploymentId("test-crash")
        controller = DeploymentController.create_single_server(
            deployment_id, app_context
        )

        server_id = next(iter(controller.deployment.get_servers().keys()))
        crash_info = CrashInfo(
            exit_code=1,
            timestamp=time.time(),
            stderr="Segmentation fault",
            signal=11,
        )

        # Simulate crash callback
        controller._handle_crash(server_id, crash_info)

        assert not controller.deployment.is_healthy()


class TestDeploymentControllerProperties:
    """Test property accessors."""

    def test_endpoint_returns_single_server_endpoint(self, app_context):
        """Test that endpoint property returns the server endpoint for single server."""
        deployment_id = DeploymentId("test-endpoint")
        controller = DeploymentController.create_single_server(
            deployment_id, app_context
        )

        endpoint = controller.endpoint

        server = next(iter(controller.deployment.get_servers().values()))
        assert endpoint == server.endpoint

    def test_endpoints_returns_coordinator_endpoints_for_cluster(self, app_context):
        """Test that endpoints property returns coordinator endpoints for cluster."""
        deployment_id = DeploymentId("test-endpoints")
        cluster_config = ClusterConfig(agents=1, dbservers=1, coordinators=2)
        controller = DeploymentController.create_cluster(
            deployment_id, app_context, cluster_config
        )

        endpoints = controller.endpoints

        # Should return 2 coordinator endpoints
        assert len(endpoints) == 2

    def test_agency_endpoints_returns_agent_endpoints(self, app_context):
        """Test that agency_endpoints returns agent endpoints for cluster."""
        deployment_id = DeploymentId("test-agency")
        cluster_config = ClusterConfig(agents=3, dbservers=1, coordinators=1)
        controller = DeploymentController.create_cluster(
            deployment_id, app_context, cluster_config
        )

        agency_endpoints = controller.agency_endpoints

        # Should return 3 agent endpoints
        assert len(agency_endpoints) == 3

    def test_agency_endpoints_empty_for_single_server(self, app_context):
        """Test that agency_endpoints is empty for single server."""
        deployment_id = DeploymentId("test-no-agency")
        controller = DeploymentController.create_single_server(
            deployment_id, app_context
        )

        assert controller.agency_endpoints == []


class TestDeploymentControllerContextManager:
    """Test context manager support."""

    def test_context_manager_stops_on_exit(self, app_context):
        """Test that context manager stops deployment on exit."""
        deployment_id = DeploymentId("test-context")
        controller = DeploymentController.create_single_server(
            deployment_id, app_context
        )

        # Mock server
        server = next(iter(controller.deployment.get_servers().values()))
        server.start = Mock()
        server.stop = Mock()
        server.health_check_sync = Mock(
            return_value=HealthStatus(is_healthy=True, response_time=0.1)
        )

        with controller:
            controller.start(timeout=10.0)

        # Server should have been stopped
        server.stop.assert_called()


# Fixtures


@pytest.fixture
def app_context():
    """Create a mock application context for testing."""
    config = ArmadilloConfig(
        deployment_mode=DeploymentMode.SINGLE_SERVER,
        is_test_mode=True,
    )

    # Create mock context
    ctx = Mock(spec=ApplicationContext)
    ctx.config = config
    ctx.logger = Mock()

    # Mock port allocator
    port_counter = [8529]

    def allocate_port():
        port = port_counter[0]
        port_counter[0] += 1
        return port

    ctx.port_allocator = Mock()
    ctx.port_allocator.allocate_port = allocate_port
    ctx.port_allocator.release_port = Mock()

    # Mock auth provider
    ctx.auth_provider = Mock()
    ctx.auth_provider.get_auth_headers.return_value = {}

    # Mock filesystem
    ctx.filesystem = Mock()
    ctx.filesystem.server_dir.return_value = Path("/tmp/test-server")

    # Mock process supervisor
    ctx.process_supervisor = Mock()
    ctx.process_supervisor.register_crash_callback = Mock()
    ctx.process_supervisor.unregister_crash_callback = Mock()
    ctx.process_supervisor.get_exit_codes.return_value = {}
    ctx.process_supervisor.get_crash_state.return_value = {}

    # Mock cluster bootstrapper
    ctx.cluster_bootstrapper = Mock()

    return ctx
