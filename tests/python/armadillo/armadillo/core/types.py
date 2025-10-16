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


class ArmadilloConfig(BaseModel):
    """Main framework configuration."""

    deployment_mode: DeploymentMode = DeploymentMode.SINGLE_SERVER
    cluster: ClusterConfig = Field(default_factory=ClusterConfig)
    timeouts: TimeoutConfig = Field(default_factory=TimeoutConfig)
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

    @model_validator(mode="after")
    def validate_config(self) -> "ArmadilloConfig":
        """Validate and normalize configuration."""
        # Import here to avoid circular imports
        import inspect  # pylint: disable=import-outside-toplevel
        from .build_detection import detect_build_directory, normalize_build_directory
        from .errors import ConfigurationError, PathError

        # Set default temp directory if not specified
        if self.temp_dir is None:
            self.temp_dir = Path("/tmp/armadillo")

        # Create temp directory
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        # Handle bin_dir: normalize or auto-detect
        if self.bin_dir is not None:
            # User explicitly provided a build directory
            # Normalize it to find the actual bin directory containing arangod
            normalized_bin_dir = normalize_build_directory(self.bin_dir)
            if normalized_bin_dir is None:
                # Directory exists but no arangod found
                raise PathError(
                    f"Could not find arangod binary in build directory: {self.bin_dir}\n"
                    f"Looked in:\n"
                    f"  - {self.bin_dir}/arangod\n"
                    f"  - {self.bin_dir}/bin/arangod\n"
                    f"Please ensure the build directory contains a compiled arangod executable."
                )
            self.bin_dir = normalized_bin_dir
        elif not self._is_unit_test_context():
            # No explicit bin_dir, try auto-detection
            detected_build_dir = detect_build_directory()
            if detected_build_dir:
                self.bin_dir = detected_build_dir

        if self.work_dir and not self.work_dir.exists():
            self.work_dir.mkdir(parents=True, exist_ok=True)

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

    def _is_unit_test_context(self) -> bool:
        """Check if we're running in a unit test context where build detection should be skipped."""
        import inspect

        for frame_info in inspect.stack():
            if (
                "framework_tests/unit" in frame_info.filename
                or "framework_tests\\unit" in frame_info.filename
            ):
                return True
        return False


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
    crash_info: Optional[Dict[str, Any]] = None


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
