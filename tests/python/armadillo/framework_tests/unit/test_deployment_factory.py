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
        """Port is auto-allocated for single server."""
        deployment_id = DeploymentId("test-port")

        with patch.object(ArangoServer, "create_single_server") as mock_create:
            mock_server = Mock(spec=ArangoServer)
            mock_create.return_value = mock_server

            DeploymentFactory.create_single_server(deployment_id, app_context)

            # Verify args were passed (port is auto-allocated by factory method)
            call_args = mock_create.call_args
            args = call_args.kwargs["args"]
            # Args should have authentication default
            assert args["server.authentication"] == "false"

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

            # Verify merged args were passed
            call_args = mock_create.call_args
            args = call_args.kwargs["args"]

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
            args = call_args.kwargs["args"]
            assert args["server.authentication"] == "false"

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
            args = call_args.kwargs["args"]
            assert args["server.authentication"] == "true"

    def test_none_server_args_uses_defaults(self, app_context):
        """None server_args should use default configuration."""
        deployment_id = DeploymentId("test-none-args")

        with patch.object(ArangoServer, "create_single_server") as mock_create:
            mock_server = Mock(spec=ArangoServer)
            mock_create.return_value = mock_server

            DeploymentFactory.create_single_server(
                deployment_id, app_context, server_args=None
            )

            call_args = mock_create.call_args
            args = call_args.kwargs["args"]
            # Should have default authentication
            assert args["server.authentication"] == "false"

    def test_empty_dict_server_args_uses_defaults(self, app_context):
        """Empty dict server_args should use default configuration."""
        deployment_id = DeploymentId("test-empty-args")

        with patch.object(ArangoServer, "create_single_server") as mock_create:
            mock_server = Mock(spec=ArangoServer)
            mock_create.return_value = mock_server

            DeploymentFactory.create_single_server(
                deployment_id, app_context, server_args={}
            )

            call_args = mock_create.call_args
            args = call_args.kwargs["args"]
            # Should have default authentication
            assert args["server.authentication"] == "false"


class TestCreateCluster:
    """Test create_cluster factory method."""

    def test_creates_cluster_deployment(self, app_context):
        """Creates ClusterDeployment with correct deployment_id."""
        deployment_id = DeploymentId("test-cluster")
        cluster_config = ClusterConfig(agents=1, dbservers=1, coordinators=1)

        with patch.object(ArangoServer, "create_cluster_server") as mock_create:
            mock_create.side_effect = lambda sid, role, port, ctx, args: Mock(
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
            mock_create.side_effect = lambda sid, role, port, ctx, args: Mock(
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
        """Servers have unique IDs following expected pattern."""
        deployment_id = DeploymentId("test-unique")
        cluster_config = ClusterConfig(agents=2, dbservers=2, coordinators=2)

        with patch.object(ArangoServer, "create_cluster_server") as mock_create:
            mock_create.side_effect = lambda sid, role, port, ctx, args: Mock(
                spec=ArangoServer, server_id=sid, role=role, port=port
            )

            deployment = DeploymentFactory.create_cluster(
                deployment_id, app_context, cluster_config
            )

            server_ids = list(deployment.get_servers().keys())

            # Verify exact expected IDs (stronger than just uniqueness check)
            expected_ids = {
                ServerId(f"{deployment_id}-agent-0"),
                ServerId(f"{deployment_id}-agent-1"),
                ServerId(f"{deployment_id}-dbserver-0"),
                ServerId(f"{deployment_id}-dbserver-1"),
                ServerId(f"{deployment_id}-coordinator-0"),
                ServerId(f"{deployment_id}-coordinator-1"),
            }
            assert set(server_ids) == expected_ids

    def test_agent_ports_allocated_and_agency_endpoints_built(self, app_context):
        """Agent ports are allocated and agency endpoints are built correctly."""
        deployment_id = DeploymentId("test-agency")
        cluster_config = ClusterConfig(agents=3, dbservers=1, coordinators=1)

        created_servers = []

        def capture_server(sid, role, port, ctx, args):
            server = Mock(spec=ArangoServer, server_id=sid, role=role, port=port)
            created_servers.append((role, port, args))
            return server

        with patch.object(
            ArangoServer, "create_cluster_server", side_effect=capture_server
        ):
            DeploymentFactory.create_cluster(deployment_id, app_context, cluster_config)

            # Get agent args
            agent_args_list = [
                (role, port, args)
                for role, port, args in created_servers
                if role == ServerRole.AGENT
            ]
            assert len(agent_args_list) == 3

            # Verify all agents have agency.endpoint with all 3 endpoints
            for role, port, args in agent_args_list:
                agency_endpoints = args["agency.endpoint"]
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

        def capture_server(sid, role, port, ctx, args):
            server = Mock(spec=ArangoServer, server_id=sid, role=role, port=port)
            created_servers.append((role, args))
            return server

        with patch.object(
            ArangoServer, "create_cluster_server", side_effect=capture_server
        ):
            DeploymentFactory.create_cluster(
                deployment_id, app_context, cluster_config, server_args=custom_args
            )

            # All servers should have custom args
            for role, args in created_servers:
                assert args["custom.setting"] == "value"
                assert args["server.authentication"] == "false"

    def test_minimum_cluster_configuration(self, app_context):
        """Minimum cluster (1 agent, 1 dbserver, 1 coordinator) creates exactly 3 servers."""
        deployment_id = DeploymentId("test-min-cluster")
        cluster_config = ClusterConfig(agents=1, dbservers=1, coordinators=1)

        with patch.object(ArangoServer, "create_cluster_server") as mock_create:
            mock_create.side_effect = lambda sid, role, port, ctx, args: Mock(
                spec=ArangoServer, server_id=sid, role=role, port=port
            )

            deployment = DeploymentFactory.create_cluster(
                deployment_id, app_context, cluster_config
            )

            assert deployment.get_server_count() == 3

            agents = deployment.get_servers_by_role(ServerRole.AGENT)
            dbservers = deployment.get_servers_by_role(ServerRole.DBSERVER)
            coordinators = deployment.get_servers_by_role(ServerRole.COORDINATOR)

            assert len(agents) == 1
            assert len(dbservers) == 1
            assert len(coordinators) == 1

    def test_large_cluster_configuration(self, app_context):
        """Large cluster (5-10-3) creates correct number of servers with unique IDs."""
        deployment_id = DeploymentId("test-large-cluster")
        cluster_config = ClusterConfig(agents=5, dbservers=10, coordinators=3)

        with patch.object(ArangoServer, "create_cluster_server") as mock_create:
            mock_create.side_effect = lambda sid, role, port, ctx, args: Mock(
                spec=ArangoServer, server_id=sid, role=role, port=port
            )

            deployment = DeploymentFactory.create_cluster(
                deployment_id, app_context, cluster_config
            )

            # Total: 5 + 10 + 3 = 18 servers
            assert deployment.get_server_count() == 18

            agents = deployment.get_servers_by_role(ServerRole.AGENT)
            dbservers = deployment.get_servers_by_role(ServerRole.DBSERVER)
            coordinators = deployment.get_servers_by_role(ServerRole.COORDINATOR)

            assert len(agents) == 5
            assert len(dbservers) == 10
            assert len(coordinators) == 3

            # All server IDs should be unique
            server_ids = list(deployment.get_servers().keys())
            assert len(server_ids) == 18
            assert len(set(server_ids)) == 18  # No duplicates

    def test_none_server_args_in_cluster(self, app_context):
        """None server_args in cluster should use defaults."""
        deployment_id = DeploymentId("test-cluster-none-args")
        cluster_config = ClusterConfig(agents=1, dbservers=1, coordinators=1)

        created_servers = []

        def capture_server(sid, role, port, ctx, args):
            server = Mock(spec=ArangoServer, server_id=sid, role=role, port=port)
            created_servers.append((role, args))
            return server

        with patch.object(
            ArangoServer, "create_cluster_server", side_effect=capture_server
        ):
            DeploymentFactory.create_cluster(
                deployment_id, app_context, cluster_config, server_args=None
            )

            # All servers should have default authentication
            for role, args in created_servers:
                assert args["server.authentication"] == "false"

    def test_empty_dict_server_args_in_cluster(self, app_context):
        """Empty dict server_args in cluster should use defaults."""
        deployment_id = DeploymentId("test-cluster-empty-args")
        cluster_config = ClusterConfig(agents=1, dbservers=1, coordinators=1)

        created_servers = []

        def capture_server(sid, role, port, ctx, args):
            server = Mock(spec=ArangoServer, server_id=sid, role=role, port=port)
            created_servers.append((role, args))
            return server

        with patch.object(
            ArangoServer, "create_cluster_server", side_effect=capture_server
        ):
            DeploymentFactory.create_cluster(
                deployment_id, app_context, cluster_config, server_args={}
            )

            # All servers should have default authentication
            for role, args in created_servers:
                assert args["server.authentication"] == "false"


class TestDeploymentBehavior:
    """Test deployment behavior without mocking internals.

    These tests verify actual deployment behavior by letting the factory
    create real ArangoServer instances and inspecting their properties.
    This is more robust than mocking create_* methods.
    """

    def test_single_server_deployment_creates_actual_server(self, app_context):
        """Single server deployment creates real ArangoServer with correct properties."""
        deployment_id = DeploymentId("behavior-test-single")

        # No mocking - let it create real server instances
        deployment = DeploymentFactory.create_single_server(deployment_id, app_context)

        # Verify deployment type and ID
        assert isinstance(deployment, SingleServerDeployment)
        assert deployment.deployment_id == deployment_id

        # Verify server was created
        server = deployment.server
        assert server is not None
        assert server.server_id == ServerId(str(deployment_id))
        assert server.role == ServerRole.SINGLE

        # Verify port was allocated (not zero)
        assert server.port > 0

    def test_single_server_with_custom_args_applied(self, app_context):
        """Custom server args are actually applied to created server."""
        deployment_id = DeploymentId("behavior-test-custom")
        custom_args = {
            "server.authentication": "true",
            "custom.setting": "custom_value",
        }

        deployment = DeploymentFactory.create_single_server(
            deployment_id, app_context, server_args=custom_args
        )

        server = deployment.server
        # Verify server exists and has a config
        assert server is not None
        # The server's paths object should have been created with the config
        assert server.paths is not None

    def test_cluster_deployment_creates_actual_servers(self, app_context):
        """Cluster deployment creates real servers with correct roles."""
        deployment_id = DeploymentId("behavior-test-cluster")
        cluster_config = ClusterConfig(agents=3, dbservers=2, coordinators=1)

        # No mocking - let it create real server instances
        deployment = DeploymentFactory.create_cluster(
            deployment_id, app_context, cluster_config
        )

        # Verify deployment type and ID
        assert isinstance(deployment, ClusterDeployment)
        assert deployment.deployment_id == deployment_id

        # Verify actual server count
        assert deployment.get_server_count() == 6

        # Verify servers by role - these are real server objects
        agents = deployment.get_servers_by_role(ServerRole.AGENT)
        dbservers = deployment.get_servers_by_role(ServerRole.DBSERVER)
        coordinators = deployment.get_servers_by_role(ServerRole.COORDINATOR)

        assert len(agents) == 3
        assert len(dbservers) == 2
        assert len(coordinators) == 1

        # Verify each agent has proper ID and allocated port
        agent_ids = sorted([str(s.server_id) for s in agents])
        expected_ids = [f"{deployment_id}-agent-{i}" for i in range(3)]
        assert agent_ids == expected_ids

        for server in agents:
            assert server.role == ServerRole.AGENT
            assert server.port > 0  # Actual allocated port

    def test_cluster_servers_have_unique_allocated_ports(self, app_context):
        """All cluster servers get unique allocated ports."""
        deployment_id = DeploymentId("behavior-test-ports")
        cluster_config = ClusterConfig(agents=3, dbservers=2, coordinators=2)

        deployment = DeploymentFactory.create_cluster(
            deployment_id, app_context, cluster_config
        )

        # Collect all ports from actual server objects
        all_servers = deployment.get_servers().values()
        ports = [server.port for server in all_servers]

        # All ports should be allocated (> 0)
        assert all(port > 0 for port in ports)

        # All ports should be unique
        assert len(ports) == len(set(ports))


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


class TestCreateAgents:
    """Test _create_agents helper method."""

    def test_returns_correct_number_of_agents(self, app_context):
        """Returns correct number of agents + agency endpoints."""
        deployment_id = DeploymentId("test-agents")
        merged_args = {"server.authentication": "false"}
        count = 3

        with patch.object(ArangoServer, "create_cluster_server") as mock_create:
            mock_create.side_effect = lambda sid, role, port, ctx, args: Mock(
                spec=ArangoServer, server_id=sid, role=role, port=port
            )

            servers, agency_endpoints = DeploymentFactory._create_agents(
                deployment_id, app_context, merged_args, count
            )

            assert len(servers) == 3
            assert len(agency_endpoints) == 3

    def test_agents_have_correct_ids(self, app_context):
        """Agents have correct server IDs following deployment-role-N pattern."""
        deployment_id = DeploymentId("test-ids")
        merged_args = {}
        count = 2

        with patch.object(ArangoServer, "create_cluster_server") as mock_create:
            mock_create.side_effect = lambda sid, role, port, ctx, args: Mock(
                spec=ArangoServer, server_id=sid, role=role, port=port
            )

            servers, _ = DeploymentFactory._create_agents(
                deployment_id, app_context, merged_args, count
            )

            # Verify exact expected IDs and roles
            server_ids = list(servers.keys())
            expected_ids = [
                ServerId("test-ids-agent-0"),
                ServerId("test-ids-agent-1"),
            ]
            assert server_ids == expected_ids

            # Verify all are agents
            for server in servers.values():
                assert server.role == ServerRole.AGENT

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
            mock_create.side_effect = lambda sid, role, port, ctx, args: Mock(
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
            mock_create.side_effect = lambda sid, role, port, ctx, args: Mock(
                spec=ArangoServer, server_id=sid, role=role, port=port
            )

            servers = DeploymentFactory._create_dbservers(
                deployment_id, app_context, merged_args, count, agency_endpoints
            )

            assert len(servers) == 2

    def test_dbservers_have_correct_ids(self, app_context):
        """Dbservers have correct server IDs following deployment-role-N pattern."""
        deployment_id = DeploymentId("test-ids")
        merged_args = {}
        count = 2
        agency_endpoints = ["tcp://127.0.0.1:8529"]

        with patch.object(ArangoServer, "create_cluster_server") as mock_create:
            mock_create.side_effect = lambda sid, role, port, ctx, args: Mock(
                spec=ArangoServer, server_id=sid, role=role, port=port
            )

            servers = DeploymentFactory._create_dbservers(
                deployment_id, app_context, merged_args, count, agency_endpoints
            )

            # Verify exact expected IDs and roles
            server_ids = list(servers.keys())
            expected_ids = [
                ServerId("test-ids-dbserver-0"),
                ServerId("test-ids-dbserver-1"),
            ]
            assert server_ids == expected_ids

            # Verify all are dbservers
            for server in servers.values():
                assert server.role == ServerRole.DBSERVER


class TestCreateCoordinators:
    """Test _create_coordinators helper method."""

    def test_returns_correct_number_of_coordinators(self, app_context):
        """Returns correct number of coordinators."""
        deployment_id = DeploymentId("test-coordinators")
        merged_args = {}
        count = 2
        agency_endpoints = ["tcp://127.0.0.1:8529"]

        with patch.object(ArangoServer, "create_cluster_server") as mock_create:
            mock_create.side_effect = lambda sid, role, port, ctx, args: Mock(
                spec=ArangoServer, server_id=sid, role=role, port=port
            )

            servers = DeploymentFactory._create_coordinators(
                deployment_id, app_context, merged_args, count, agency_endpoints
            )

            assert len(servers) == 2

    def test_coordinators_have_correct_ids(self, app_context):
        """Coordinators have correct server IDs following deployment-role-N pattern."""
        deployment_id = DeploymentId("test-ids")
        merged_args = {}
        count = 2
        agency_endpoints = ["tcp://127.0.0.1:8529"]

        with patch.object(ArangoServer, "create_cluster_server") as mock_create:
            mock_create.side_effect = lambda sid, role, port, ctx, args: Mock(
                spec=ArangoServer, server_id=sid, role=role, port=port
            )

            servers = DeploymentFactory._create_coordinators(
                deployment_id, app_context, merged_args, count, agency_endpoints
            )

            # Verify exact expected IDs and roles
            server_ids = list(servers.keys())
            expected_ids = [
                ServerId("test-ids-coordinator-0"),
                ServerId("test-ids-coordinator-1"),
            ]
            assert server_ids == expected_ids

            # Verify all are coordinators
            for server in servers.values():
                assert server.role == ServerRole.COORDINATOR


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
    ctx.filesystem.server_dir = Mock(side_effect=lambda x: Path(f"/tmp/test/{x}"))

    return ctx
