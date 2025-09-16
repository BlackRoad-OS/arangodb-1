"""Unit tests for StandardDeploymentPlanner."""

import pytest
from pathlib import Path
from unittest.mock import Mock

from armadillo.core.types import DeploymentMode, ServerRole, ClusterConfig
from armadillo.instances.deployment_planner import StandardDeploymentPlanner
from armadillo.instances.manager import DeploymentPlan


class TestStandardDeploymentPlanner:
    """Test deployment planning functionality."""

    def setup_method(self):
        """Set up test environment."""
        # Create mock port allocator
        self.mock_port_allocator = Mock()
        self.mock_port_allocator.allocate_port.side_effect = lambda: self._get_next_port()
        self._port_counter = 8529

        # Create mock logger
        self.mock_logger = Mock()

        self.planner = StandardDeploymentPlanner(
            port_allocator=self.mock_port_allocator,
            logger=self.mock_logger
        )

    def _get_next_port(self) -> int:
        """Get next port for testing."""
        port = self._port_counter
        self._port_counter += 1
        return port

    def test_create_single_server_deployment(self):
        """Test creating single server deployment plan."""
        plan = self.planner.create_deployment_plan(
            deployment_id="test_single",
            mode=DeploymentMode.SINGLE_SERVER
        )

        assert plan.deployment_mode == DeploymentMode.SINGLE_SERVER
        assert len(plan.servers) == 1
        assert len(plan.coordination_endpoints) == 1
        assert len(plan.agency_endpoints) == 0

        server = plan.servers[0]
        assert server.role == ServerRole.SINGLE
        assert server.port == 8529
        # Check that data_dir contains the expected path structure
        assert str(server.data_dir).endswith("test_single/single/data")
        assert str(server.log_file).endswith("test_single/single/arangod.log")

        # Check coordination endpoint
        assert plan.coordination_endpoints[0] == "http://127.0.0.1:8529"

        # Verify logger was called
        self.mock_logger.info.assert_called_once()
        assert "Created deployment plan: single_server with 1 servers" in str(self.mock_logger.info.call_args)

    def test_create_cluster_deployment_default_config(self):
        """Test creating cluster deployment with default configuration."""
        plan = self.planner.create_deployment_plan(
            deployment_id="test_cluster",
            mode=DeploymentMode.CLUSTER
        )

        assert plan.deployment_mode == DeploymentMode.CLUSTER
        
        # Default cluster config: 3 agents, 3 dbservers, 1 coordinator
        total_servers = 3 + 3 + 1  # agents + dbservers + coordinators
        assert len(plan.servers) == total_servers
        assert len(plan.get_agents()) == 3
        assert len(plan.get_dbservers()) == 3
        assert len(plan.get_coordinators()) == 1
        assert len(plan.coordination_endpoints) == 1
        assert len(plan.agency_endpoints) == 3

    def test_create_cluster_deployment_custom_config(self):
        """Test creating cluster deployment with custom configuration."""
        custom_config = ClusterConfig(
            agents=1,
            dbservers=2,
            coordinators=2,
            replication_factor=1
        )

        plan = self.planner.create_deployment_plan(
            deployment_id="test_custom_cluster",
            mode=DeploymentMode.CLUSTER,
            cluster_config=custom_config
        )

        assert len(plan.get_agents()) == 1
        assert len(plan.get_dbservers()) == 2
        assert len(plan.get_coordinators()) == 2
        assert len(plan.coordination_endpoints) == 2
        assert len(plan.agency_endpoints) == 1

    def test_agent_configuration(self):
        """Test agent server configuration details."""
        plan = self.planner.create_deployment_plan(
            deployment_id="test_agents",
            mode=DeploymentMode.CLUSTER,
            cluster_config=ClusterConfig(agents=2, dbservers=1, coordinators=1)
        )

        agents = plan.get_agents()
        assert len(agents) == 2

        for i, agent in enumerate(agents):
            assert agent.role == ServerRole.AGENT
            assert agent.port == 8529 + i
            assert str(agent.data_dir).endswith(f"test_agents/agent_{i}/data")
            assert str(agent.log_file).endswith(f"test_agents/agent_{i}/arangod.log")

            # Check agent-specific args
            assert agent.args["agency.activate"] == "true"
            assert agent.args["agency.size"] == "2"
            assert agent.args["agency.supervision"] == "true"
            assert agent.args["server.authentication"] == "false"
            assert agent.args["agency.my-address"] == f"tcp://127.0.0.1:{8529 + i}"
            assert "agency.endpoint" in agent.args
            assert "tcp://127.0.0.1:8529" in agent.args["agency.endpoint"]
            assert "tcp://127.0.0.1:8530" in agent.args["agency.endpoint"]

    def test_dbserver_configuration(self):
        """Test database server configuration details."""
        plan = self.planner.create_deployment_plan(
            deployment_id="test_dbservers",
            mode=DeploymentMode.CLUSTER,
            cluster_config=ClusterConfig(agents=1, dbservers=2, coordinators=1)
        )

        dbservers = plan.get_dbservers()
        assert len(dbservers) == 2

        # Ports: agent=8529, dbservers=8530,8531, coordinator=8532
        for i, dbserver in enumerate(dbservers):
            expected_port = 8530 + i
            assert dbserver.role == ServerRole.DBSERVER
            assert dbserver.port == expected_port
            assert str(dbserver.data_dir).endswith(f"test_dbservers/dbserver_{i}/data")
            assert str(dbserver.log_file).endswith(f"test_dbservers/dbserver_{i}/arangod.log")

            # Check dbserver-specific args
            assert dbserver.args["cluster.my-role"] == "PRIMARY"
            assert dbserver.args["cluster.my-address"] == f"tcp://127.0.0.1:{expected_port}"
            assert dbserver.args["cluster.agency-endpoint"] == "tcp://127.0.0.1:8529"
            assert dbserver.args["server.authentication"] == "false"

    def test_coordinator_configuration(self):
        """Test coordinator configuration details."""
        plan = self.planner.create_deployment_plan(
            deployment_id="test_coordinators",
            mode=DeploymentMode.CLUSTER,
            cluster_config=ClusterConfig(agents=1, dbservers=1, coordinators=2)
        )

        coordinators = plan.get_coordinators()
        assert len(coordinators) == 2

        # Ports: agent=8529, dbserver=8530, coordinators=8531,8532
        for i, coordinator in enumerate(coordinators):
            expected_port = 8531 + i
            assert coordinator.role == ServerRole.COORDINATOR
            assert coordinator.port == expected_port
            assert str(coordinator.data_dir).endswith(f"test_coordinators/coordinator_{i}/data")
            assert str(coordinator.log_file).endswith(f"test_coordinators/coordinator_{i}/arangod.log")

            # Check coordinator-specific args
            assert coordinator.args["cluster.my-role"] == "COORDINATOR"
            assert coordinator.args["cluster.my-address"] == f"tcp://127.0.0.1:{expected_port}"
            assert coordinator.args["cluster.agency-endpoint"] == "tcp://127.0.0.1:8529"
            assert coordinator.args["server.authentication"] == "false"

        # Check coordination endpoints
        expected_endpoints = ["http://127.0.0.1:8531", "http://127.0.0.1:8532"]
        assert plan.coordination_endpoints == expected_endpoints

    def test_agency_endpoint_propagation(self):
        """Test that agency endpoints are properly set on all agents."""
        plan = self.planner.create_deployment_plan(
            deployment_id="test_agency",
            mode=DeploymentMode.CLUSTER,
            cluster_config=ClusterConfig(agents=3, dbservers=1, coordinators=1)
        )

        agents = plan.get_agents()
        expected_agency_endpoints = [
            "tcp://127.0.0.1:8529",
            "tcp://127.0.0.1:8530", 
            "tcp://127.0.0.1:8531"
        ]

        # All agents should have the same agency endpoints
        for agent in agents:
            agency_endpoint_str = agent.args["agency.endpoint"]
            for endpoint in expected_agency_endpoints:
                assert endpoint in agency_endpoint_str

    def test_port_allocation_calls(self):
        """Test that port allocator is called for each server."""
        self.planner.create_deployment_plan(
            deployment_id="test_ports",
            mode=DeploymentMode.CLUSTER,
            cluster_config=ClusterConfig(agents=2, dbservers=2, coordinators=1)
        )

        # Should allocate ports for: 2 agents + 2 dbservers + 1 coordinator = 5 calls
        assert self.mock_port_allocator.allocate_port.call_count == 5

    def test_unsupported_deployment_mode(self):
        """Test error handling for unsupported deployment modes."""
        with pytest.raises(ValueError, match="Unsupported deployment mode"):
            self.planner.create_deployment_plan(
                deployment_id="test_error",
                mode="INVALID_MODE"  # This should cause a ValueError
            )

    def test_deployment_planner_protocol_compliance(self):
        """Test that StandardDeploymentPlanner implements DeploymentPlanner protocol."""
        # This test verifies that the class implements the expected interface
        assert hasattr(self.planner, 'create_deployment_plan')
        assert callable(self.planner.create_deployment_plan)

    def test_plan_single_server_directory_structure(self):
        """Test single server directory structure."""
        plan = self.planner.create_deployment_plan(
            deployment_id="dir_test",
            mode=DeploymentMode.SINGLE_SERVER
        )

        server = plan.servers[0]
        assert str(server.data_dir).endswith("dir_test/single/data")
        assert str(server.log_file).endswith("dir_test/single/arangod.log")

    def test_cluster_directory_structure(self):
        """Test cluster directory structure."""
        plan = self.planner.create_deployment_plan(
            deployment_id="cluster_dir_test",
            mode=DeploymentMode.CLUSTER,
            cluster_config=ClusterConfig(agents=1, dbservers=1, coordinators=1)
        )

        # Check agent directory
        agent = plan.get_agents()[0]
        assert str(agent.data_dir).endswith("cluster_dir_test/agent_0/data")
        assert str(agent.log_file).endswith("cluster_dir_test/agent_0/arangod.log")

        # Check dbserver directory
        dbserver = plan.get_dbservers()[0]
        assert str(dbserver.data_dir).endswith("cluster_dir_test/dbserver_0/data")
        assert str(dbserver.log_file).endswith("cluster_dir_test/dbserver_0/arangod.log")

        # Check coordinator directory
        coordinator = plan.get_coordinators()[0]
        assert str(coordinator.data_dir).endswith("cluster_dir_test/coordinator_0/data")
        assert str(coordinator.log_file).endswith("cluster_dir_test/coordinator_0/arangod.log")
