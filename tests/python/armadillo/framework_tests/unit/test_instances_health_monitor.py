"""Unit tests for HealthMonitor."""

import pytest
from unittest.mock import Mock, MagicMock, patch
from armadillo.instances.health_monitor import HealthMonitor
from armadillo.core.types import HealthStatus, ServerRole, ServerStats
from armadillo.core.errors import HealthCheckError


class TestHealthMonitor:
    """Test HealthMonitor basic functionality."""

    def test_init(self):
        """Test HealthMonitor initialization."""
        mock_logger = Mock()
        monitor = HealthMonitor(mock_logger)

        assert monitor._logger == mock_logger

    def test_check_server_health_success(self):
        """Test checking healthy server."""
        mock_logger = Mock()
        monitor = HealthMonitor(mock_logger)

        mock_server = Mock()
        mock_server.server_id = "server1"
        healthy_status = HealthStatus(is_healthy=True, response_time=0.1)
        mock_server.health_check_sync.return_value = healthy_status

        result = monitor.check_server_health(mock_server, timeout=10.0)

        assert result.is_healthy
        assert result == healthy_status
        mock_server.health_check_sync.assert_called_once_with(timeout=10.0)

    def test_check_server_health_failure(self):
        """Test checking unhealthy server."""
        mock_logger = Mock()
        monitor = HealthMonitor(mock_logger)

        mock_server = Mock()
        mock_server.server_id = "server1"
        mock_server.health_check_sync.side_effect = Exception("Connection failed")

        result = monitor.check_server_health(mock_server, timeout=10.0)

        assert not result.is_healthy
        assert "Connection failed" in result.error_message

    def test_check_deployment_health_all_healthy(self):
        """Test checking deployment with all healthy servers."""
        mock_logger = Mock()
        monitor = HealthMonitor(mock_logger)

        server1 = Mock()
        server1.server_id = "server1"
        server1.health_check_sync.return_value = HealthStatus(
            is_healthy=True, response_time=0.1
        )

        server2 = Mock()
        server2.server_id = "server2"
        server2.health_check_sync.return_value = HealthStatus(
            is_healthy=True, response_time=0.1
        )

        servers = {"server1": server1, "server2": server2}

        result = monitor.check_deployment_health(servers, timeout=30.0)

        assert result.is_healthy
        assert result.error_message is None

    def test_check_deployment_health_some_unhealthy(self):
        """Test checking deployment with some unhealthy servers."""
        mock_logger = Mock()
        monitor = HealthMonitor(mock_logger)

        server1 = Mock()
        server1.server_id = "server1"
        server1.health_check_sync.return_value = HealthStatus(
            is_healthy=True, response_time=0.1
        )

        server2 = Mock()
        server2.server_id = "server2"
        server2.health_check_sync.return_value = HealthStatus(
            is_healthy=False, response_time=0.2, error_message="Not responding"
        )

        servers = {"server1": server1, "server2": server2}

        result = monitor.check_deployment_health(servers, timeout=30.0)

        assert not result.is_healthy
        assert "server2" in result.error_message
        assert "1/2 servers unhealthy" in result.error_message

    def test_check_deployment_health_empty_servers(self):
        """Test checking deployment with no servers."""
        mock_logger = Mock()
        monitor = HealthMonitor(mock_logger)

        result = monitor.check_deployment_health({}, timeout=30.0)

        assert not result.is_healthy
        assert "No servers" in result.error_message

    def test_collect_server_stats_success(self):
        """Test collecting server statistics."""
        mock_logger = Mock()
        monitor = HealthMonitor(mock_logger)

        mock_server = Mock()
        mock_server.server_id = "server1"
        mock_stats = ServerStats(
            pid=1234,
            memory_usage=1024,
            cpu_percent=10.5,
            connection_count=50,
            uptime=100.0,
        )
        mock_server.get_stats.return_value = mock_stats

        result = monitor.collect_server_stats(mock_server)

        assert result == mock_stats
        mock_server.get_stats.assert_called_once()

    def test_collect_server_stats_failure(self):
        """Test collecting stats from failed server."""
        mock_logger = Mock()
        monitor = HealthMonitor(mock_logger)

        mock_server = Mock()
        mock_server.server_id = "server1"
        mock_server.get_stats.side_effect = Exception("Stats unavailable")

        result = monitor.collect_server_stats(mock_server)

        assert result is None

    def test_collect_deployment_stats(self):
        """Test collecting stats from multiple servers."""
        mock_logger = Mock()
        monitor = HealthMonitor(mock_logger)

        server1 = Mock()
        server1.server_id = "server1"
        stats1 = ServerStats(
            pid=1234,
            memory_usage=1024,
            cpu_percent=10.5,
            connection_count=50,
            uptime=100.0,
        )
        server1.get_stats.return_value = stats1

        server2 = Mock()
        server2.server_id = "server2"
        stats2 = ServerStats(
            pid=1235,
            memory_usage=2048,
            cpu_percent=20.5,
            connection_count=100,
            uptime=200.0,
        )
        server2.get_stats.return_value = stats2

        servers = {"server1": server1, "server2": server2}

        result = monitor.collect_deployment_stats(servers)

        assert len(result) == 2
        assert result["server1"] == stats1
        assert result["server2"] == stats2


class TestHealthMonitorReadiness:
    """Test HealthMonitor readiness checking."""

    @patch("armadillo.instances.health_monitor.requests.get")
    def test_check_coordinator_readiness_success(self, mock_get):
        """Test checking coordinator readiness."""
        mock_logger = Mock()
        monitor = HealthMonitor(mock_logger)

        mock_server = Mock()
        mock_server.server_id = "coord1"
        mock_server.role = ServerRole.COORDINATOR
        mock_server.get_endpoint.return_value = "http://localhost:8529"

        mock_response = Mock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        is_ready, error = monitor.check_server_readiness(mock_server, timeout=10.0)

        assert is_ready
        assert error is None
        # Verify it was called with correct endpoint
        call_args = mock_get.call_args
        assert call_args[0][0] == "http://localhost:8529/_api/version"
        assert call_args[1]["timeout"] == 10.0

    @patch("armadillo.instances.health_monitor.requests.get")
    def test_check_agent_readiness_success(self, mock_get):
        """Test checking agent readiness."""
        mock_logger = Mock()
        monitor = HealthMonitor(mock_logger)

        mock_server = Mock()
        mock_server.server_id = "agent1"
        mock_server.role = ServerRole.AGENT
        mock_server.get_endpoint.return_value = "http://localhost:8531"

        mock_response = Mock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        is_ready, error = monitor.check_server_readiness(mock_server, timeout=10.0)

        assert is_ready
        assert error is None
        # Agents use agency endpoint
        assert "/_api/agency/read" in mock_get.call_args[0][0]

    @patch("armadillo.instances.health_monitor.requests.get")
    def test_check_readiness_failure(self, mock_get):
        """Test readiness check failure."""
        mock_logger = Mock()
        monitor = HealthMonitor(mock_logger)

        mock_server = Mock()
        mock_server.role = ServerRole.COORDINATOR
        mock_server.get_endpoint.return_value = "http://localhost:8529"

        mock_response = Mock()
        mock_response.status_code = 500
        mock_get.return_value = mock_response

        is_ready, error = monitor.check_server_readiness(mock_server, timeout=10.0)

        assert not is_ready
        assert "500" in error

    @patch("armadillo.instances.health_monitor.requests.get")
    def test_check_readiness_service_api_disabled(self, mock_get):
        """Test readiness check when service API is disabled."""
        mock_logger = Mock()
        monitor = HealthMonitor(mock_logger)

        mock_server = Mock()
        mock_server.server_id = "server1"
        mock_server.role = ServerRole.COORDINATOR
        mock_server.get_endpoint.return_value = "http://localhost:8529"

        # First call returns 403 with service API disabled error
        mock_response = Mock()
        mock_response.status_code = 403
        mock_response.json.return_value = {
            "errorNum": 11,
            "errorMessage": "service api is disabled",
        }
        mock_get.return_value = mock_response

        # Mock health check fallback
        mock_server.health_check_sync.return_value = HealthStatus(
            is_healthy=True, response_time=0.1
        )

        is_ready, error = monitor.check_server_readiness(mock_server, timeout=10.0)

        assert is_ready
        assert error is None

    def test_verify_deployment_ready_success(self):
        """Test verifying all servers are ready."""
        mock_logger = Mock()
        monitor = HealthMonitor(mock_logger)

        with patch.object(monitor, "check_server_readiness") as mock_check:
            mock_check.return_value = (True, None)

            server1 = Mock()
            server1.server_id = "server1"
            server2 = Mock()
            server2.server_id = "server2"

            servers = {"server1": server1, "server2": server2}

            # Should not raise
            monitor.verify_deployment_ready(servers, timeout=60.0)

            assert mock_check.call_count == 2

    def test_verify_deployment_ready_failure(self):
        """Test verifying deployment with unready servers."""
        mock_logger = Mock()
        monitor = HealthMonitor(mock_logger)

        with patch.object(monitor, "check_server_readiness") as mock_check:
            mock_check.return_value = (False, "Connection refused")

            server1 = Mock()
            server1.server_id = "server1"

            servers = {"server1": server1}

            with pytest.raises(HealthCheckError, match="not ready"):
                monitor.verify_deployment_ready(servers, timeout=60.0)


class TestHealthMonitorIntegration:
    """Test HealthMonitor integration scenarios."""

    def test_deployment_health_with_mixed_states(self):
        """Test deployment health with servers in various states."""
        mock_logger = Mock()
        monitor = HealthMonitor(mock_logger)

        # Healthy server
        server1 = Mock()
        server1.server_id = "server1"
        server1.health_check_sync.return_value = HealthStatus(
            is_healthy=True, response_time=0.1
        )

        # Unhealthy server
        server2 = Mock()
        server2.server_id = "server2"
        server2.health_check_sync.return_value = HealthStatus(
            is_healthy=False, response_time=0.2, error_message="Database locked"
        )

        # Server that throws exception
        server3 = Mock()
        server3.server_id = "server3"
        server3.health_check_sync.side_effect = Exception("Network timeout")

        servers = {"server1": server1, "server2": server2, "server3": server3}

        result = monitor.check_deployment_health(servers, timeout=30.0)

        assert not result.is_healthy
        assert "2/3 servers unhealthy" in result.error_message
        assert "server2" in result.error_message or "server3" in result.error_message
