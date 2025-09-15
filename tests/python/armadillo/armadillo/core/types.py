"""Core type definitions for the Armadillo framework."""

from enum import Enum
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from pathlib import Path


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


@dataclass
class ServerConfig:
    """Configuration for a single ArangoDB server."""
    role: ServerRole
    port: int
    data_dir: Path
    log_file: Path
    args: Dict[str, str] = field(default_factory=dict)
    memory_limit_mb: Optional[int] = None
    startup_timeout: float = 30.0


@dataclass
class ClusterConfig:
    """Configuration for ArangoDB cluster topology."""
    agents: int = 3
    dbservers: int = 3
    coordinators: int = 1
    replication_factor: int = 2


@dataclass
class MonitoringConfig:
    """Monitoring and debugging configuration."""
    enable_crash_analysis: bool = True
    enable_gdb_debugging: bool = True
    enable_memory_profiling: bool = False
    enable_network_monitoring: bool = True
    health_check_interval: float = 1.0
    process_stats_interval: float = 5.0


@dataclass
class ArmadilloConfig:
    """Main framework configuration."""
    deployment_mode: DeploymentMode
    cluster: ClusterConfig = field(default_factory=ClusterConfig)
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)
    test_timeout: float = 900.0
    result_formats: List[str] = field(default_factory=lambda: ["junit", "json"])
    temp_dir: Optional[Path] = None
    keep_instances_on_failure: bool = False

    # Runtime configuration
    bin_dir: Optional[Path] = None
    work_dir: Optional[Path] = None
    verbose: int = 0


# Result types for test execution
@dataclass
class ExecutionResult:
    """Individual test result."""
    name: str
    outcome: ExecutionOutcome
    duration: float
    setup_duration: float = 0.0
    teardown_duration: float = 0.0
    error_message: Optional[str] = None
    failure_message: Optional[str] = None
    crash_info: Optional[Dict[str, Any]] = None


@dataclass
class SuiteExecutionResults:
    """Results for a complete test suite."""
    tests: List[ExecutionResult]
    total_duration: float
    summary: Dict[str, int] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


# Health and status types
@dataclass
class HealthStatus:
    """Server health status."""
    is_healthy: bool
    response_time: float
    error_message: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ServerStats:
    """Server statistics and metrics."""
    process_id: int
    memory_usage: int
    cpu_percent: float
    connection_count: int
    uptime: float
    additional_metrics: Dict[str, Any] = field(default_factory=dict)


# Process management types
@dataclass
class ProcessStats:
    """Process statistics."""
    pid: int
    memory_rss: int
    memory_vms: int
    cpu_percent: float
    num_threads: int
    status: str

