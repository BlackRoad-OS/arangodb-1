"""Unit tests for ClusterBootstrapper."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from concurrent.futures import ThreadPoolExecutor
from armadillo.instances.cluster_bootstrapper import ClusterBootstrapper
from armadillo.core.types import ServerRole
from armadillo.core.errors import ServerStartupError, AgencyError, ClusterError


class TestClusterBootstrapper:
    """Test ClusterBootstrapper basic functionality."""

    def test_init(self):
        """Test ClusterBootstrapper initialization."""
        mock_logger = Mock()
        mock_executor = Mock()
        
        bootstrapper = ClusterBootstrapper(mock_logger, mock_executor)
        
        assert bootstrapper._logger == mock_logger
        assert bootstrapper._executor == mock_executor

    def test_get_agents(self):
        """Test getting agent servers from server dict."""
        mock_logger = Mock()
        mock_executor = Mock()
        bootstrapper = ClusterBootstrapper(mock_logger, mock_executor)
        
        agent1 = Mock()
        agent1.role = ServerRole.AGENT
        coord1 = Mock()
        coord1.role = ServerRole.COORDINATOR
        agent2 = Mock()
        agent2.role = ServerRole.AGENT
        
        servers = {
            "agent1": agent1,
            "coord1": coord1,
            "agent2": agent2,
        }
        
        agents = bootstrapper._get_agents(servers)
        
        assert len(agents) == 2
        assert ("agent1", agent1) in agents
        assert ("agent2", agent2) in agents

    @patch("armadillo.instances.cluster_bootstrapper.requests.get")
    def test_check_agent_config_success(self, mock_get):
        """Test checking agent configuration successfully."""
        mock_logger = Mock()
        mock_executor = Mock()
        bootstrapper = ClusterBootstrapper(mock_logger, mock_executor)
        
        mock_server = Mock()
        mock_server.endpoint = "http://localhost:8531"
        
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"leaderId": "agent1", "lastAcked": 123}
        mock_get.return_value = mock_response
        
        config = bootstrapper._check_agent_config("agent1", mock_server)
        
        assert config is not None
        assert config["leaderId"] == "agent1"
        assert config["lastAcked"] == 123

    @patch("armadillo.instances.cluster_bootstrapper.requests.get")
    def test_check_agent_config_not_ready(self, mock_get):
        """Test checking agent that's not ready."""
        mock_logger = Mock()
        mock_executor = Mock()
        bootstrapper = ClusterBootstrapper(mock_logger, mock_executor)
        
        mock_server = Mock()
        mock_server.endpoint = "http://localhost:8531"
        
        mock_response = Mock()
        mock_response.status_code = 503
        mock_get.return_value = mock_response
        
        config = bootstrapper._check_agent_config("agent1", mock_server)
        
        assert config is None

    def test_analyze_agency_status_ready(self):
        """Test analyzing agency status when ready."""
        mock_logger = Mock()
        mock_executor = Mock()
        bootstrapper = ClusterBootstrapper(mock_logger, mock_executor)
        
        agent1 = Mock()
        agent1.endpoint = "http://localhost:8531"
        agent2 = Mock()
        agent2.endpoint = "http://localhost:8532"
        agent3 = Mock()
        agent3.endpoint = "http://localhost:8533"
        
        agents = [
            ("agent1", agent1),
            ("agent2", agent2),
            ("agent3", agent3),
        ]
        
        # Mock all agents having consensus
        with patch.object(bootstrapper, "_check_agent_config") as mock_check:
            mock_check.side_effect = [
                {"leaderId": "agent1", "lastAcked": 123},
                {"leaderId": "agent1", "lastAcked": 124},
                {"leaderId": "agent1", "lastAcked": 125},
            ]
            
            have_leader, have_config, consensus = bootstrapper._analyze_agency_status(agents)
            
            assert have_leader == 3
            assert have_config == 3
            assert consensus is True

    def test_analyze_agency_status_no_consensus(self):
        """Test analyzing agency status with disagreement."""
        mock_logger = Mock()
        mock_executor = Mock()
        bootstrapper = ClusterBootstrapper(mock_logger, mock_executor)
        
        agent1 = Mock()
        agent2 = Mock()
        agents = [("agent1", agent1), ("agent2", agent2)]
        
        # Mock agents disagreeing on leader
        with patch.object(bootstrapper, "_check_agent_config") as mock_check:
            mock_check.side_effect = [
                {"leaderId": "agent1", "lastAcked": 123},
                {"leaderId": "agent2", "lastAcked": 124},  # Different leader!
            ]
            
            have_leader, have_config, consensus = bootstrapper._analyze_agency_status(agents)
            
            assert consensus is False

    def test_start_servers_by_role(self):
        """Test starting servers by role."""
        mock_logger = Mock()
        mock_executor = Mock()
        
        # Mock executor to return successful futures
        mock_future = Mock()
        mock_future.result.return_value = None
        mock_executor.submit.return_value = mock_future
        
        bootstrapper = ClusterBootstrapper(mock_logger, mock_executor)
        
        agent1 = Mock()
        agent1.role = ServerRole.AGENT
        agent2 = Mock()
        agent2.role = ServerRole.AGENT
        coord1 = Mock()
        coord1.role = ServerRole.COORDINATOR
        
        servers = {
            "agent1": agent1,
            "agent2": agent2,
            "coord1": coord1,
        }
        
        startup_order = []
        
        bootstrapper._start_servers_by_role(
            servers, ServerRole.AGENT, startup_order, timeout=60.0
        )
        
        # Verify agents were started
        assert len(startup_order) == 2
        assert "agent1" in startup_order
        assert "agent2" in startup_order
        
        # Verify executor was called twice
        assert mock_executor.submit.call_count == 2

    def test_start_servers_by_role_failure(self):
        """Test handling server startup failure."""
        mock_logger = Mock()
        mock_executor = Mock()
        
        # Mock executor to return failing future
        mock_future = Mock()
        mock_future.result.side_effect = Exception("Startup failed")
        mock_executor.submit.return_value = mock_future
        
        bootstrapper = ClusterBootstrapper(mock_logger, mock_executor)
        
        agent1 = Mock()
        agent1.role = ServerRole.AGENT
        
        servers = {"agent1": agent1}
        startup_order = []
        
        with pytest.raises(ServerStartupError, match="Startup failed"):
            bootstrapper._start_servers_by_role(
                servers, ServerRole.AGENT, startup_order, timeout=60.0
            )

    def test_wait_for_agency_ready_no_agents(self):
        """Test waiting for agency with no agents."""
        mock_logger = Mock()
        mock_executor = Mock()
        bootstrapper = ClusterBootstrapper(mock_logger, mock_executor)
        
        servers = {}
        
        with pytest.raises(AgencyError, match="No agent servers"):
            bootstrapper.wait_for_agency_ready(servers, timeout=5.0)

    def test_wait_for_agency_ready_success(self):
        """Test successful agency readiness."""
        mock_logger = Mock()
        mock_executor = Mock()
        bootstrapper = ClusterBootstrapper(mock_logger, mock_executor)
        
        agent1 = Mock()
        agent1.role = ServerRole.AGENT
        agent2 = Mock()
        agent2.role = ServerRole.AGENT
        agent3 = Mock()
        agent3.role = ServerRole.AGENT
        
        servers = {
            "agent1": agent1,
            "agent2": agent2,
            "agent3": agent3,
        }
        
        # Mock agency becoming ready immediately
        with patch.object(bootstrapper, "_analyze_agency_status") as mock_analyze:
            mock_analyze.return_value = (3, 3, True)  # All agents ready
            
            # Should not raise
            bootstrapper.wait_for_agency_ready(servers, timeout=5.0)

    def test_wait_for_cluster_ready_no_coordinators(self):
        """Test waiting for cluster with no coordinators."""
        mock_logger = Mock()
        mock_executor = Mock()
        bootstrapper = ClusterBootstrapper(mock_logger, mock_executor)
        
        servers = {}
        
        with pytest.raises(ClusterError, match="No coordinator"):
            bootstrapper.wait_for_cluster_ready(servers, timeout=5.0)

    @patch("armadillo.instances.cluster_bootstrapper.requests.get")
    def test_wait_for_cluster_ready_success(self, mock_get):
        """Test successful cluster readiness."""
        mock_logger = Mock()
        mock_executor = Mock()
        bootstrapper = ClusterBootstrapper(mock_logger, mock_executor)
        
        coord1 = Mock()
        coord1.role = ServerRole.COORDINATOR
        coord1.endpoint = "http://localhost:8529"
        
        servers = {"coord1": coord1}
        
        # Mock successful health check
        mock_response = Mock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response
        
        # Should not raise
        bootstrapper.wait_for_cluster_ready(servers, timeout=5.0)


class TestClusterBootstrapperIntegration:
    """Test ClusterBootstrapper integration scenarios."""

    def test_bootstrap_cluster_sequence(self):
        """Test complete bootstrap sequence."""
        mock_logger = Mock()
        mock_executor = Mock()
        
        # Mock successful futures
        mock_future = Mock()
        mock_future.result.return_value = None
        mock_executor.submit.return_value = mock_future
        
        bootstrapper = ClusterBootstrapper(mock_logger, mock_executor)
        
        # Create mock servers
        agent1 = Mock()
        agent1.role = ServerRole.AGENT
        dbserver1 = Mock()
        dbserver1.role = ServerRole.DBSERVER
        coord1 = Mock()
        coord1.role = ServerRole.COORDINATOR
        coord1.endpoint = "http://localhost:8529"
        
        servers = {
            "agent1": agent1,
            "db1": dbserver1,
            "coord1": coord1,
        }
        
        startup_order = []
        
        # Mock agency and cluster ready checks
        with patch.object(bootstrapper, "wait_for_agency_ready"):
            with patch.object(bootstrapper, "wait_for_cluster_ready"):
                bootstrapper.bootstrap_cluster(servers, startup_order, timeout=300.0)
        
        # Verify all servers were started in order
        assert len(startup_order) == 3
        # Agent should be first
        assert startup_order[0] == "agent1"
        # DB and coord order may vary due to parallel start
        assert "db1" in startup_order
        assert "coord1" in startup_order

