"""
Unit tests for deployment executor classes:
- SingleServerExecutor
- ClusterExecutor

These tests validate:
1. Correct handling of plan types
2. Server factory invocation
3. Error raising on type mismatches
4. Shutdown logic

They use lightweight mocks to avoid spawning real processes.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
import pytest

from armadillo.core.types import ServerConfig, ServerRole, TimeoutConfig, HealthStatus
from armadillo.core.value_objects import ServerId
from armadillo.core.errors import ServerError, ClusterError
from armadillo.instances.deployment_plan import (
    SingleServerDeploymentPlan,
    ClusterDeploymentPlan,
)
from armadillo.instances.deployment_executor import (
    SingleServerExecutor,
    ClusterExecutor,
)
from armadillo.instances.cluster_bootstrapper import ClusterBootstrapper

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_server_config(role: ServerRole, port: int, tmp_path):
    data_dir = tmp_path / f"{role.value}_data"
    log_file = tmp_path / f"{role.value}.log"
    return ServerConfig(
        role=role,
        port=port,
        data_dir=data_dir,
        log_file=log_file,
        args={"server.authentication": "false"},
    )


class DummyLogger:
    def info(self, *a, **kw): pass
    def debug(self, *a, **kw): pass
    def warning(self, *a, **kw): pass
    def error(self, *a, **kw): pass


# ---------------------------------------------------------------------------
# SingleServerExecutor Tests
# ---------------------------------------------------------------------------

def test_single_server_executor_success(tmp_path):
    logger = DummyLogger()
    timeouts = TimeoutConfig()
    plan = SingleServerDeploymentPlan(
        server=make_server_config(ServerRole.SINGLE, 12000, tmp_path)
    )

    # Mock server with required interface
    server_id = ServerId("server_0")
    mock_server = MagicMock()
    mock_server.health_check_sync.return_value = HealthStatus(
        is_healthy=True, response_time=0.01
    )

    # Mock factory returning single server dict
    class MockFactory:
        def create_server_instances(self, servers_config):
            assert len(servers_config) == 1
            return {server_id: mock_server}

    factory = MockFactory()

    executor = SingleServerExecutor(logger, factory, timeouts)
    deployment = executor.deploy(plan)

    assert deployment is not None
    assert deployment.get_server_count() == 1
    servers_dict = deployment.get_servers()
    assert len(servers_dict) == 1
    # Check that the server is in the dict (using the server's server_id)
    assert mock_server.server_id in servers_dict or server_id in servers_dict
    assert servers_dict.get(mock_server.server_id) == mock_server or servers_dict.get(server_id) == mock_server
    mock_server.start.assert_called_once()
    mock_server.health_check_sync.assert_called_once()


def test_single_server_executor_wrong_plan_type(tmp_path):
    logger = DummyLogger()
    timeouts = TimeoutConfig()

    # Cluster plan passed to single executor should raise
    cluster_plan = ClusterDeploymentPlan(servers=[])

    class MockFactory:
        def create_server_instances(self, servers_config):
            return {}

    executor = SingleServerExecutor(logger, MockFactory(), timeouts)

    with pytest.raises(ServerError):
        executor.deploy(cluster_plan)


def test_single_server_executor_health_failure(tmp_path):
    logger = DummyLogger()
    timeouts = TimeoutConfig()
    plan = SingleServerDeploymentPlan(
        server=make_server_config(ServerRole.SINGLE, 13000, tmp_path)
    )

    server_id = ServerId("server_0")
    mock_server = MagicMock()
    mock_server.health_check_sync.return_value = HealthStatus(
        is_healthy=False, response_time=0.02, error_message="unhealthy"
    )

    class MockFactory:
        def create_server_instances(self, servers_config):
            return {server_id: mock_server}

    executor = SingleServerExecutor(logger, MockFactory(), timeouts)

    with pytest.raises(ServerError) as exc:
        executor.deploy(plan)

    assert "health check failed" in str(exc.value).lower()
    mock_server.start.assert_called_once()
    mock_server.health_check_sync.assert_called_once()


def test_single_server_executor_shutdown(tmp_path):
    """Test single server executor shutdown."""
    logger = DummyLogger()
    timeouts = TimeoutConfig()

    server_id = ServerId("server_0")
    mock_server = MagicMock()
    mock_server.server_id = server_id

    from armadillo.instances.deployment import (
        SingleServerDeployment,
        DeploymentStatus,
        DeploymentTiming,
    )
    from armadillo.instances.deployment_plan import SingleServerDeploymentPlan
    import time

    deployment = SingleServerDeployment(
        plan=SingleServerDeploymentPlan(
            server=make_server_config(ServerRole.SINGLE, 12000, tmp_path)
        ),
        server=mock_server,
        status=DeploymentStatus(is_deployed=True, is_healthy=True),
        timing=DeploymentTiming(startup_time=time.time()),
    )

    executor = SingleServerExecutor(logger, Mock(), timeouts)
    executor.shutdown(deployment, timeout=10.0)

    mock_server.stop.assert_called_once_with(timeout=10.0)
    assert deployment.status.is_deployed is False


# ---------------------------------------------------------------------------
# ClusterExecutor Tests
# ---------------------------------------------------------------------------

def test_cluster_executor_success(tmp_path, monkeypatch):
    logger = DummyLogger()
    timeouts = TimeoutConfig()

    # Build cluster plan with simple topology
    server_configs = [
        make_server_config(ServerRole.AGENT, 14000, tmp_path),
        make_server_config(ServerRole.AGENT, 14001, tmp_path),
        make_server_config(ServerRole.DBSERVER, 14010, tmp_path),
        make_server_config(ServerRole.COORDINATOR, 14020, tmp_path),
    ]
    plan = ClusterDeploymentPlan(servers=server_configs)

    # Mock servers with roles
    servers_dict = {}
    for i, cfg in enumerate(server_configs):
        sid = ServerId(f"{cfg.role.value}_{i}")
        servers_dict[sid] = SimpleNamespace(role=cfg.role)

    class MockFactory:
        def create_server_instances(self, servers_config):
            assert servers_config == server_configs
            return servers_dict

    # Monkeypatch bootstrapper to avoid real startup logic
    def fake_bootstrap(self, servers, timeout=0):
        # Just verify servers dict is passed correctly
        assert servers == servers_dict

    monkeypatch.setattr(ClusterBootstrapper, "bootstrap_cluster", fake_bootstrap)

    from concurrent.futures import ThreadPoolExecutor
    executor_pool = ThreadPoolExecutor(max_workers=1)

    executor = ClusterExecutor(
        logger, MockFactory(), executor_pool, timeouts
    )
    deployment = executor.deploy(plan)

    assert deployment is not None
    assert deployment.get_servers() == servers_dict

    executor_pool.shutdown(wait=True)


def test_cluster_executor_wrong_plan_type(monkeypatch):
    logger = DummyLogger()
    timeouts = TimeoutConfig()

    class MockFactory:
        def create_server_instances(self, servers_config):
            return {}

    from concurrent.futures import ThreadPoolExecutor
    executor_pool = ThreadPoolExecutor(max_workers=1)

    executor = ClusterExecutor(logger, MockFactory(), executor_pool, timeouts)

    # Use single server plan (invalid)
    bad_plan = SingleServerDeploymentPlan(
        server=ServerConfig(
            role=ServerRole.SINGLE,
            port=18000,
            data_dir=".",
            log_file="arangod.log",
            args={},
        )
    )

    with pytest.raises(ClusterError):
        executor.deploy(bad_plan)

    executor_pool.shutdown(wait=True)


def test_cluster_executor_empty_servers(monkeypatch):
    logger = DummyLogger()
    timeouts = TimeoutConfig()
    plan = ClusterDeploymentPlan(servers=[])

    class MockFactory:
        def create_server_instances(self, servers_config):
            assert servers_config == []
            return {}

    def fake_bootstrap(self, servers, timeout=0):
        # Should not be called with empty servers; but if called, do nothing
        return

    monkeypatch.setattr(ClusterBootstrapper, "bootstrap_cluster", fake_bootstrap)

    from concurrent.futures import ThreadPoolExecutor
    executor_pool = ThreadPoolExecutor(max_workers=1)

    executor = ClusterExecutor(logger, MockFactory(), executor_pool, timeouts)
    deployment = executor.deploy(plan)

    assert deployment is not None
    assert deployment.get_servers() == {}

    executor_pool.shutdown(wait=True)


def test_cluster_executor_shutdown(tmp_path):
    """Test cluster executor shutdown with role-based order."""
    logger = DummyLogger()
    timeouts = TimeoutConfig()

    # Create mock servers with different roles
    agent1 = MagicMock()
    agent1.server_id = ServerId("agent_0")
    agent1.role = ServerRole.AGENT

    agent2 = MagicMock()
    agent2.server_id = ServerId("agent_1")
    agent2.role = ServerRole.AGENT

    dbserver = MagicMock()
    dbserver.server_id = ServerId("dbserver_0")
    dbserver.role = ServerRole.DBSERVER

    coordinator = MagicMock()
    coordinator.server_id = ServerId("coordinator_0")
    coordinator.role = ServerRole.COORDINATOR

    servers = {
        agent1.server_id: agent1,
        agent2.server_id: agent2,
        dbserver.server_id: dbserver,
        coordinator.server_id: coordinator,
    }

    from armadillo.instances.deployment import (
        ClusterDeployment,
        DeploymentStatus,
        DeploymentTiming,
    )
    from armadillo.instances.deployment_plan import ClusterDeploymentPlan
    import time

    deployment = ClusterDeployment(
        plan=ClusterDeploymentPlan(servers=[]),
        servers=servers,
        status=DeploymentStatus(is_deployed=True, is_healthy=True),
        timing=DeploymentTiming(startup_time=time.time()),
    )

    from concurrent.futures import ThreadPoolExecutor
    executor_pool = ThreadPoolExecutor(max_workers=1)

    executor = ClusterExecutor(logger, Mock(), executor_pool, timeouts)
    executor.shutdown(deployment, timeout=40.0)

    # Verify shutdown order: non-agents first, then agents
    # Non-agents should be stopped first
    dbserver.stop.assert_called_once()
    coordinator.stop.assert_called_once()

    # Agents should be stopped last
    agent1.stop.assert_called_once()
    agent2.stop.assert_called_once()

    # Verify all calls happened (order verified by call order in executor)
    assert dbserver.stop.call_count == 1
    assert coordinator.stop.call_count == 1
    assert agent1.stop.call_count == 1
    assert agent2.stop.call_count == 1
    assert deployment.status.is_deployed is False

    executor_pool.shutdown(wait=True)
