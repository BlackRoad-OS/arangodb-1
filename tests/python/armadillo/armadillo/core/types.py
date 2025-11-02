"""Core type definitions for the Armadillo framework."""

from enum import Enum
from typing import Dict, List, Optional, Any
from pathlib import Path

from pydantic import BaseModel, Field, model_validator


class DeploymentMode(Enum):
    """ArangoDB deployment mode."""

    SINGLE_SERVER = "single_server"
    CLUSTER = "cluster"


class ServerRole(Enum):
    """ArangoDB server role."""

    SINGLE = "single"
    AGENT = "agent"
    DBSERVER = "dbserver"
    COORDINATOR = "coordinator"


class ExecutionOutcome(Enum):
    """Test execution outcome."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"
    TIMEOUT = "timeout"
    CRASHED = "crashed"


class CrashInfo(BaseModel):
    """Information about a crashed process."""

    exit_code: int
    timestamp: float
    stderr: Optional[str] = None
    signal: Optional[int] = None


class ServerConfig(BaseModel):
    """Configuration for a single ArangoDB server."""

    role: ServerRole
    port: int
    data_dir: Path
    log_file: Path
    args: Dict[str, str] = Field(default_factory=dict)
    memory_limit_mb: Optional[int] = None
    startup_timeout: float = 30.0


class ClusterConfig(BaseModel):
    """Configuration for ArangoDB cluster topology."""

    agents: int = 3
    dbservers: int = 3
    coordinators: int = 1
    replication_factor: int = 2


class TimeoutConfig(BaseModel):
    """Centralized timeout configuration to eliminate magical constants."""

    # Health check timeouts
    health_check_default: float = 5.0
    health_check_quick: float = 2.0
    health_check_extended: float = 10.0

    # Server lifecycle timeouts
    server_startup: float = 30.0
    server_shutdown: float = 30.0
    server_shutdown_agent: float = 90.0  # Agents need more time

    # Deployment timeouts
    deployment_single: float = 60.0
    deployment_cluster: float = 300.0

    # Process management timeouts
    process_graceful_stop: float = 3.0
    process_force_kill: float = 2.0
    emergency_cleanup: float = 15.0


class InfrastructureConfig(BaseModel):
    """Infrastructure and system-level configuration constants."""

    # Thread pool configuration
    manager_max_workers: int = 10
    orchestrator_max_workers: int = 5

    # Network configuration
    http_timeout_default: float = 30.0
    tcp_connection_limit: int = 20

    # Port management
    default_base_port: int = 8529
    max_port_range: int = 1000

    # Retry and polling intervals
    agency_retry_interval: float = 0.5
    cluster_retry_interval: float = 1.0
    orchestrator_retry_interval: float = 2.0
    coordinator_retry_interval: float = 3.0
    server_shutdown_poll_interval: float = 1.0


class ArmadilloConfig(BaseModel):
    """Main framework configuration."""

    deployment_mode: DeploymentMode = DeploymentMode.SINGLE_SERVER
    cluster: ClusterConfig = Field(default_factory=ClusterConfig)
    timeouts: TimeoutConfig = Field(default_factory=TimeoutConfig)
    infrastructure: InfrastructureConfig = Field(default_factory=InfrastructureConfig)
    test_timeout: float = 900.0
    result_formats: List[str] = Field(default_factory=lambda: ["junit", "json"])
    temp_dir: Optional[Path] = None
    keep_instances_on_failure: bool = False

    # Runtime configuration
    bin_dir: Optional[Path] = None
    work_dir: Optional[Path] = None
    verbose: int = 0

    # Test execution configuration
    log_level: str = "INFO"
    compact_mode: bool = False
    show_server_logs: bool = False

    # Test mode flag - explicit instead of stack inspection
    is_test_mode: bool = False

    @model_validator(mode="after")
    def validate_config(self) -> "ArmadilloConfig":
        """Validate configuration - NO SIDE EFFECTS.

        This method performs ONLY pure validation that the configuration
        is internally consistent. It does NOT:
        - Create directories
        - Detect build directories
        - Perform any I/O operations

        For initialization with side effects, use initialize_config() from
        core.config_initializer after construction.
        """
        from .errors import ConfigurationError

        # Validate cluster configuration
        if self.deployment_mode == DeploymentMode.CLUSTER:
            if self.cluster.agents < 1:  # pylint: disable=no-member
                raise ConfigurationError("Cluster must have at least 1 agent")
            if self.cluster.dbservers < 1:  # pylint: disable=no-member
                raise ConfigurationError("Cluster must have at least 1 dbserver")
            if self.cluster.coordinators < 1:  # pylint: disable=no-member
                raise ConfigurationError("Cluster must have at least 1 coordinator")

        # Validate timeouts
        if self.test_timeout <= 0:
            raise ConfigurationError("Test timeout must be positive")

        return self


# Result types for test execution
class ExecutionResult(BaseModel):
    """Individual test result."""

    name: str
    outcome: ExecutionOutcome
    duration: float
    setup_duration: float = 0.0
    teardown_duration: float = 0.0
    error_message: Optional[str] = None
    failure_message: Optional[str] = None
    crash_info: Optional[CrashInfo] = None


class SuiteExecutionResults(BaseModel):
    """Results for a complete test suite."""

    tests: List[ExecutionResult]
    total_duration: float
    summary: Dict[str, int] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


# Health and status types
class HealthStatus(BaseModel):
    """Server health status."""

    is_healthy: bool
    response_time: float
    error_message: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class ServerStats(BaseModel):
    """Server statistics and metrics."""

    process_id: int
    memory_usage: int
    cpu_percent: float
    connection_count: int
    uptime: float
    additional_metrics: Dict[str, Any] = Field(default_factory=dict)


# Process management types
class ProcessStats(BaseModel):
    """Process statistics."""

    pid: int
    memory_rss: int
    memory_vms: int
    cpu_percent: float
    num_threads: int
    status: str
