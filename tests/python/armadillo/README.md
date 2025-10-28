# Armadillo: Modern ArangoDB Testing Framework

Armadillo is a modern Python testing framework built on pytest that replaces ArangoDB's legacy JavaScript testing framework. It provides comprehensive support for both single-server and cluster deployments with sophisticated lifecycle management, structured logging, and result analysis.

## Features

### ✅ Current Implementation
- **Multi-Server Support**: Single server and cluster deployments with unified infrastructure
- **Cluster Management**: Agency coordination, database server management, rolling restarts
- **Layered Timeout System**: Global deadlines, per-test timeouts, watchdog enforcement  
- **Structured Logging**: JSON + Rich terminal output with context tracking
- **Process Supervision**: Robust process management with crash detection and cleanup
- **Pytest Integration**: Native plugin with fixtures and markers
- **Result Export**: JSON and JUnit XML output formats
- **CLI Interface**: Modern Typer-based command line interface
- **Result Analysis**: Comprehensive summary analysis and reporting
- **Health Monitoring**: Server readiness checks and deployment verification
- **Port Management**: Automatic port allocation with collision avoidance

## Installation

```bash
cd tests/python/armadillo
pip install -e .
```

## Quick Start

### Run Tests
```bash
# Single server tests (default)
armadillo test run tests/

# Cluster tests
armadillo test run tests/ --cluster

# With custom timeout and output
armadillo test run tests/ --timeout 300 --output-dir ./results

# Verbose mode with server logs
armadillo -vv test run tests/ --show-server-logs

# Compact output
armadillo test run tests/ --compact
```

### Analyze Results
```bash
# Show summary
armadillo analyze summary ./results/test_results.json

# Plain text output
armadillo analyze summary ./results/test_results.json --format plain

# List available analyzers
armadillo analyze list-analyzers
```

### Configuration
```bash
# Show current configuration
armadillo config

# Show version information
armadillo version
```

## Writing Tests

### Basic Test with Single Server
```python
import pytest

@pytest.mark.arango_single
def test_basic_operation(arango_single_server):
    """Test with session-scoped server."""
    server = arango_single_server
    assert server.is_running()

    # Your test code here
```

### Function-Scoped Server
```python
@pytest.mark.arango_single
def test_isolated_operation(arango_single_server_function):
    """Test with function-scoped server."""
    server = arango_single_server_function

    # Fresh server instance for this test
    assert server.is_running()
```

### Available Markers
- `@pytest.mark.arango_single`: Requires single ArangoDB server
- `@pytest.mark.arango_cluster`: Requires ArangoDB cluster
- `@pytest.mark.slow`: Long-running test
- `@pytest.mark.fast`: Fast test
- `@pytest.mark.crash_test`: Test involves intentional crashes
- `@pytest.mark.stress_test`: High-load stress test
- `@pytest.mark.flaky`: Known intermittent failures
- `@pytest.mark.auth_required`: Authentication required
- `@pytest.mark.cluster_coordination`: Cluster coordination features
- `@pytest.mark.replication`: Data replication
- `@pytest.mark.sharding`: Sharding functionality
- `@pytest.mark.failover`: High availability and failover
- `@pytest.mark.rta_suite("name")`: RTA test suite marker
- `@pytest.mark.smoke_test`: Basic smoke test
- `@pytest.mark.regression`: Regression test
- `@pytest.mark.performance`: Performance measurement test

### Available Fixtures
- `arango_single_server` (session): Single server for entire test session
- `arango_single_server_function` (function): Single server per test function
- `arango_cluster` (session): Full cluster deployment manager
- `arango_cluster_function` (function): Cluster per test function
- `arango_deployment`: Auto-selects single or cluster based on configuration
- `arango_coordinators` / `arango_dbservers` / `arango_agents`: Role-filtered server lists

## Architecture

```
armadillo/
├── core/           # Core framework (types, config, errors, logging, timeouts, process)
├── instances/      # Server instance management
├── utils/          # Utilities (filesystem, crypto, auth, codecs, ports)
├── pytest_plugin/ # Pytest integration
├── results/        # Result collection and export
└── cli/            # Command-line interface
```

## Key Components

### Timeout Management
- **Global Deadlines**: Overall test run time limits
- **Per-Test Timeouts**: Individual test time limits
- **Watchdog Enforcement**: Background monitoring with signal escalation
- **Cooperative Cancellation**: Async-aware timeout handling

### Process Management
- **ProcessExecutor**: One-shot command execution with timeouts
- **ProcessSupervisor**: Long-running process lifecycle management
- **Crash Detection**: Automatic process monitoring and failure reporting

### Structured Logging
- **Rich Terminal Output**: Colored, context-aware console logging
- **JSON Export**: Machine-readable structured logs
- **Context Tracking**: Per-test and per-server log segmentation
- **Event Classification**: Process, server, and test event taxonomy

### Health Monitoring
- **HTTP Health Checks**: Server readiness and responsiveness
- **Process Statistics**: Memory, CPU, and connection monitoring
- **Startup Validation**: Configurable readiness checks with timeout

## Environment Variables

Configure via environment variables with `ARMADILLO_` prefix:

```bash
export ARMADILLO_DEPLOYMENT_MODE=single_server
export ARMADILLO_TEST_TIMEOUT=900.0
export ARMADILLO_TEMP_DIR=/tmp/armadillo-tests
export ARMADILLO_BIN_DIR=/usr/local/bin
export ARMADILLO_VERBOSE=1
export ARMADILLO_LOG_LEVEL=INFO              # DEBUG, INFO, WARNING, ERROR
export ARMADILLO_SHOW_SERVER_LOGS=0          # 1 to show arangod stdout
export ARMADILLO_COMPACT_MODE=0              # 1 for compact pytest output
export ARMADILLO_KEEP_INSTANCES_ON_FAILURE=0 # 1 to keep servers on failure
```

## Development

### Framework Testing

The Armadillo framework itself is comprehensively tested with unit tests that are separate from the integration tests that will use the framework.

#### Test Structure
```
armadillo/
├── tests/                 # Integration tests (using the framework)
│   └── test_example.py    # Examples of framework usage
├── framework_tests/       # Unit tests for the framework itself
│   ├── conftest.py        # Test configuration and fixtures
│   ├── pytest.ini        # Framework test configuration
│   └── unit/              # Unit test modules
│       ├── test_core_*.py # Core component tests
│       ├── test_utils_*.py # Utility module tests
│       └── test_results_*.py # Result processing tests
└── run_framework_tests.py # Test runner script
```

#### Running Framework Tests
```bash
# Install development dependencies
pip install -e .[development]

# Run all framework unit tests
python run_framework_tests.py

# Run with verbose output
python run_framework_tests.py -v

# Run specific test categories
python run_framework_tests.py -k "crypto"
python run_framework_tests.py -k "config"
python run_framework_tests.py -k "timeout"

# Run with coverage
python run_framework_tests.py --cov=armadillo --cov-report=html

# Run specific test file
python run_framework_tests.py framework_tests/unit/test_core_types.py
```

#### Framework Test Categories
- **Core Components**: Types, configuration, errors, logging, timeouts, process management
- **Utilities**: Crypto, auth, filesystem, codecs, port management
- **Instance Management**: Server lifecycle, health monitoring
- **Result Processing**: Collection, export, analysis
- **CLI Components**: Command parsing, output formatting

#### Integration Tests vs Framework Tests
- **Framework Tests** (`framework_tests/`): Unit tests for framework components
  - No external dependencies (ArangoDB, network, etc.)
  - Fast execution (< 1s per test)
  - Mock external dependencies
  - Test edge cases and error conditions

- **Integration Tests** (`tests/`): End-to-end tests using the framework
  - Require actual ArangoDB instances
  - Test real server interactions
  - Validate complete workflows
  - Examples of framework usage

### Code Quality
```bash
# Type checking
mypy armadillo/

# Code formatting
black armadillo/
isort armadillo/

# Linting
flake8 armadillo/
```

### Project Structure
The implementation follows the documented plan from `implementation_plan.md` with:
- Modern Python practices (type hints, async/await, dataclasses)
- Clear error hierarchy and structured exception handling
- Comprehensive logging with both human and machine-readable output
- Layered timeout management for robustness
- Plugin-based pytest integration

## Migration from JavaScript Framework

This Phase 1 implementation provides:
- **Equivalent Functionality**: Single server lifecycle management
- **Enhanced Reliability**: Timeout management, structured error handling
- **Modern Development**: Type safety, rich tooling, pytest integration
- **Maintainability**: Clean architecture, comprehensive documentation

Future phases will provide full feature parity with the legacy system while maintaining the clean, modern design principles.

## Troubleshooting

### Common Issues

**Server startup failures:**
```bash
# Check binary path
armadillo config

# Increase startup timeout
armadillo test run --timeout 60 tests/
```

**Log analysis:**
```bash
# Enable debug logging
armadillo -vv test run tests/

# Results: JUnit XML and JSON are supported
ls ./test-results/
```

## Support

- **Documentation**: See `tests/python/plan/` for detailed design docs
- **Architecture**: Refer to `implementation_plan.md` for full system overview
- **Issues**: Phase 1 focuses on core functionality; advanced features in later phases

---

*Armadillo Phase 1 - Modern ArangoDB Testing Framework*

