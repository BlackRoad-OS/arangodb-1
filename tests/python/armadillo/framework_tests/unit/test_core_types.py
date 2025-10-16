"""Tests for core types and data structures."""

import pytest
from pathlib import Path

from armadillo.core.types import (
    DeploymentMode,
    ServerRole,
    ExecutionOutcome,
    ServerConfig,
    ClusterConfig,
    TimeoutConfig,
    ArmadilloConfig,
    ExecutionResult,
    SuiteExecutionResults,
    HealthStatus,
    ServerStats,
    ProcessStats,
)


class TestEnums:
    """Test enum types."""

    def test_deployment_mode_values(self):
        """Test DeploymentMode enum values."""
        assert DeploymentMode.SINGLE_SERVER.value == "single_server"
        assert DeploymentMode.CLUSTER.value == "cluster"

    def test_server_role_values(self):
        """Test ServerRole enum values."""
        assert ServerRole.SINGLE.value == "single"
        assert ServerRole.AGENT.value == "agent"
        assert ServerRole.DBSERVER.value == "dbserver"
        assert ServerRole.COORDINATOR.value == "coordinator"

    def test_test_outcome_values(self):
        """Test ExecutionOutcome enum values."""
        assert ExecutionOutcome.PASSED.value == "passed"
        assert ExecutionOutcome.FAILED.value == "failed"
        assert ExecutionOutcome.SKIPPED.value == "skipped"
        assert ExecutionOutcome.ERROR.value == "error"
        assert ExecutionOutcome.TIMEOUT.value == "timeout"
        assert ExecutionOutcome.CRASHED.value == "crashed"


class TestServerConfig:
    """Test ServerConfig dataclass."""

    def test_server_config_creation(self):
        """Test ServerConfig creation with required fields."""
        config = ServerConfig(
            role=ServerRole.SINGLE,
            port=8529,
            data_dir=Path("/tmp/data"),
            log_file=Path("/tmp/log.txt"),
        )

        assert config.role == ServerRole.SINGLE
        assert config.port == 8529
        assert config.data_dir == Path("/tmp/data")
        assert config.log_file == Path("/tmp/log.txt")
        assert config.args == {}
        assert config.memory_limit_mb is None
        assert config.startup_timeout == 30.0

    def test_server_config_with_optional_fields(self):
        """Test ServerConfig with optional fields."""
        config = ServerConfig(
            role=ServerRole.COORDINATOR,
            port=8530,
            data_dir=Path("/tmp/data"),
            log_file=Path("/tmp/log.txt"),
            args={"server.threads": "4"},
            memory_limit_mb=1024,
            startup_timeout=60.0,
        )

        assert config.args == {"server.threads": "4"}
        assert config.memory_limit_mb == 1024
        assert config.startup_timeout == 60.0


class TestClusterConfig:
    """Test ClusterConfig dataclass."""

    def test_cluster_config_defaults(self):
        """Test ClusterConfig default values."""
        config = ClusterConfig()

        assert config.agents == 3
        assert config.dbservers == 3
        assert config.coordinators == 1
        assert config.replication_factor == 2

    def test_cluster_config_custom(self):
        """Test ClusterConfig with custom values."""
        config = ClusterConfig(
            agents=5, dbservers=4, coordinators=2, replication_factor=3
        )

        assert config.agents == 5
        assert config.dbservers == 4
        assert config.coordinators == 2
        assert config.replication_factor == 3


class TestTimeoutConfig:
    """Test TimeoutConfig dataclass."""

    def test_timeout_config_defaults(self):
        """Test TimeoutConfig default values."""
        config = TimeoutConfig()

        # Health check timeouts
        assert config.health_check_default == 5.0
        assert config.health_check_quick == 2.0
        assert config.health_check_extended == 10.0

        # Server lifecycle timeouts
        assert config.server_startup == 30.0
        assert config.server_shutdown == 30.0
        assert config.server_shutdown_agent == 90.0

        # Deployment timeouts
        assert config.deployment_single == 60.0
        assert config.deployment_cluster == 300.0

        # Process management timeouts
        assert config.process_graceful_stop == 3.0
        assert config.process_force_kill == 2.0
        assert config.emergency_cleanup == 15.0


class TestArmadilloConfig:
    """Test main ArmadilloConfig dataclass."""

    def test_armadillo_config_creation(self):
        """Test ArmadilloConfig creation."""
        config = ArmadilloConfig(deployment_mode=DeploymentMode.SINGLE_SERVER)

        assert config.deployment_mode == DeploymentMode.SINGLE_SERVER
        assert isinstance(config.cluster, ClusterConfig)
        assert isinstance(config.timeouts, TimeoutConfig)
        assert config.test_timeout == 900.0
        assert config.result_formats == ["junit", "json"]
        # temp_dir is now set to default by the validator
        assert config.temp_dir == Path("/tmp/armadillo")
        assert config.keep_instances_on_failure is False
        assert config.bin_dir is None
        assert config.work_dir is None
        assert config.verbose == 0


class TestExecutionResult:
    """Test ExecutionResult dataclass."""

    def test_test_result_creation(self):
        """Test ExecutionResult creation."""
        result = ExecutionResult(
            name="test_example", outcome=ExecutionOutcome.PASSED, duration=1.5
        )

        assert result.name == "test_example"
        assert result.outcome == ExecutionOutcome.PASSED
        assert result.duration == 1.5
        assert result.setup_duration == 0.0
        assert result.teardown_duration == 0.0
        assert result.error_message is None
        assert result.failure_message is None
        assert result.crash_info is None

    def test_test_result_with_failure(self):
        """Test ExecutionResult with failure information."""
        result = ExecutionResult(
            name="test_failed",
            outcome=ExecutionOutcome.FAILED,
            duration=2.0,
            failure_message="Assertion failed",
            setup_duration=0.1,
            teardown_duration=0.05,
        )

        assert result.outcome == ExecutionOutcome.FAILED
        assert result.failure_message == "Assertion failed"
        assert result.setup_duration == 0.1
        assert result.teardown_duration == 0.05


class TestSuiteExecutionResults:
    """Test SuiteExecutionResults dataclass."""

    def test_test_suite_results_creation(self):
        """Test SuiteExecutionResults creation."""
        test1 = ExecutionResult(
            name="test1", outcome=ExecutionOutcome.PASSED, duration=1.0
        )
        test2 = ExecutionResult(
            name="test2", outcome=ExecutionOutcome.FAILED, duration=2.0
        )

        results = SuiteExecutionResults(
            tests=[test1, test2],
            total_duration=10.5,
            summary={"passed": 1, "failed": 1},
            metadata={"framework": "armadillo"},
        )

        assert len(results.tests) == 2
        assert results.total_duration == 10.5
        assert results.summary == {"passed": 1, "failed": 1}
        assert results.metadata == {"framework": "armadillo"}


class TestHealthStatus:
    """Test HealthStatus dataclass."""

    def test_healthy_status(self):
        """Test healthy status creation."""
        status = HealthStatus(is_healthy=True, response_time=0.5)

        assert status.is_healthy is True
        assert status.response_time == 0.5
        assert status.error_message is None
        assert status.details == {}

    def test_unhealthy_status(self):
        """Test unhealthy status with error."""
        status = HealthStatus(
            is_healthy=False,
            response_time=5.0,
            error_message="Connection timeout",
            details={"status_code": 500},
        )

        assert status.is_healthy is False
        assert status.response_time == 5.0
        assert status.error_message == "Connection timeout"
        assert status.details == {"status_code": 500}


class TestServerStats:
    """Test ServerStats dataclass."""

    def test_server_stats_creation(self):
        """Test ServerStats creation."""
        stats = ServerStats(
            process_id=12345,
            memory_usage=1024 * 1024,
            cpu_percent=25.5,
            connection_count=10,
            uptime=3600.0,
            additional_metrics={"cache_hit_rate": 0.95},
        )

        assert stats.process_id == 12345
        assert stats.memory_usage == 1024 * 1024
        assert stats.cpu_percent == 25.5
        assert stats.connection_count == 10
        assert stats.uptime == 3600.0
        assert stats.additional_metrics["cache_hit_rate"] == 0.95


class TestProcessStats:
    """Test ProcessStats dataclass."""

    def test_process_stats_creation(self):
        """Test ProcessStats creation."""
        stats = ProcessStats(
            pid=12345,
            memory_rss=1024 * 1024,
            memory_vms=2048 * 1024,
            cpu_percent=15.0,
            num_threads=8,
            status="running",
        )

        assert stats.pid == 12345
        assert stats.memory_rss == 1024 * 1024
        assert stats.memory_vms == 2048 * 1024
        assert stats.cpu_percent == 15.0
        assert stats.num_threads == 8
        assert stats.status == "running"
