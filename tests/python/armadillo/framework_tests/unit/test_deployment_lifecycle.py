"""Tests for deployment lifecycle and state transitions.

Tests verify deployment state transitions:
- none → deployed → shut down → redeployed
- State consistency during transitions
- Error handling during state transitions
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch

from armadillo.core.context import ApplicationContext
from armadillo.core.value_objects import DeploymentId, ServerId
from armadillo.core.types import ServerRole, ServerConfig
from armadillo.core.errors import ServerStartupError, ServerShutdownError, ServerError
from armadillo.instances.manager import InstanceManager
from armadillo.instances.deployment_plan import (
    SingleServerDeploymentPlan,
    ClusterDeploymentPlan,
)


class TestSingleServerLifecycle:
    """Test deployment lifecycle for single server deployments."""

    def test_initial_state_no_deployment(self) -> None:
        """Verify initial state has no deployment."""
        app_context = ApplicationContext.for_testing()
        manager = InstanceManager(DeploymentId("test_init"), app_context=app_context)

        # Initial state: no deployment
        assert manager._deployment is None
        assert manager.get_all_servers() == {}

    def test_deploy_creates_deployment_and_marks_deployed(self) -> None:
        """Verify deployment creates deployment object and marks it deployed."""
        app_context = ApplicationContext.for_testing()
        manager = InstanceManager(DeploymentId("test_deploy"), app_context=app_context)

        plan = SingleServerDeploymentPlan(
            server=ServerConfig(
                role=ServerRole.SINGLE,
                port=8529,
                data_dir=Path("/tmp/test"),
                log_file=Path("/tmp/test.log"),
            )
        )

        # Mock server start to succeed quickly
        with patch.object(
            manager._deployment_orchestrator._server_factory,
            "create_server_instances",
        ) as mock_create:
            mock_server = Mock()
            mock_server.server_id = ServerId("server_0")
            mock_server.start = Mock()
            mock_server.is_running.return_value = True
            mock_server.endpoint = "http://127.0.0.1:8529"

            mock_create.return_value = {ServerId("server_0"): mock_server}

            manager.deploy_servers(plan, timeout=5.0)

        # After deployment: has deployment, marked as deployed
        assert manager._deployment is not None
        assert manager._deployment.is_deployed() is True
        assert manager._deployment.get_status().is_deployed is True
        assert manager._deployment.get_timing().startup_time is not None
        assert len(manager.get_all_servers()) == 1

    def test_shutdown_marks_deployment_not_deployed(self) -> None:
        """Verify shutdown marks deployment as not deployed."""
        app_context = ApplicationContext.for_testing()
        manager = InstanceManager(
            DeploymentId("test_shutdown"), app_context=app_context
        )

        plan = SingleServerDeploymentPlan(
            server=ServerConfig(
                role=ServerRole.SINGLE,
                port=8529,
                data_dir=Path("/tmp/test"),
                log_file=Path("/tmp/test.log"),
            )
        )

        # Deploy
        with patch.object(
            manager._deployment_orchestrator._server_factory,
            "create_server_instances",
        ) as mock_create:
            mock_server = Mock()
            mock_server.server_id = ServerId("server_0")
            mock_server.start = Mock()
            mock_server.stop = Mock()
            mock_server.is_running.return_value = True
            mock_server.endpoint = "http://127.0.0.1:8529"

            mock_create.return_value = {ServerId("server_0"): mock_server}

            manager.deploy_servers(plan, timeout=5.0)
            assert manager._deployment is not None
            assert manager._deployment.is_deployed() is True

            # Shutdown
            manager.shutdown_deployment(timeout=5.0)

        # After shutdown: deployment marked as not deployed
        assert manager._deployment is not None  # Object still exists
        assert manager._deployment.is_deployed() is False
        assert manager._deployment.get_status().is_deployed is False
        assert manager._deployment.get_timing().shutdown_time is not None

    def test_redeploy_after_shutdown_works(self) -> None:
        """Verify redeployment after shutdown works correctly."""
        app_context = ApplicationContext.for_testing()
        manager = InstanceManager(
            DeploymentId("test_redeploy"), app_context=app_context
        )

        plan = SingleServerDeploymentPlan(
            server=ServerConfig(
                role=ServerRole.SINGLE,
                port=8529,
                data_dir=Path("/tmp/test"),
                log_file=Path("/tmp/test.log"),
            )
        )

        with patch.object(
            manager._deployment_orchestrator._server_factory,
            "create_server_instances",
        ) as mock_create:
            mock_server_1 = Mock()
            mock_server_1.server_id = ServerId("server_0")
            mock_server_1.start = Mock()
            mock_server_1.stop = Mock()
            mock_server_1.is_running.return_value = True
            mock_server_1.endpoint = "http://127.0.0.1:8529"

            mock_server_2 = Mock()
            mock_server_2.server_id = ServerId("server_0")
            mock_server_2.start = Mock()
            mock_server_2.stop = Mock()
            mock_server_2.is_running.return_value = True
            mock_server_2.endpoint = "http://127.0.0.1:8529"

            # First deployment
            mock_create.return_value = {ServerId("server_0"): mock_server_1}
            manager.deploy_servers(plan, timeout=5.0)
            first_deployment = manager._deployment
            assert first_deployment is not None
            assert first_deployment.is_deployed() is True
            first_startup_time = first_deployment.get_timing().startup_time

            # Shutdown
            manager.shutdown_deployment(timeout=5.0)
            assert first_deployment.is_deployed() is False

            # Redeploy (should create new deployment)
            mock_create.return_value = {ServerId("server_0"): mock_server_2}
            manager.deploy_servers(plan, timeout=5.0)
            second_deployment = manager._deployment

            # Verify second deployment is new and deployed
            assert second_deployment is not None
            assert second_deployment.is_deployed() is True
            # New deployment should have different startup time
            assert second_deployment.get_timing().startup_time != first_startup_time

    def test_deploy_already_deployed_prevents_double_deployment(self) -> None:
        """Verify attempting to deploy when already deployed is prevented."""
        app_context = ApplicationContext.for_testing()
        manager = InstanceManager(DeploymentId("test_double"), app_context=app_context)

        plan = SingleServerDeploymentPlan(
            server=ServerConfig(
                role=ServerRole.SINGLE,
                port=8529,
                data_dir=Path("/tmp/test"),
                log_file=Path("/tmp/test.log"),
            )
        )

        with patch.object(
            manager._deployment_orchestrator._server_factory,
            "create_server_instances",
        ) as mock_create:
            mock_server = Mock()
            mock_server.server_id = ServerId("server_0")
            mock_server.start = Mock()
            mock_server.is_running.return_value = True
            mock_server.endpoint = "http://127.0.0.1:8529"

            mock_create.return_value = {ServerId("server_0"): mock_server}

            # First deployment
            manager.deploy_servers(plan, timeout=5.0)
            assert manager._deployment is not None
            assert manager._deployment.is_deployed() is True

            # Second deployment attempt should raise error
            with pytest.raises(ServerError, match="already active|already deployed"):
                manager.deploy_servers(plan, timeout=5.0)

    def test_shutdown_no_deployment_is_safe(self) -> None:
        """Verify shutdown with no deployment is safe (no-op)."""
        app_context = ApplicationContext.for_testing()
        manager = InstanceManager(
            DeploymentId("test_no_shutdown"), app_context=app_context
        )

        # Shutdown without deployment should not raise error
        manager.shutdown_deployment(timeout=5.0)

        # Should still have no deployment
        assert manager._deployment is None

    def test_deploy_failure_leaves_no_deployment(self) -> None:
        """Verify deployment failure cleans up and leaves no deployment."""
        app_context = ApplicationContext.for_testing()
        manager = InstanceManager(DeploymentId("test_fail"), app_context=app_context)

        plan = SingleServerDeploymentPlan(
            server=ServerConfig(
                role=ServerRole.SINGLE,
                port=8529,
                data_dir=Path("/tmp/test"),
                log_file=Path("/tmp/test.log"),
            )
        )

        with patch.object(
            manager._deployment_orchestrator._server_factory,
            "create_server_instances",
            side_effect=ServerStartupError(
                "Startup failed", details={"server_id": "server_0"}
            ),
        ):
            with pytest.raises(ServerStartupError):
                manager.deploy_servers(plan, timeout=5.0)

        # After failed deployment: should have no deployment or not-deployed state
        # Implementation may vary - either _deployment is None or is_deployed() is False
        if manager._deployment is not None:
            assert manager._deployment.is_deployed() is False


class TestClusterLifecycle:
    """Test deployment lifecycle for cluster deployments."""

    def test_cluster_deployment_state_consistent(self) -> None:
        """Verify cluster deployment state management works correctly.

        This tests the state management at the InstanceManager level
        by patching the full deployment orchestrator execution.
        """
        app_context = ApplicationContext.for_testing()
        manager = InstanceManager(
            DeploymentId("test_cluster_state"), app_context=app_context
        )

        plan = ClusterDeploymentPlan(
            servers=[
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
        )

        # Mock at the orchestrator level to avoid complex bootstrap mocking
        from armadillo.instances.deployment import ClusterDeployment

        mock_deployment = ClusterDeployment(plan=plan, servers={})

        with patch.object(
            manager._deployment_orchestrator,
            "execute_deployment",
            return_value=mock_deployment,
        ):
            # Deploy
            manager.deploy_servers(plan, timeout=10.0)
            assert manager._deployment is not None
            assert manager._deployment.is_deployed() is True

            # Shutdown (mock the orchestrator shutdown too)
            with patch.object(manager._deployment_orchestrator, "shutdown_deployment"):
                manager.shutdown_deployment(timeout=10.0)
                assert manager._deployment is not None
                assert manager._deployment.is_deployed() is False

            # Redeploy
            manager.deploy_servers(plan, timeout=10.0)
            assert manager._deployment is not None
            assert manager._deployment.is_deployed() is True


class TestStateConsistency:
    """Test state consistency during transitions."""

    def test_deployment_status_reflects_is_deployed_method(self) -> None:
        """Verify status.is_deployed and is_deployed() method stay consistent."""
        app_context = ApplicationContext.for_testing()
        manager = InstanceManager(
            DeploymentId("test_consistency"), app_context=app_context
        )

        plan = SingleServerDeploymentPlan(
            server=ServerConfig(
                role=ServerRole.SINGLE,
                port=8529,
                data_dir=Path("/tmp/test"),
                log_file=Path("/tmp/test.log"),
            )
        )

        with patch.object(
            manager._deployment_orchestrator._server_factory,
            "create_server_instances",
        ) as mock_create:
            mock_server = Mock()
            mock_server.server_id = ServerId("server_0")
            mock_server.start = Mock()
            mock_server.stop = Mock()
            mock_server.is_running.return_value = True
            mock_server.endpoint = "http://127.0.0.1:8529"

            mock_create.return_value = {ServerId("server_0"): mock_server}

            # Deploy
            manager.deploy_servers(plan, timeout=5.0)
            assert manager._deployment is not None
            # Both should be True
            assert manager._deployment.get_status().is_deployed is True
            assert manager._deployment.is_deployed() is True

            # Shutdown
            manager.shutdown_deployment(timeout=5.0)
            assert manager._deployment is not None
            # Both should be False
            assert manager._deployment.get_status().is_deployed is False
            assert manager._deployment.is_deployed() is False

    def test_timing_information_populated_correctly(self) -> None:
        """Verify timing information is populated during lifecycle."""
        app_context = ApplicationContext.for_testing()
        manager = InstanceManager(DeploymentId("test_timing"), app_context=app_context)

        plan = SingleServerDeploymentPlan(
            server=ServerConfig(
                role=ServerRole.SINGLE,
                port=8529,
                data_dir=Path("/tmp/test"),
                log_file=Path("/tmp/test.log"),
            )
        )

        with patch.object(
            manager._deployment_orchestrator._server_factory,
            "create_server_instances",
        ) as mock_create:
            mock_server = Mock()
            mock_server.server_id = ServerId("server_0")
            mock_server.start = Mock()
            mock_server.stop = Mock()
            mock_server.is_running.return_value = True
            mock_server.endpoint = "http://127.0.0.1:8529"

            mock_create.return_value = {ServerId("server_0"): mock_server}

            # Initial: no timing
            assert manager._deployment is None

            # After deploy: startup_time set, shutdown_time None
            manager.deploy_servers(plan, timeout=5.0)
            assert manager._deployment is not None
            timing = manager._deployment.get_timing()  # type: ignore[unreachable]
            assert timing.startup_time is not None
            assert timing.shutdown_time is None

            # After shutdown: both set
            manager.shutdown_deployment(timeout=5.0)
            assert manager._deployment is not None
            assert manager._deployment.get_timing().startup_time is not None
            assert manager._deployment.get_timing().shutdown_time is not None
            assert (
                manager._deployment.get_timing().shutdown_time
                >= manager._deployment.get_timing().startup_time
            )
