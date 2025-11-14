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


class TestServerConfig:
    """Test ServerConfig dataclass."""

    def test_server_config_with_optional_fields(self) -> None:
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

    def test_cluster_config_custom(self) -> None:
        """Test ClusterConfig with custom values."""
        config = ClusterConfig(
            agents=5, dbservers=4, coordinators=2, replication_factor=3
        )

        assert config.agents == 5
        assert config.dbservers == 4
        assert config.coordinators == 2
        assert config.replication_factor == 3


class TestExecutionResult:
    """Test ExecutionResult dataclass."""

    def test_test_result_with_failure(self) -> None:
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


class TestHealthStatus:
    """Test HealthStatus dataclass."""

    def test_healthy_status(self) -> None:
        """Test healthy status creation."""
        status = HealthStatus(is_healthy=True, response_time=0.5)

        assert status.is_healthy is True
        assert status.response_time == 0.5
        assert status.error_message is None
        assert status.details == {}

    def test_unhealthy_status(self) -> None:
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


