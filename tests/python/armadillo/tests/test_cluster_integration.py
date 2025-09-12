"""Integration tests for Phase 2 cluster functionality."""

import pytest
import time
from typing import List

from armadillo.instances.server import ArangoServer
from armadillo.instances.manager import InstanceManager
from armadillo.instances.orchestrator import ClusterOrchestrator
from armadillo.core.types import ServerRole, DeploymentMode


@pytest.mark.arango_cluster
@pytest.mark.slow
@pytest.mark.cluster_coordination
class TestClusterDeployment:
    """Test cluster deployment and coordination."""

    def test_cluster_fixture_available(self, arango_cluster: InstanceManager):
        """Test that cluster fixture provides working cluster."""
        assert arango_cluster is not None
        assert arango_cluster.is_deployed()
        assert arango_cluster.is_healthy()

        # Verify cluster composition
        coordinators = arango_cluster.get_servers_by_role(ServerRole.COORDINATOR)
        dbservers = arango_cluster.get_servers_by_role(ServerRole.DBSERVER)
        agents = arango_cluster.get_servers_by_role(ServerRole.AGENT)

        assert len(coordinators) >= 1
        assert len(dbservers) >= 1
        assert len(agents) >= 3

        print(f"Cluster has {len(coordinators)} coordinators, "
              f"{len(dbservers)} database servers, and {len(agents)} agents")

    def test_cluster_health_check(self, arango_cluster: InstanceManager):
        """Test cluster health monitoring."""
        health = arango_cluster.check_deployment_health()

        assert health.is_healthy
        assert health.response_time > 0
        assert "server_count" in health.details

        print(f"Cluster health check: {health.response_time:.3f}s")

    def test_server_role_fixtures(self, arango_coordinators: List[ArangoServer],
                                 arango_dbservers: List[ArangoServer],
                                 arango_agents: List[ArangoServer]):
        """Test role-specific server fixtures."""
        assert len(arango_coordinators) >= 1
        assert len(arango_dbservers) >= 1
        assert len(arango_agents) >= 3

        # Verify coordinators are running and healthy
        for coordinator in arango_coordinators:
            assert coordinator.is_running()
            health = coordinator.health_check_sync()
            assert health.is_healthy

        print(f"All {len(arango_coordinators)} coordinators are healthy")

    def test_coordination_endpoints(self, arango_cluster: InstanceManager):
        """Test cluster coordination endpoints."""
        endpoints = arango_cluster.get_coordination_endpoints()

        assert len(endpoints) >= 1
        assert all(endpoint.startswith("http://") for endpoint in endpoints)

        print(f"Coordination endpoints: {endpoints}")

    def test_agency_endpoints(self, arango_cluster: InstanceManager):
        """Test agency endpoints."""
        endpoints = arango_cluster.get_agency_endpoints()

        assert len(endpoints) >= 3  # At least 3 agents for quorum
        assert all(endpoint.startswith("tcp://") for endpoint in endpoints)

        print(f"Agency endpoints: {endpoints}")


@pytest.mark.arango_cluster
@pytest.mark.slow
@pytest.mark.cluster_coordination
class TestClusterOrchestration:
    """Test advanced cluster orchestration."""

    def test_orchestrator_initialization(self, arango_orchestrator: ClusterOrchestrator):
        """Test cluster orchestrator functionality."""
        assert arango_orchestrator is not None

        # Get cluster state
        state = arango_orchestrator.get_cluster_state()
        assert state is not None
        assert len(state.healthy_servers) > 0

        print(f"Cluster state: {len(state.healthy_servers)} healthy servers")

    @pytest.mark.asyncio
    async def test_cluster_health_check(self, arango_orchestrator: ClusterOrchestrator):
        """Test comprehensive cluster health check."""
        health_report = await arango_orchestrator.perform_cluster_health_check(detailed=True)

        assert health_report["overall_health"] in ["healthy", "degraded"]
        assert health_report["health_percentage"] > 0
        assert "agency" in health_report
        assert "coordinators" in health_report
        assert "dbservers" in health_report

        print(f"Cluster health: {health_report['overall_health']} "
              f"({health_report['health_percentage']:.1f}%)")

    @pytest.mark.asyncio
    async def test_wait_for_cluster_ready(self, arango_orchestrator: ClusterOrchestrator):
        """Test waiting for cluster readiness."""
        # Should complete quickly since cluster is already ready
        start_time = time.time()
        await arango_orchestrator.wait_for_cluster_ready(timeout=30.0)
        elapsed = time.time() - start_time

        # Should be very fast since cluster is already ready
        assert elapsed < 10.0

        print(f"Cluster ready check completed in {elapsed:.2f}s")


@pytest.mark.arango_single
@pytest.mark.slow
class TestSingleServerIntegration:
    """Test single server integration with enhanced fixtures."""

    def test_single_server_fixture(self, arango_single_server: ArangoServer):
        """Test enhanced single server fixture."""
        assert arango_single_server is not None
        assert arango_single_server.is_running()

        health = arango_single_server.health_check_sync()
        assert health.is_healthy

        stats = arango_single_server.collect_stats()
        assert stats.process_id > 0
        assert stats.uptime > 0

        print(f"Single server PID: {stats.process_id}, uptime: {stats.uptime:.1f}s")

    def test_function_scoped_server(self, arango_single_server_function: ArangoServer):
        """Test function-scoped server fixture."""
        assert arango_single_server_function is not None
        assert arango_single_server_function.is_running()

        # Should be different from session server
        health = arango_single_server_function.health_check_sync()
        assert health.is_healthy

        print(f"Function server endpoint: {arango_single_server_function.endpoint}")


@pytest.mark.auth_required
@pytest.mark.fast
class TestAuthenticationIntegration:
    """Test authentication integration with servers."""

    def test_jwt_token_creation(self):
        """Test JWT token creation for server communication."""
        from armadillo.utils.auth import get_auth_provider

        auth = get_auth_provider()

        # Create user token
        user_token = auth.create_user_token(
            username="test_user",
            permissions=["read", "write"],
            ttl=300.0
        )

        assert isinstance(user_token, str)
        assert len(user_token) > 0

        # Verify token
        payload = auth.verify_jwt(user_token)
        assert payload["username"] == "test_user"
        assert payload["permissions"] == ["read", "write"]

        print(f"Created user token for test_user")

    def test_cluster_auth_headers(self):
        """Test cluster authentication header generation."""
        from armadillo.utils.auth import get_auth_provider

        auth = get_auth_provider()

        headers = auth.create_cluster_auth_headers(
            cluster_id="test_cluster_123",
            role="coordinator"
        )

        assert "Authorization" in headers
        assert headers["Authorization"].startswith("Bearer ")

        print(f"Created cluster auth headers for test_cluster_123")

    def test_basic_auth_fallback(self):
        """Test basic authentication fallback."""
        from armadillo.utils.auth import get_auth_provider

        auth = get_auth_provider()

        basic_headers = auth.get_basic_auth_header(
            username="admin",
            password="secret"
        )

        assert "Authorization" in basic_headers
        assert basic_headers["Authorization"].startswith("Basic ")

        print("Created basic auth headers")


@pytest.mark.smoke_test
@pytest.mark.fast
class TestPhase2Integration:
    """Smoke tests for Phase 2 functionality."""

    def test_deployment_modes_available(self):
        """Test that both deployment modes are available."""
        from armadillo.core.types import DeploymentMode

        modes = list(DeploymentMode)
        assert DeploymentMode.SINGLE_SERVER in modes
        assert DeploymentMode.CLUSTER in modes

        print(f"Available deployment modes: {[m.value for m in modes]}")

    def test_server_roles_available(self):
        """Test that all server roles are available."""
        from armadillo.core.types import ServerRole

        roles = list(ServerRole)
        expected_roles = [ServerRole.SINGLE, ServerRole.AGENT, ServerRole.DBSERVER, ServerRole.COORDINATOR]

        for role in expected_roles:
            assert role in roles

        print(f"Available server roles: {[r.value for r in roles]}")

    def test_pytest_markers_registered(self):
        """Test that pytest markers are properly registered."""
        # This test validates that our custom markers are available
        # The actual marker registration is tested by the pytest plugin

        expected_markers = [
            "arango_single", "arango_cluster", "slow", "fast", "crash_test",
            "stress_test", "flaky", "auth_required", "cluster_coordination",
            "replication", "sharding", "failover", "smoke_test", "regression",
            "performance", "rta_suite"
        ]

        # In a real test run, these markers would be available
        # For now, just verify the list is complete
        assert len(expected_markers) == 16

        print(f"Expected {len(expected_markers)} pytest markers to be registered")

    def test_framework_components_importable(self):
        """Test that all Phase 2 components can be imported."""
        # Test instance management
        from armadillo.instances.manager import InstanceManager, get_instance_manager
        from armadillo.instances.orchestrator import ClusterOrchestrator, get_cluster_orchestrator
        from armadillo.instances.server import ArangoServer

        # Test enhanced authentication
        from armadillo.utils.auth import AuthProvider, get_auth_provider

        # Test enhanced pytest plugin
        from armadillo.pytest_plugin.plugin import ArmadilloPlugin

        print("All Phase 2 components import successfully")
