# Armadillo: Modern ArangoDB Testing Framework

## Overview

**Armadillo** is a modern Python testing framework built on pytest that replaces ArangoDB's legacy JavaScript testing framework. It provides the same sophisticated functionality including distributed system orchestration, advanced crash analysis, comprehensive monitoring, and result processing while following Python best practices and leveraging pytest's powerful plugin ecosystem.

**Key Design Principles:**
- **Modern Python**: Type hints, async/await, dataclasses, and clean APIs
- **Pytest Integration**: Native pytest plugin with fixtures, markers, and hooks
- **Pythonic Naming**: snake_case, descriptive names, and clear interfaces
- **Clean Architecture**: Modular design with clear separation of concerns
- **Production Ready**: Comprehensive logging, error handling, and monitoring

**Removed Legacy Features:**
- Windows support (Linux-only)
- Valgrind integration (replaced with modern profiling)
- Legacy command-line compatibility (new clean CLI)

## Architecture Overview

```
armadillo/
├── core/           # Core framework and configuration
├── instances/      # ArangoDB instance management
├── monitoring/     # Crash analysis, profiling, network monitoring
├── results/        # Result processing and export
├── tools/          # Client tool wrappers (dump, import, etc.)
├── pytest_plugin/ # Pytest integration
├── cli/            # Command-line interface
└── utils/          # Utilities and helpers
```

## Core Types and Configuration

**Modern Type System:**
```python
from enum import Enum
from typing import Dict, List, Optional, Protocol, runtime_checkable
from dataclasses import dataclass, field
from pathlib import Path
import asyncio

class DeploymentMode(Enum):
    SINGLE_SERVER = "single_server"
    CLUSTER = "cluster"

class ServerRole(Enum):
    SINGLE = "single"
    AGENT = "agent"
    DBSERVER = "dbserver"
    COORDINATOR = "coordinator"

class TestOutcome(Enum):
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
```

## File Structure

### Core Framework
```
armadillo/
├── __init__.py                    # Package exports
├── core/
│   ├── __init__.py
│   ├── framework.py               # Main ArmadilloFramework class
│   ├── config.py                  # Configuration management
│   ├── types.py                   # Type definitions
│   ├── exceptions.py              # Custom exceptions
│   └── context.py                 # Test execution context
```

### Instance Management
```
├── instances/
│   ├── __init__.py
│   ├── manager.py                 # InstanceManager - lifecycle coordination
│   ├── server.py                  # ArangoServer - individual server wrapper
│   ├── cluster.py                 # ClusterOrchestrator - cluster coordination
│   ├── agency.py                  # AgencyManager - consensus management
│   ├── health.py                  # HealthMonitor - server health checks
│   └── topology.py                # TopologyBuilder - deployment setup
```

### Monitoring and Analysis
```
├── monitoring/
│   ├── __init__.py
│   ├── crash_analyzer.py          # CrashAnalyzer - GDB integration
│   ├── process_monitor.py         # ProcessMonitor - resource tracking
│   ├── network_monitor.py         # NetworkMonitor - network stats/capture
│   ├── memory_profiler.py         # MemoryProfiler - memory analysis
│   ├── sanitizer_handler.py       # SanitizerHandler - ASAN/TSAN reports
│   └── debug_collector.py         # DebugCollector - comprehensive debugging
```

### Result Processing
```
├── results/
│   ├── __init__.py
│   ├── collector.py               # ResultCollector - test result gathering
│   ├── processor.py               # ResultProcessor - analysis and stats
│   ├── exporters/
│   │   ├── __init__.py
│   │   ├── junit.py               # JUnit XML exporter
│   │   ├── json_exporter.py       # JSON exporter
│   │   ├── yaml_exporter.py       # YAML exporter
│   │   └── html_reporter.py       # HTML report generator
│   └── analysis/
│       ├── __init__.py
│       ├── performance.py         # Performance analysis
│       ├── statistics.py          # Statistical analysis
│       └── trends.py              # Trend analysis
```

### Client Tools Integration
```
├── tools/
│   ├── __init__.py
│   ├── base.py                    # BaseTool - common tool interface
│   ├── shell.py                   # ArangoShell - arangosh wrapper
│   ├── dump.py                    # ArangoDump - backup tool
│   ├── restore.py                 # ArangoRestore - restore tool
│   ├── import_tool.py             # ArangoImport - data import
│   ├── export_tool.py             # ArangoExport - data export
│   ├── benchmark.py               # ArangoBench - benchmarking
│   └── backup.py                  # ArangoBackup - backup management
```

### Pytest Integration
```
├── pytest_plugin/
│   ├── __init__.py
│   ├── plugin.py                  # Main pytest plugin
│   ├── fixtures.py                # Test fixtures (servers, clusters)
│   ├── markers.py                 # Custom pytest markers
│   ├── hooks.py                   # Pytest hook implementations
│   ├── collectors.py              # Custom test collectors
│   └── reports.py                 # Custom reporting hooks
```

### Utilities
```
├── utils/
│   ├── __init__.py
│   ├── ports.py                   # PortManager - port allocation
│   ├── paths.py                   # PathResolver - path management
│   ├── auth.py                    # AuthManager - JWT/authentication
│   ├── process.py                 # ProcessRunner - process execution
│   ├── logging.py                 # LogManager - logging configuration
│   ├── async_utils.py             # Async utilities and helpers
│   └── system.py                  # SystemInfo - system detection
```

### Command Line Interface
```
├── cli/
│   ├── __init__.py
│   ├── main.py                    # Main CLI entry point
│   ├── commands/
│   │   ├── __init__.py
│   │   ├── test.py                # Test execution commands
│   │   ├── cluster.py             # Cluster management commands
│   │   ├── debug.py               # Debugging commands
│   │   └── config.py              # Configuration commands
│   └── formatters.py              # Output formatters
```

## Key Classes and APIs

### Core Framework
```python
class ArmadilloFramework:
    """Main framework orchestrating test execution."""

    def __init__(self, config: ArmadilloConfig):
        self.config = config
        self.instance_manager = InstanceManager(config)
        self.monitoring = MonitoringManager(config.monitoring)
        self.result_collector = ResultCollector()

    async def setup_deployment(self) -> None:
        """Set up the ArangoDB deployment."""

    async def run_test_suite(self, test_path: Path) -> TestResults:
        """Run a complete test suite."""

    async def teardown(self, cleanup: bool = True) -> None:
        """Clean up all resources."""
```

### Instance Management
```python
class InstanceManager:
    """Manages ArangoDB server instances lifecycle."""

    async def create_deployment(self, mode: DeploymentMode) -> Deployment:
        """Create deployment based on configuration."""

    async def start_all_servers(self) -> None:
        """Start all servers with proper dependency ordering."""

    async def stop_all_servers(self, graceful: bool = True) -> None:
        """Stop all servers gracefully or forcefully."""

    async def wait_for_cluster_ready(self, timeout: float = 60.0) -> bool:
        """Wait for cluster to be ready and healthy."""

class ArangoServer:
    """Wrapper for individual ArangoDB server process."""

    async def start(self, wait_ready: bool = True) -> None:
        """Start the server process."""

    async def stop(self, graceful: bool = True, timeout: float = 30.0) -> None:
        """Stop the server process."""

    async def restart(self, wait_ready: bool = True) -> None:
        """Restart the server process."""

    async def health_check(self) -> HealthStatus:
        """Check server health and status."""

    async def get_stats(self) -> ServerStats:
        """Get current server statistics."""
```

### Monitoring
```python
class CrashAnalyzer:
    """Advanced crash analysis with GDB integration."""

    async def analyze_crash(self, server: ArangoServer) -> CrashReport:
        """Perform comprehensive crash analysis."""

    async def generate_core_dump(self, pid: int) -> Path:
        """Generate core dump for analysis."""

    async def run_gdb_analysis(self, core_path: Path, binary: Path) -> GdbReport:
        """Run GDB analysis on core dump."""

class ProcessMonitor:
    """Continuous process monitoring and statistics."""

    async def start_monitoring(self, servers: List[ArangoServer]) -> None:
        """Start monitoring all server processes."""

    async def get_current_stats(self, server: ArangoServer) -> ProcessStats:
        """Get current process statistics."""

    async def detect_performance_issues(self) -> List[PerformanceIssue]:
        """Detect performance anomalies."""
```

### Result Processing
```python
class ResultCollector:
    """Collects and aggregates test results."""

    def add_test_result(self, result: TestResult) -> None:
        """Add a single test result."""

    async def finalize_results(self) -> TestSuiteResults:
        """Finalize and process all results."""

    async def export_results(self, formats: List[str], output_dir: Path) -> None:
        """Export results in specified formats."""
```

## Pytest Integration

### Plugin Architecture
```python
# armadillo/pytest_plugin/plugin.py
class ArmadilloPlugin:
    """Main pytest plugin for Armadillo framework."""

    def pytest_configure(self, config):
        """Configure pytest for Armadillo."""

    def pytest_collection_modifyitems(self, items):
        """Modify collected test items."""

    def pytest_runtest_setup(self, item):
        """Set up test execution environment."""

# Fixtures
@pytest.fixture(scope="session")
async def arango_single_server(request) -> ArangoServer:
    """Provide a single ArangoDB server for testing."""

@pytest.fixture(scope="session")
async def arango_cluster(request) -> ArangoCluster:
    """Provide an ArangoDB cluster for testing."""

# Markers
pytest.mark.arango_single    # Requires single server
pytest.mark.arango_cluster   # Requires cluster
pytest.mark.slow            # Long-running test
pytest.mark.crash_test      # Test involves crashes
pytest.mark.rta_suite("auth") # Specific RTA test suite
```

### Test Discovery and Execution
```python
# Tests follow pytest conventions
# tests/test_collections.py
@pytest.mark.arango_single
async def test_create_collection(arango_single_server):
    """Test collection creation."""

@pytest.mark.arango_cluster
@pytest.mark.slow
async def test_cluster_replication(arango_cluster):
    """Test cluster replication."""

@pytest.mark.crash_test
async def test_coordinator_crash_recovery(arango_cluster):
    """Test coordinator crash and recovery."""
```

## Command Line Interface

### Simplified CLI Design
The CLI focuses on ease of use for everyday development with sensible defaults. Advanced configuration is available but not required.

```bash
# Simple test execution (uses smart defaults)
armadillo tests/collections/
armadillo tests/replication/ --cluster
armadillo tests/recovery/ --crash-analysis

# Common options with good defaults
armadillo tests/ --cluster --dbservers 2 --coordinators 1
armadillo tests/ --single-server --port 8529
armadillo tests/ --timeout 600 --keep-instances-on-failure

# Advanced monitoring (optional)
armadillo tests/ --memory-profiling --network-monitoring
armadillo tests/ --gdb-debugging --output-dir ./test-results

# Output formats (defaults to junit + json)
armadillo tests/ --format junit
armadillo tests/ --format json --format html
```

### Smart Defaults
The framework provides intelligent defaults to minimize configuration:

- **Single Server**: Default for most tests, starts on available port
- **Cluster**: 3 agents, 2 dbservers, 1 coordinator when `--cluster` is used
- **Monitoring**: Basic crash analysis enabled, advanced features opt-in
- **Output**: JUnit XML + JSON reports to `./test-results/`
- **Cleanup**: Automatic cleanup on success, keep instances on failure for debugging
- **Timeout**: 15 minutes default, adjustable per test suite

### CLI-Only Configuration
All configuration is done via command-line arguments - no configuration files needed:

```bash
# Deployment configuration
armadillo tests/ --cluster --agents 3 --dbservers 2 --coordinators 1
armadillo tests/ --single-server --port 8529

# Monitoring options
armadillo tests/ --crash-analysis --memory-profiling --network-monitoring
armadillo tests/ --no-crash-analysis  # Disable default crash analysis

# Output and behavior
armadillo tests/ --timeout 600 --keep-instances-on-failure
armadillo tests/ --output-dir ./my-results --format junit --format json
armadillo tests/ --parallel --max-workers 4

# Test filtering
armadillo tests/ --suite auth --suite collections
armadillo tests/ --exclude slow --exclude flaky
```

## Implementation Phases

### Phase 1: Core Foundation (Weeks 1-2)
**Goal**: Basic server management and test execution capability

1. **Project Setup**
   - Create package structure and `pyproject.toml`
   - Set up development environment (linting, type checking)
   - Basic CLI with `typer` for test execution

2. **Core Infrastructure**
   - Implement type definitions (`types.py`)
   - Create configuration management (`config.py`)
   - Add basic exception handling (`exceptions.py`)

3. **Single Server Support**
   - Implement `ArangoServer` class for single server
   - Add process management utilities
   - Create port allocation system
   - Basic health checking

4. **Basic Test Execution**
   - Simple test discovery and execution
   - Basic result collection
   - JUnit XML output for CI integration

**Deliverables**: Working single-server test execution with basic reporting

### Phase 2: Cluster Support (Weeks 3-4)
**Goal**: Multi-server cluster coordination and pytest integration

1. **Cluster Management**
   - Complete `InstanceManager` with lifecycle management
   - Create `ClusterOrchestrator` for multi-server coordination
   - Implement agency management for consensus
   - Add cluster health verification

2. **Pytest Plugin Foundation**
   - Core pytest plugin implementation
   - Basic fixtures for single server and cluster
   - Custom markers for test categorization
   - Test collection and execution hooks

3. **Authentication**
   - JWT token generation and management
   - Secure communication setup
   - User authentication helpers

4. **CLI Enhancement**
   - Add cluster configuration options
   - Implement smart defaults for deployment modes

**Deliverables**: Full cluster setup/teardown, basic pytest integration, enhanced CLI

### Phase 3: Test Management and Results (Weeks 5-6)
**Goal**: Comprehensive test management and result processing

1. **Advanced Test Management**
   - Test filtering and selection
   - Test suite organization
   - Parallel execution support
   - Background process coordination

2. **Result Processing**
   - Multi-format export (JSON, HTML, YAML)
   - Basic performance analysis
   - Statistical reporting
   - Result aggregation across test runs

3. **Client Tools Integration**
   - Basic client tool wrappers (shell, dump, restore)
   - Background tool execution
   - Tool output integration

4. **Enhanced Pytest Integration**
   - Advanced fixtures with scope management
   - Custom test collectors
   - Reporting hooks integration

**Deliverables**: Complete test management, multi-format results, client tools integration

### Phase 4: Advanced Monitoring (Weeks 7-8)
**Goal**: Crash analysis and advanced debugging capabilities

1. **Crash Analysis**
   - GDB integration for crash analysis
   - Core dump generation and processing
   - Stack trace filtering and analysis
   - Crash report generation

2. **Process Monitoring**
   - Real-time resource monitoring
   - Performance metrics collection
   - Anomaly detection
   - Memory usage tracking

3. **Sanitizer Integration**
   - AddressSanitizer/ThreadSanitizer support
   - Sanitizer report collection and processing
   - Report filtering and analysis

4. **Debug Utilities**
   - Comprehensive debugging helpers
   - Log analysis and correlation
   - Debug data collection

**Deliverables**: Advanced crash analysis, process monitoring, sanitizer integration

### Phase 5: Network Monitoring and Profiling (Weeks 9-10)
**Goal**: Network analysis and advanced profiling capabilities

1. **Network Monitoring**
   - Network statistics collection
   - TCP packet capture integration
   - Connection pattern analysis
   - Network health monitoring

2. **Memory Profiling**
   - Memory usage tracking and analysis
   - Memory leak detection
   - Profiling report generation
   - Memory snapshot management

3. **Performance Optimization**
   - Framework overhead optimization
   - Memory usage optimization
   - Parallel execution improvements

4. **Advanced Client Tools**
   - Complete client tool integration (import, export, benchmark, backup)
   - Advanced tool configuration
   - Tool performance monitoring

**Deliverables**: Network monitoring, memory profiling, performance optimization

### Phase 6: Production Features and Polish (Weeks 11-12)
**Goal**: Production readiness and comprehensive documentation

1. **Production Features**
   - Comprehensive error handling and recovery
   - Advanced logging and debugging
   - Resource cleanup and management
   - Signal handling and graceful shutdown

2. **Documentation and Examples**
   - API documentation
   - User guide and tutorials
   - Migration guide from JavaScript framework
   - Example test suites and configurations

3. **Testing and Validation**
   - Comprehensive framework test suite
   - Performance benchmarking
   - Compatibility validation with existing tests
   - Regression testing

4. **Final Polish**
   - CLI usability improvements
   - Error message improvements
   - Performance fine-tuning
   - Release preparation

**Deliverables**: Production-ready framework with documentation and validation

## Dependencies

### Core Dependencies
```toml
[project]
dependencies = [
    "pytest>=7.4.0",
    "pytest-asyncio>=0.21.0",
    "pydantic>=2.5.0",
    "typer>=0.9.0",              # Modern CLI framework
    "rich>=13.0.0",              # Rich terminal output
    "psutil>=5.9.0",             # Process monitoring
    "aiofiles>=23.0.0",          # Async file operations
    "aiohttp>=3.9.0",            # HTTP client for API calls
    "PyYAML>=6.0",               # Configuration files
    "jinja2>=3.1.0",             # Template rendering
]

[project.optional-dependencies]
monitoring = [
    "prometheus-client>=0.19.0", # Metrics collection
    "scapy>=2.5.0",             # Network packet capture
]
analysis = [
    "pandas>=2.1.0",            # Statistical analysis
    "matplotlib>=3.8.0",        # Visualization
    "seaborn>=0.13.0",          # Statistical plots
]
development = [
    "black>=23.0.0",            # Code formatting
    "isort>=5.13.0",            # Import sorting
    "mypy>=1.7.0",              # Type checking
    "pytest-cov>=4.1.0",       # Coverage
    "pre-commit>=3.6.0",       # Git hooks
]
```

### System Requirements
- **Python**: 3.9+ (async/await, type hints, dataclasses)
- **Operating System**: Linux (Ubuntu 20.04+, RHEL 8+)
- **Memory**: 4GB+ recommended for cluster testing
- **Storage**: 10GB+ for test data and logs

## Testing Strategy

### Framework Testing
```python
# tests/unit/test_server.py - Unit tests for server management
# tests/integration/test_cluster.py - Integration tests for cluster
# tests/performance/test_overhead.py - Performance impact tests
# tests/regression/test_compatibility.py - Compatibility with existing tests
```

### Validation Approach
1. **Unit Testing**: Test individual components in isolation
2. **Integration Testing**: Test with real ArangoDB instances
3. **Performance Testing**: Validate monitoring overhead
4. **Compatibility Testing**: Run subset of existing JavaScript tests
5. **Regression Testing**: Ensure equivalent functionality

## Migration Strategy

### From JavaScript Framework
1. **Phase 1**: Run both frameworks in parallel
2. **Phase 2**: Migrate subset of critical tests
3. **Phase 3**: Feature parity validation
4. **Phase 4**: Full migration with deprecation of JavaScript framework

### Configuration Migration
- Automatic conversion tool for existing configurations
- Mapping guide for parameter name changes
- Compatibility mode for gradual migration

This implementation plan provides a comprehensive roadmap for creating a modern, production-ready Python testing framework that maintains all the sophisticated functionality of the original JavaScript system while embracing Python best practices and pytest conventions.
