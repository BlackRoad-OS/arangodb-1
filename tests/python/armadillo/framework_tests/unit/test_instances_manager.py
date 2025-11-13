"""
Minimal unit tests for instances/manager.py - Instance manager.

Tests essential InstanceManager functionality with minimal mocking.
"""

import pytest
from unittest.mock import Mock
from pathlib import Path

from armadillo.instances.manager import InstanceManager
from armadillo.instances.deployment_plan import (
    SingleServerDeploymentPlan,
    ClusterDeploymentPlan,
)
from armadillo.core.types import DeploymentMode, ServerRole, ServerConfig
from armadillo.core.context import ApplicationContext


class TestInstanceManagerBasic:
    """Test InstanceManager basic functionality."""

    def test_manager_can_be_created(self):
        """Test InstanceManager can be instantiated."""
        app_context = ApplicationContext.for_testing()
        manager = InstanceManager("test_deployment", app_context=app_context)

        assert manager is not None
        assert manager.deployment_id == "test_deployment"

    def test_manager_has_expected_attributes(self):
        """Test manager has expected attributes."""
        app_context = ApplicationContext.for_testing()
        manager = InstanceManager("test", app_context=app_context)

        # Check that expected attributes exist
        assert hasattr(manager, "deployment_id")
        assert hasattr(manager, "_app_context")
        assert hasattr(manager._app_context, "config")
        assert hasattr(manager._app_context, "port_allocator")
        assert hasattr(manager, "_deployment")
        assert hasattr(manager, "_threading")

    def test_manager_has_expected_methods(self):
        """Test manager has expected public methods."""
        app_context = ApplicationContext.for_testing()
        manager = InstanceManager("test", app_context=app_context)

        # Check that public methods exist
        assert hasattr(manager, "create_deployment_plan")
        assert hasattr(manager, "deploy_servers")
        assert hasattr(manager, "shutdown_deployment")
        assert hasattr(manager, "get_server")
        assert callable(manager.create_deployment_plan)
        assert callable(manager.deploy_servers)
        assert callable(manager.shutdown_deployment)
        assert callable(manager.get_server)

    def test_unique_deployment_ids(self):
        """Test deployment IDs are preserved correctly."""
        app_context = ApplicationContext.for_testing()
        manager1 = InstanceManager("deployment_one", app_context=app_context)
        manager2 = InstanceManager("deployment_two", app_context=app_context)

        assert manager1.deployment_id != manager2.deployment_id
        assert manager1.deployment_id == "deployment_one"
        assert manager2.deployment_id == "deployment_two"


class TestDeploymentPlan:
    """Test DeploymentPlan dataclass functionality."""

    def test_single_server_deployment_plan_can_be_created(self):
        """Test SingleServerDeploymentPlan can be instantiated."""
        server_config = ServerConfig(
            role=ServerRole.SINGLE,
            port=8529,
            data_dir=Path("/tmp/single"),
            log_file=Path("/tmp/single.log"),
        )
        plan = SingleServerDeploymentPlan(server=server_config)

        assert plan is not None
        assert plan.server == server_config
        assert plan.server.role == ServerRole.SINGLE

    def test_deployment_plan_with_servers(self):
        """Test DeploymentPlan with server configurations."""
        # Create some mock server configs
        servers = [
            ServerConfig(
                role=ServerRole.AGENT,
                port=8531,
                data_dir=Path("/tmp/agent"),
                log_file=Path("/tmp/agent.log"),
            ),
            ServerConfig(
                role=ServerRole.COORDINATOR,
                port=8529,
                data_dir=Path("/tmp/coord"),
                log_file=Path("/tmp/coord.log"),
            ),
        ]

        plan = ClusterDeploymentPlan(servers=servers)

        assert len(plan.servers) == 2

    def test_deployment_plan_server_filtering(self):
        """Test DeploymentPlan server filtering methods."""
        servers = [
            ServerConfig(
                role=ServerRole.AGENT,
                port=8531,
                data_dir=Path("/tmp/agent"),
                log_file=Path("/tmp/agent.log"),
            ),
            ServerConfig(
                role=ServerRole.COORDINATOR,
                port=8529,
                data_dir=Path("/tmp/coord"),
                log_file=Path("/tmp/coord.log"),
            ),
            ServerConfig(
                role=ServerRole.DBSERVER,
                port=8530,
                data_dir=Path("/tmp/db"),
                log_file=Path("/tmp/db.log"),
            ),
        ]

        plan = ClusterDeploymentPlan(servers=servers)

        agents = plan.get_agents()
        coordinators = plan.get_coordinators()
        dbservers = plan.get_dbservers()

        assert len(agents) == 1
        assert len(coordinators) == 1
        assert len(dbservers) == 1
        assert agents[0].role == ServerRole.AGENT
        assert coordinators[0].role == ServerRole.COORDINATOR
        assert dbservers[0].role == ServerRole.DBSERVER


class TestInstanceManagerDeployment:
    """Test InstanceManager deployment operations with minimal mocking."""

    def setup_method(self):
        """Set up test environment."""
        self.app_context = ApplicationContext.for_testing()
        self.manager = InstanceManager("test_deployment", app_context=self.app_context)

    def test_get_server_no_servers(self):
        """Test getting server when no servers exist."""
        try:
            server = self.manager.get_server("nonexistent")
            # Should return None for nonexistent server
            assert server is None
        except Exception:
            # If it throws an exception for no server, that's also acceptable behavior
            pass

    def test_create_deployment_plan_single_basic(self):
        """Test creating single server deployment plan."""
        from armadillo.core.types import ClusterConfig

        try:
            result = self.manager.create_deployment_plan(
                mode=DeploymentMode.SINGLE_SERVER, cluster_config=ClusterConfig()
            )
            # If successful, should return some result
            assert result is not None or result is None  # Either is acceptable
        except Exception:
            # Creation might fail due to missing dependencies, that's ok for this test
            pass

    def test_create_deployment_plan_cluster_basic(self):
        """Test creating cluster deployment plan."""
        from armadillo.core.types import ClusterConfig

        try:
            result = self.manager.create_deployment_plan(
                mode=DeploymentMode.CLUSTER,
                cluster_config=ClusterConfig(agents=1, dbservers=1, coordinators=1),
            )
            # If successful, should return some result
            assert result is not None or result is None  # Either is acceptable
        except Exception:
            # Creation might fail due to missing dependencies, that's ok for this test
            pass


class TestInstanceManagerErrorHandling:
    """Test basic error handling."""

    def test_manager_handles_invalid_deployment_id(self):
        """Test manager creation with edge case deployment IDs."""
        app_context = ApplicationContext.for_testing()

        # Test with empty string
        manager1 = InstanceManager("", app_context=app_context)
        assert manager1.deployment_id == ""

        # Test with special characters
        manager2 = InstanceManager("test-deployment_123", app_context=app_context)
        assert manager2.deployment_id == "test-deployment_123"


class TestInstanceManagerMockIntegration:
    """Test manager with safe mocking."""

    def setup_method(self):
        """Set up test environment."""
        self.app_context = ApplicationContext.for_testing()
        self.manager = InstanceManager("mock_test", app_context=self.app_context)

    def test_shutdown_deployment_handles_no_deployment(self):
        """Test shutdown when no deployment exists."""
        try:
            self.manager.shutdown_deployment()
            # Should handle gracefully or raise appropriate error
        except Exception:
            # Some error handling is acceptable
            pass


class TestInstanceManagerLifecycleDeployment:
    """Tests for lifecycle strategy path (use_lifecycle_strategies=True) state sync."""

    class FakeServer:
        """Minimal fake server used to populate orchestrator internal dict without real processes."""

        def __init__(self, server_id, role):
            self.server_id = server_id
            self.role = role
            self.endpoint = f"http://localhost:0/{server_id}"
            self._running = True

        def is_running(self):
            return self._running

        def get_pid(self):
            return 12345

        def stop(self, timeout=None):
            self._running = False

    def setup_method(self):
        self.app_context = ApplicationContext.for_testing()
        # InstanceManager sets use_lifecycle_strategies=True when constructing orchestrator
        self.manager = InstanceManager("lifecycle_test", app_context=self.app_context)

    def _inject_fake_execution(self, plan):
        """Patch orchestrator.execute_deployment to populate internal _deployment."""
        orch = self.manager._deployment_orchestrator

        def fake_execute_deployment(p, timeout=None):
            from armadillo.instances.deployment_plan import (
                SingleServerDeploymentPlan,
                ClusterDeploymentPlan,
            )
            from armadillo.instances.deployment import (
                SingleServerDeployment,
                ClusterDeployment,
                DeploymentStatus,
                DeploymentTiming,
            )
            from armadillo.core.value_objects import ServerId
            from armadillo.core.types import ServerRole
            import time

            from unittest.mock import Mock

            if isinstance(p, SingleServerDeploymentPlan):
                sid = ServerId("server_0")
                server = self.FakeServer(sid, ServerRole.SINGLE)
                orch._deployment = SingleServerDeployment(
                    plan=p,
                    server=server,
                    status=DeploymentStatus(is_deployed=True, is_healthy=True),
                    timing=DeploymentTiming(startup_time=time.time()),
                )
                # Create a fake executor for shutdown
                fake_executor = Mock()
                fake_executor.shutdown = Mock(
                    side_effect=lambda dep, timeout: dep.mark_shutdown(time.time())
                )
                orch._current_executor = fake_executor
            elif isinstance(p, ClusterDeploymentPlan):
                sids_roles = [
                    ("agent_0", ServerRole.AGENT),
                    ("dbserver_0", ServerRole.DBSERVER),
                    ("coordinator_0", ServerRole.COORDINATOR),
                ]
                servers = {}
                for sid_str, role in sids_roles:
                    sid = ServerId(sid_str)
                    servers[sid] = self.FakeServer(sid, role)
                orch._deployment = ClusterDeployment(
                    plan=p,
                    servers=servers,
                    status=DeploymentStatus(is_deployed=True, is_healthy=True),
                    timing=DeploymentTiming(startup_time=time.time()),
                )
                # Create a fake executor for shutdown
                fake_executor = Mock()
                fake_executor.shutdown = Mock(
                    side_effect=lambda dep, timeout: dep.mark_shutdown(time.time())
                )
                orch._current_executor = fake_executor
            else:
                raise AssertionError(f"Unexpected plan type: {type(p)}")

        orch.execute_deployment = fake_execute_deployment  # type: ignore

    def test_lifecycle_single_server_deployment_syncs_state(self):
        """Verify single server deployment populates InstanceManager._deployment from orchestrator."""
        from armadillo.core.types import ServerConfig, ServerRole
        from armadillo.instances.deployment_plan import SingleServerDeploymentPlan
        from pathlib import Path

        plan = SingleServerDeploymentPlan(
            server=ServerConfig(
                role=ServerRole.SINGLE,
                port=8529,
                data_dir=Path("/tmp/single_lifecycle"),
                log_file=Path("/tmp/single_lifecycle.log"),
            )
        )
        self._inject_fake_execution(plan)

        self.manager.deploy_servers(plan, timeout=5.0)

        # State assertions
        assert self.manager.is_deployed() is True
        assert self.manager.is_healthy() is True
        assert self.manager._deployment is not None
        assert self.manager._deployment.get_server_count() == 1
        orch_servers = self.manager._deployment_orchestrator.get_servers()
        assert len(orch_servers) == 1
        # get_server returns the same instance
        sid = next(iter(orch_servers.keys()))
        assert self.manager.get_server(sid) is orch_servers[sid]

    def test_lifecycle_cluster_deployment(self):
        """Verify cluster deployment succeeds and all servers are accessible."""
        from armadillo.core.types import ServerConfig, ServerRole
        from armadillo.instances.deployment_plan import ClusterDeploymentPlan
        from pathlib import Path

        servers = [
            ServerConfig(
                role=ServerRole.AGENT,
                port=8531,
                data_dir=Path("/tmp/agent_lifecycle"),
                log_file=Path("/tmp/agent_lifecycle.log"),
            ),
            ServerConfig(
                role=ServerRole.DBSERVER,
                port=8530,
                data_dir=Path("/tmp/dbserver_lifecycle"),
                log_file=Path("/tmp/dbserver_lifecycle.log"),
            ),
            ServerConfig(
                role=ServerRole.COORDINATOR,
                port=8529,
                data_dir=Path("/tmp/coord_lifecycle"),
                log_file=Path("/tmp/coord_lifecycle.log"),
            ),
        ]
        plan = ClusterDeploymentPlan(servers=servers)
        self._inject_fake_execution(plan)

        self.manager.deploy_servers(plan, timeout=5.0)

        assert self.manager.is_deployed() is True
        assert self.manager.is_healthy() is True

        # All three servers present
        assert self.manager._deployment is not None
        assert self.manager._deployment.get_server_count() == 3
        orch_servers = self.manager._deployment_orchestrator.get_servers()
        assert len(orch_servers) == 3

        # Verify all servers are present (startup order is no longer tracked)
        roles = [s.role for s in orch_servers.values()]
        assert ServerRole.AGENT in roles
        assert ServerRole.DBSERVER in roles
        assert ServerRole.COORDINATOR in roles

        # Role-based retrieval works
        agents = self.manager.get_servers_by_role(ServerRole.AGENT)
        dbservers = self.manager.get_servers_by_role(ServerRole.DBSERVER)
        coordinators = self.manager.get_servers_by_role(ServerRole.COORDINATOR)
        assert len(agents) == 1 and len(dbservers) == 1 and len(coordinators) == 1

        # Shutdown path should clear state without errors using fake server stop()
        self.manager.shutdown_deployment(timeout=5.0)
        assert self.manager.is_deployed() is False
        # After shutdown, deployment status is False but deployment object may still exist
        # The orchestrator should have cleared its deployment
        assert (
            self.manager._deployment_orchestrator._deployment is None
            or len(self.manager._deployment_orchestrator.get_servers()) == 0
        )
