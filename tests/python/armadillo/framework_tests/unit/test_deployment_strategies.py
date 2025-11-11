"""
Unit tests for new lifecycle-owning deployment strategy classes:
- SingleServerDeploymentStrategy
- ClusterDeploymentStrategy

These tests validate:
1. Correct handling of plan types
2. Server factory invocation
3. Startup order population
4. Error raising on type mismatches

They use lightweight mocks to avoid spawning real processes.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest

from armadillo.core.types import ServerConfig, ServerRole, TimeoutConfig, HealthStatus
from armadillo.core.value_objects import ServerId
from armadillo.core.errors import ServerError, ClusterError
from armadillo.instances.deployment_plan import (
    SingleServerDeploymentPlan,
    ClusterDeploymentPlan,
)
from armadillo.instances.deployment_strategy import (
    SingleServerDeploymentStrategy,
    ClusterDeploymentStrategy,
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
# SingleServerDeploymentStrategy Tests
# ---------------------------------------------------------------------------

def test_single_server_deployment_strategy_success(tmp_path):
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

    strategy = SingleServerDeploymentStrategy(logger, factory, timeouts)
    servers = strategy.deploy(plan)

    assert len(servers) == 1
    assert server_id in servers
    mock_server.start.assert_called_once()
    mock_server.health_check_sync.assert_called_once()
    assert strategy.startup_order == [server_id]


def test_single_server_deployment_strategy_wrong_plan_type(tmp_path):
    logger = DummyLogger()
    timeouts = TimeoutConfig()

    # Cluster plan passed to single strategy should raise
    cluster_plan = ClusterDeploymentPlan(servers=[])

    class MockFactory:
        def create_server_instances(self, servers_config):
            return {}

    strategy = SingleServerDeploymentStrategy(logger, MockFactory(), timeouts)

    with pytest.raises(ServerError):
        strategy.deploy(cluster_plan)


def test_single_server_deployment_strategy_health_failure(tmp_path):
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

    strategy = SingleServerDeploymentStrategy(logger, MockFactory(), timeouts)

    with pytest.raises(ServerError) as exc:
        strategy.deploy(plan)

    assert "health check failed" in str(exc.value).lower()
    mock_server.start.assert_called_once()
    mock_server.health_check_sync.assert_called_once()


# ---------------------------------------------------------------------------
# ClusterDeploymentStrategy Tests
# ---------------------------------------------------------------------------

def test_cluster_deployment_strategy_success(tmp_path, monkeypatch):
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
    def fake_bootstrap(self, servers, startup_order, timeout=0):
        # Simulate ordered startup: agents -> dbservers -> coordinators
        for role in (ServerRole.AGENT, ServerRole.DBSERVER, ServerRole.COORDINATOR):
            for sid, srv in servers.items():
                if srv.role == role:
                    startup_order.append(sid)

    monkeypatch.setattr(ClusterBootstrapper, "bootstrap_cluster", fake_bootstrap)

    from concurrent.futures import ThreadPoolExecutor
    executor = ThreadPoolExecutor(max_workers=1)

    strategy = ClusterDeploymentStrategy(
        logger, MockFactory(), executor, timeouts
    )
    servers = strategy.deploy(plan)

    assert servers == servers_dict
    order = strategy.startup_order
    # Validate order grouping
    roles_in_order = [servers_dict[sid].role for sid in order]
    # Agents first
    assert roles_in_order[:2] == [ServerRole.AGENT, ServerRole.AGENT]
    assert ServerRole.DBSERVER in roles_in_order[2:3]
    assert roles_in_order[-1] == ServerRole.COORDINATOR

    executor.shutdown(wait=True)


def test_cluster_deployment_strategy_wrong_plan_type(monkeypatch):
    logger = DummyLogger()
    timeouts = TimeoutConfig()

    class MockFactory:
        def create_server_instances(self, servers_config):
            return {}

    from concurrent.futures import ThreadPoolExecutor
    executor = ThreadPoolExecutor(max_workers=1)

    strategy = ClusterDeploymentStrategy(logger, MockFactory(), executor, timeouts)

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
        strategy.deploy(bad_plan)

    executor.shutdown(wait=True)


def test_cluster_deployment_strategy_empty_servers(monkeypatch):
    logger = DummyLogger()
    timeouts = TimeoutConfig()
    plan = ClusterDeploymentPlan(servers=[])

    class MockFactory:
        def create_server_instances(self, servers_config):
            assert servers_config == []
            return {}

    def fake_bootstrap(self, servers, startup_order, timeout=0):
        # Should not be called with empty servers; but if called, do nothing
        return

    monkeypatch.setattr(ClusterBootstrapper, "bootstrap_cluster", fake_bootstrap)

    from concurrent.futures import ThreadPoolExecutor
    executor = ThreadPoolExecutor(max_workers=1)

    strategy = ClusterDeploymentStrategy(logger, MockFactory(), executor, timeouts)
    servers = strategy.deploy(plan)

    assert servers == {}
    assert strategy.startup_order == []

    executor.shutdown(wait=True)
