"""Tests for DeploymentFactory.

Tests the factory methods for creating ArangoDB deployments:
- Single server deployment creation
- Cluster deployment creation
- Server argument building and merging
- Server configuration creation
"""

import pytest
from unittest.mock import Mock, patch, call
from pathlib import Path

from armadillo.instances.deployment_factory import DeploymentFactory
from armadillo.instances.deployment import SingleServerDeployment, ClusterDeployment
from armadillo.instances.server import ArangoServer
from armadillo.core.context import ApplicationContext
from armadillo.core.value_objects import ServerId, DeploymentId
from armadillo.core.types import (
    ServerRole,
    ClusterConfig,
    ServerConfig,
    ArmadilloConfig,
    DeploymentMode,
)


class TestCreateSingleServer:
    """Test create_single_server factory method."""

    def test_creates_single_server_deployment(self, app_context):
        """Creates SingleServerDeployment with correct deployment_id."""
        deployment_id = DeploymentId("test-single")

        with patch.object(ArangoServer, "create_single_server") as mock_create:
            mock_server = Mock(spec=ArangoServer)
            mock_create.return_value = mock_server

            deployment = DeploymentFactory.create_single_server(
                deployment_id, app_context
            )

            assert isinstance(deployment, SingleServerDeployment)
            assert deployment.deployment_id == deployment_id

    def test_creates_one_server_with_single_role(self, app_context):
        """Creates one server with correct role (SINGLE)."""
        deployment_id = DeploymentId("test-role")

        with patch.object(ArangoServer, "create_single_server") as mock_create:
            mock_server = Mock(spec=ArangoServer)
            mock_server.role = ServerRole.SINGLE
            mock_server.server_id = ServerId(str(deployment_id))
            mock_create.return_value = mock_server

            deployment = DeploymentFactory.create_single_server(
                deployment_id, app_context
            )

            assert deployment.get_server_count() == 1
            server = deployment.server
            assert server.role == ServerRole.SINGLE

    def test_port_is_zero_for_auto_allocation(self, app_context):
        """Port is set to 0 for auto-allocation."""
        deployment_id = DeploymentId("test-port")

        with patch.object(ArangoServer, "create_single_server") as mock_create:
            mock_server = Mock(spec=ArangoServer)
            mock_create.return_value = mock_server

            DeploymentFactory.create_single_server(deployment_id, app_context)

            # Verify ServerConfig was created with port=0
            call_args = mock_create.call_args
            config = call_args.kwargs["config"]
            assert config.port == 0

    def test_server_args_properly_merged(self, app_context):
        """Server args are properly merged (framework defaults + custom)."""
        deployment_id = DeploymentId("test-args")
        custom_args = {"database.directory": "/custom/path", "custom.arg": "value"}

        with patch.object(ArangoServer, "create_single_server") as mock_create:
            mock_server = Mock(spec=ArangoServer)
            mock_create.return_value = mock_server

            DeploymentFactory.create_single_server(
                deployment_id, app_context, server_args=custom_args
            )

            # Verify merged args were passed to ServerConfig
            call_args = mock_create.call_args
            config = call_args.kwargs["config"]
            args = config.args

            # Should have default authentication
            assert args["server.authentication"] == "false"
            # Should have custom args
            assert args["database.directory"] == "/custom/path"
            assert args["custom.arg"] == "value"

    def test_authentication_default_false(self, app_context):
        """server.authentication is set to 'false' by default."""
        deployment_id = DeploymentId("test-auth")

        with patch.object(ArangoServer, "create_single_server") as mock_create:
            mock_server = Mock(spec=ArangoServer)
            mock_create.return_value = mock_server

            DeploymentFactory.create_single_server(deployment_id, app_context)

            call_args = mock_create.call_args
            config = call_args.kwargs["config"]
            assert config.args["server.authentication"] == "false"

    def test_custom_args_override_defaults(self, app_context):
        """Custom args take precedence over defaults."""
        deployment_id = DeploymentId("test-override")
        custom_args = {"server.authentication": "true"}

        with patch.object(ArangoServer, "create_single_server") as mock_create:
            mock_server = Mock(spec=ArangoServer)
            mock_create.return_value = mock_server

            DeploymentFactory.create_single_server(
                deployment_id, app_context, server_args=custom_args
            )

            call_args = mock_create.call_args
            config = call_args.kwargs["config"]
            assert config.args["server.authentication"] == "true"


class TestCreateCluster:
    """Test create_cluster factory method."""

    def test_creates_cluster_deployment(self, app_context):
        """Creates ClusterDeployment with correct deployment_id."""
        deployment_id = DeploymentId("test-cluster")
        cluster_config = ClusterConfig(agents=1, dbservers=1, coordinators=1)

        with patch.object(ArangoServer, "create_cluster_server") as mock_create:
            mock_create.side_effect = lambda sid, role, port, ctx, config: Mock(
                spec=ArangoServer, server_id=sid, role=role, port=port
            )

            deployment = DeploymentFactory.create_cluster(
                deployment_id, app_context, cluster_config
            )

            assert isinstance(deployment, ClusterDeployment)
            assert deployment.deployment_id == deployment_id

    def test_creates_correct_number_of_servers(self, app_context):
        """Creates correct number of servers (agents, dbservers, coordinators)."""
        deployment_id = DeploymentId("test-count")
        cluster_config = ClusterConfig(agents=3, dbservers=2, coordinators=1)

        with patch.object(ArangoServer, "create_cluster_server") as mock_create:
            mock_create.side_effect = lambda sid, role, port, ctx, config: Mock(
                spec=ArangoServer, server_id=sid, role=role, port=port
            )

            deployment = DeploymentFactory.create_cluster(
                deployment_id, app_context, cluster_config
            )

            assert deployment.get_server_count() == 6  # 3 + 2 + 1

            agents = deployment.get_servers_by_role(ServerRole.AGENT)
            dbservers = deployment.get_servers_by_role(ServerRole.DBSERVER)
            coordinators = deployment.get_servers_by_role(ServerRole.COORDINATOR)

            assert len(agents) == 3
            assert len(dbservers) == 2
            assert len(coordinators) == 1

    def test_servers_have_unique_ids(self, app_context):
        """Servers have unique IDs."""
        deployment_id = DeploymentId("test-unique")
        cluster_config = ClusterConfig(agents=2, dbservers=2, coordinators=2)

        with patch.object(ArangoServer, "create_cluster_server") as mock_create:
            mock_create.side_effect = lambda sid, role, port, ctx, config: Mock(
                spec=ArangoServer, server_id=sid, role=role, port=port
            )

            deployment = DeploymentFactory.create_cluster(
                deployment_id, app_context, cluster_config
            )

            server_ids = list(deployment.get_servers().keys())
            assert len(server_ids) == len(set(server_ids))  # All unique

    def test_agent_ports_allocated_and_agency_endpoints_built(self, app_context):
        """Agent ports are allocated and agency endpoints are built correctly."""
        deployment_id = DeploymentId("test-agency")
        cluster_config = ClusterConfig(agents=3, dbservers=1, coordinators=1)

        created_servers = []

        def capture_server(sid, role, port, ctx, config):
            server = Mock(spec=ArangoServer, server_id=sid, role=role, port=port)
            created_servers.append((role, port, config))
            return server

        with patch.object(ArangoServer, "create_cluster_server", side_effect=capture_server):
            DeploymentFactory.create_cluster(deployment_id, app_context, cluster_config)

            # Get agent configs
            agent_configs = [(role, port, cfg) for role, port, cfg in created_servers if role == ServerRole.AGENT]
            assert len(agent_configs) == 3

            # Verify all agents have agency.endpoint with all 3 endpoints
            for role, port, config in agent_configs:
                agency_endpoints = config.args["agency.endpoint"]
                assert len(agency_endpoints) == 3
                # All should point to tcp://127.0.0.1:<port>
                for endpoint in agency_endpoints:
                    assert endpoint.startswith("tcp://127.0.0.1:")

    def test_server_args_properly_merged_in_cluster(self, app_context):
        """Server args are properly merged in cluster."""
        deployment_id = DeploymentId("test-cluster-args")
        cluster_config = ClusterConfig(agents=1, dbservers=1, coordinators=1)
        custom_args = {"custom.setting": "value"}

        created_servers = []

        def capture_server(sid, role, port, ctx, config):
            server = Mock(spec=ArangoServer, server_id=sid, role=role, port=port)
            created_servers.append((role, config))
            return server

        with patch.object(ArangoServer, "create_cluster_server", side_effect=capture_server):
            DeploymentFactory.create_cluster(
                deployment_id, app_context, cluster_config, server_args=custom_args
            )

            # All servers should have custom args
            for role, config in created_servers:
                assert config.args["custom.setting"] == "value"
                assert config.args["server.authentication"] == "false"


class TestBuildServerArgs:
    """Test _build_server_args helper method."""

    def test_merges_defaults_with_custom_args(self, app_context):
        """Merges defaults with custom args (custom takes precedence)."""
        custom_args = {"custom.key": "custom_value", "log.level": "debug"}

        merged = DeploymentFactory._build_server_args(app_context, custom_args)

        # Should have custom args
        assert merged["custom.key"] == "custom_value"
        assert merged["log.level"] == "debug"
        # Should have default authentication
        assert merged["server.authentication"] == "false"

    def test_sets_authentication_to_false(self, app_context):
        """Sets server.authentication to 'false'."""
        merged = DeploymentFactory._build_server_args(app_context)

        assert merged["server.authentication"] == "false"

    def test_custom_args_override_authentication(self, app_context):
        """Custom args can override authentication."""
        custom_args = {"server.authentication": "true"}

        merged = DeploymentFactory._build_server_args(app_context, custom_args)

        assert merged["server.authentication"] == "true"


class TestBuildAgentArgs:
    """Test _build_agent_args helper method."""

    def test_sets_agency_specific_arguments(self, app_context):
        """Sets correct agency-specific arguments."""
        base_args = {"server.authentication": "false"}
        port = 8529
        count = 3
        agency_endpoints = [
            "tcp://127.0.0.1:8529",
            "tcp://127.0.0.1:8530",
            "tcp://127.0.0.1:8531",
        ]

        args = DeploymentFactory._build_agent_args(
            base_args, port, count, agency_endpoints
        )

        assert args["agency.activate"] == "true"
        assert args["agency.size"] == "3"
        assert args["agency.supervision"] == "true"
        assert args["agency.my-address"] == "tcp://127.0.0.1:8529"
        assert args["agency.endpoint"] == agency_endpoints

    def test_preserves_base_args(self, app_context):
        """Preserves base args when building agent args."""
        base_args = {"server.authentication": "false", "custom.key": "value"}
        port = 8529
        count = 1
        agency_endpoints = ["tcp://127.0.0.1:8529"]

        args = DeploymentFactory._build_agent_args(
            base_args, port, count, agency_endpoints
        )

        assert args["server.authentication"] == "false"
        assert args["custom.key"] == "value"


class TestBuildDbserverArgs:
    """Test _build_dbserver_args helper method."""

    def test_sets_cluster_arguments(self, app_context):
        """Sets correct cluster arguments for dbserver."""
        base_args = {"server.authentication": "false"}
        port = 8530
        agency_endpoints = ["tcp://127.0.0.1:8529"]

        args = DeploymentFactory._build_dbserver_args(base_args, port, agency_endpoints)

        assert args["cluster.my-role"] == "PRIMARY"
        assert args["cluster.my-address"] == "tcp://127.0.0.1:8530"
        assert args["cluster.agency-endpoint"] == "tcp://127.0.0.1:8529"

    def test_uses_first_agency_endpoint(self, app_context):
        """Uses first agency endpoint for cluster connection."""
        base_args = {}
        port = 8530
        agency_endpoints = [
            "tcp://127.0.0.1:8529",
            "tcp://127.0.0.1:8531",
            "tcp://127.0.0.1:8532",
        ]

        args = DeploymentFactory._build_dbserver_args(base_args, port, agency_endpoints)

        assert args["cluster.agency-endpoint"] == "tcp://127.0.0.1:8529"


class TestBuildCoordinatorArgs:
    """Test _build_coordinator_args helper method."""

    def test_sets_coordinator_arguments(self, app_context):
        """Sets correct cluster + coordinator arguments."""
        base_args = {"server.authentication": "false"}
        port = 8531
        agency_endpoints = ["tcp://127.0.0.1:8529"]

        args = DeploymentFactory._build_coordinator_args(
            base_args, port, agency_endpoints
        )

        assert args["cluster.my-role"] == "COORDINATOR"
        assert args["cluster.my-address"] == "tcp://127.0.0.1:8531"
        assert args["cluster.agency-endpoint"] == "tcp://127.0.0.1:8529"
        assert args["foxx.force-update-on-startup"] == "true"
        assert args["cluster.default-replication-factor"] == "2"

    def test_uses_first_agency_endpoint(self, app_context):
        """Uses first agency endpoint for cluster connection."""
        base_args = {}
        port = 8531
        agency_endpoints = [
            "tcp://127.0.0.1:8529",
            "tcp://127.0.0.1:8530",
            "tcp://127.0.0.1:8532",
        ]

        args = DeploymentFactory._build_coordinator_args(
            base_args, port, agency_endpoints
        )

        assert args["cluster.agency-endpoint"] == "tcp://127.0.0.1:8529"


class TestCreateServerConfig:
    """Test _create_server_config helper method."""

    def test_creates_server_config_with_parameters(self, app_context):
        """Creates ServerConfig with the given parameters."""
        role = ServerRole.SINGLE
        port = 8529
        data_dir = Path("/tmp/test/data")
        args = {"server.authentication": "false"}

        config = DeploymentFactory._create_server_config(role, port, data_dir, args)

        assert isinstance(config, ServerConfig)
        assert config.role == role
        assert config.port == port
        assert config.data_dir == data_dir
        assert config.args == args

    def test_sets_log_file_in_parent_directory(self, app_context):
        """Sets log file in parent directory of data_dir."""
        role = ServerRole.SINGLE
        port = 8529
        data_dir = Path("/tmp/test/server/data")
        args = {}

        config = DeploymentFactory._create_server_config(role, port, data_dir, args)

        assert config.log_file == Path("/tmp/test/server/arangodb.log")


class TestCreateAgents:
    """Test _create_agents helper method."""

    def test_returns_correct_number_of_agents(self, app_context):
        """Returns correct number of agents + agency endpoints."""
        deployment_id = DeploymentId("test-agents")
        merged_args = {"server.authentication": "false"}
        count = 3

        with patch.object(ArangoServer, "create_cluster_server") as mock_create:
            mock_create.side_effect = lambda sid, role, port, ctx, config: Mock(
                spec=ArangoServer, server_id=sid, role=role, port=port
            )

            servers, agency_endpoints = DeploymentFactory._create_agents(
                deployment_id, app_context, merged_args, count
            )

            assert len(servers) == 3
            assert len(agency_endpoints) == 3

    def test_agents_have_correct_ids(self, app_context):
        """Agents have correct server IDs."""
        deployment_id = DeploymentId("test-ids")
        merged_args = {}
        count = 2

        with patch.object(ArangoServer, "create_cluster_server") as mock_create:
            mock_create.side_effect = lambda sid, role, port, ctx, config: Mock(
                spec=ArangoServer, server_id=sid, role=role, port=port
            )

            servers, _ = DeploymentFactory._create_agents(
                deployment_id, app_context, merged_args, count
            )

            server_ids = list(servers.keys())
            assert str(server_ids[0]) == "test-ids-agent-0"
            assert str(server_ids[1]) == "test-ids-agent-1"

    def test_agency_endpoints_match_ports(self, app_context):
        """Agency endpoints match allocated ports."""
        deployment_id = DeploymentId("test-endpoints")
        merged_args = {}
        count = 2

        # Track allocated ports - save original allocator
        allocated_ports = []
        original_allocate = app_context.port_allocator.allocate_port

        def track_port():
            port = original_allocate()
            allocated_ports.append(port)
            return port

        app_context.port_allocator.allocate_port = track_port

        with patch.object(ArangoServer, "create_cluster_server") as mock_create:
            mock_create.side_effect = lambda sid, role, port, ctx, config: Mock(
                spec=ArangoServer, server_id=sid, role=role, port=port
            )

            _, agency_endpoints = DeploymentFactory._create_agents(
                deployment_id, app_context, merged_args, count
            )

            for port, endpoint in zip(allocated_ports, agency_endpoints):
                assert endpoint == f"tcp://127.0.0.1:{port}"


class TestCreateDbservers:
    """Test _create_dbservers helper method."""

    def test_returns_correct_number_of_dbservers(self, app_context):
        """Returns correct number of dbservers."""
        deployment_id = DeploymentId("test-dbservers")
        merged_args = {}
        count = 2
        agency_endpoints = ["tcp://127.0.0.1:8529"]

        with patch.object(ArangoServer, "create_cluster_server") as mock_create:
            mock_create.side_effect = lambda sid, role, port, ctx, config: Mock(
                spec=ArangoServer, server_id=sid, role=role, port=port
            )

            servers = DeploymentFactory._create_dbservers(
                deployment_id, app_context, merged_args, count, agency_endpoints
            )

            assert len(servers) == 2

    def test_dbservers_have_correct_ids(self, app_context):
        """Dbservers have correct server IDs."""
        deployment_id = DeploymentId("test-ids")
        merged_args = {}
        count = 2
        agency_endpoints = ["tcp://127.0.0.1:8529"]

        with patch.object(ArangoServer, "create_cluster_server") as mock_create:
            mock_create.side_effect = lambda sid, role, port, ctx, config: Mock(
                spec=ArangoServer, server_id=sid, role=role, port=port
            )

            servers = DeploymentFactory._create_dbservers(
                deployment_id, app_context, merged_args, count, agency_endpoints
            )

            server_ids = list(servers.keys())
            assert str(server_ids[0]) == "test-ids-dbserver-0"
            assert str(server_ids[1]) == "test-ids-dbserver-1"


class TestCreateCoordinators:
    """Test _create_coordinators helper method."""

    def test_returns_correct_number_of_coordinators(self, app_context):
        """Returns correct number of coordinators."""
        deployment_id = DeploymentId("test-coordinators")
        merged_args = {}
        count = 2
        agency_endpoints = ["tcp://127.0.0.1:8529"]

        with patch.object(ArangoServer, "create_cluster_server") as mock_create:
            mock_create.side_effect = lambda sid, role, port, ctx, config: Mock(
                spec=ArangoServer, server_id=sid, role=role, port=port
            )

            servers = DeploymentFactory._create_coordinators(
                deployment_id, app_context, merged_args, count, agency_endpoints
            )

            assert len(servers) == 2

    def test_coordinators_have_correct_ids(self, app_context):
        """Coordinators have correct server IDs."""
        deployment_id = DeploymentId("test-ids")
        merged_args = {}
        count = 2
        agency_endpoints = ["tcp://127.0.0.1:8529"]

        with patch.object(ArangoServer, "create_cluster_server") as mock_create:
            mock_create.side_effect = lambda sid, role, port, ctx, config: Mock(
                spec=ArangoServer, server_id=sid, role=role, port=port
            )

            servers = DeploymentFactory._create_coordinators(
                deployment_id, app_context, merged_args, count, agency_endpoints
            )

            server_ids = list(servers.keys())
            assert str(server_ids[0]) == "test-ids-coordinator-0"
            assert str(server_ids[1]) == "test-ids-coordinator-1"


# Fixtures


@pytest.fixture
def app_context():
    """Create a mock application context for testing."""
    config = ArmadilloConfig(
        deployment_mode=DeploymentMode.SINGLE_SERVER,
        is_test_mode=True,
    )

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

    # Mock filesystem
    ctx.filesystem = Mock()
    ctx.filesystem.server_dir = Mock(
        side_effect=lambda x: Path(f"/tmp/test/{x}")
    )

    return ctx
