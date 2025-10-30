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

## Timeouts

Armadillo provides three complementary timeout mechanisms to prevent hung tests and ensure reliable test execution:

### Per-Test Timeout (`--timeout`)

**Purpose**: Kill individual tests that run longer than expected  
**Default**: Disabled (no timeout)  
**Mechanism**: Uses `pytest-timeout` with SIGALRM on Linux  
**Behavior**: Interrupts blocking I/O, **aborts remaining tests**  

```bash
# Set 120 second timeout per test
armadillo test run tests/ --timeout 120
```

**When to use:**
- Tests that should complete quickly but might hang
- Prevents single slow test from blocking entire suite
- Useful for debugging which specific test is hanging

**⚠️ Important: Timeout Aborts Session**

When a test times out, **all remaining tests are skipped** (similar to server crash behavior). This prevents unreliable results from corrupted database state. Normal test failures continue to gather maximum information.

**Limitations:**
- Linux/Unix only (uses SIGALRM)
- Won't interrupt pure CPU-bound code without I/O
- May kill legitimately slow tests on loaded CI runners
- **Aborts remaining tests** (by design for integration tests)

### Global Timeout (`--global-timeout`)

**Purpose**: Kill entire test session if it exceeds total time budget  
**Default**: 900 seconds (15 minutes)  
**Mechanism**: Framework-level timeout monitoring  
**Behavior**: Terminates pytest subprocess and all child processes  

```bash
# Set 30 minute global timeout for entire session
armadillo test run tests/ --global-timeout 1800
```

**When to use:**
- CI/CD pipelines with hard time limits
- Prevent test suite from running indefinitely
- Catch cascading failures or test explosion

**Trade-offs:**
- Kills entire suite, even if only one test is slow
- Need to balance against expected suite duration
- Consider cluster startup time (~2-5 minutes)

### Output-Idle Timeout (`--output-idle-timeout`)

**Purpose**: Kill pytest if no stdout/stderr for N seconds  
**Default**: Disabled (no timeout)  
**Mechanism**: Monitors subprocess output, escalates SIGTERM → SIGKILL  
**Behavior**: Detects tests that hang silently without producing output  

```bash
# Kill pytest if no output for 5 minutes
armadillo test run tests/ --output-idle-timeout 300
```

**When to use:**
- Detect truly hung tests that neither fail nor timeout
- CI environments where silent hangs are common
- Tests that should produce regular progress output

**How it works:**
1. Monitors pytest stdout/stderr line-by-line
2. If no output for N seconds, sends SIGTERM
3. Waits 5 seconds for graceful shutdown
4. If still alive, sends SIGKILL
5. Preserves all output formatting

### Recommended Settings

**Local development** (fast feedback):
```bash
armadillo test run tests/ --timeout 60
```

**CI/CD pipelines** (comprehensive protection):
```bash
armadillo test run tests/ \
  --timeout 120 \
  --global-timeout 1800 \
  --output-idle-timeout 300
```

**Debugging hung tests**:
```bash
# Start with output-idle to identify which test hangs
armadillo test run tests/ --output-idle-timeout 60 -vv
```

### Timeout Interaction

All three timeouts work together:
- **Per-test** fires first for individual slow tests
- **Output-idle** catches tests that hang silently
- **Global** provides final safety net for entire session

If a test violates multiple timeouts, the first to trigger wins.

### Best Practices

1. **Start conservative**: Use longer timeouts initially, then tighten based on actual test duration
2. **Monitor CI timing**: Adjust timeouts based on 95th percentile of test runs
3. **Consider infrastructure**: Shared CI runners may be slower than dedicated hardware
4. **Use output-idle sparingly**: Only enable if you've seen silent hangs in practice
5. **Test your timeouts**: Armadillo includes integration tests to verify timeout enforcement

### Troubleshooting

**Tests killed by per-test timeout:**
- Check if test is actually hung or just slow
- Increase `--timeout` or optimize the test
- Consider splitting long tests into smaller units

**Tests killed by output-idle timeout:**
- Ensure tests produce regular output (print statements, logging)
- Increase `--output-idle-timeout` for legitimately slow operations
- Check for infinite loops or deadlocks

**Entire suite killed by global timeout:**
- Check if suite duration is expected
- Increase `--global-timeout` or split into smaller suites
- Investigate cascading failures or test explosion

### Timeout Extensibility

Timeout handling is centralized in `armadillo/cli/timeout_handler.py` with extension points for diagnostic collection:

```python
# Future: Add diagnostic collection before terminating
def collect_diagnostics(timeout_type: TimeoutType, elapsed: float):
    """Collect logs, coredumps, process states before killing process."""
    # Collect server logs from temp_dir
    # Trigger coredumps from running processes  
    # Capture process states (ps, lsof, etc.)
    # Save test artifacts

timeout_handler.set_pre_terminate_hook(collect_diagnostics)
```

See `armadillo/cli/timeout_handler.py` for implementation details.

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

