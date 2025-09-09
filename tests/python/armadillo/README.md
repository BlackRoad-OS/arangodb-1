# Armadillo: Modern ArangoDB Testing Framework

**Phase 1 Implementation - Core Foundation**

Armadillo is a modern Python testing framework built on pytest that replaces ArangoDB's legacy JavaScript testing framework. This Phase 1 implementation provides the core foundation with single-server support, structured logging, timeout management, and basic result analysis.

## Features

### ✅ Phase 1 (Current)
- **Single Server Management**: Start, stop, and monitor ArangoDB server instances
- **Layered Timeout System**: Global deadlines, per-test timeouts, watchdog enforcement
- **Structured Logging**: JSON + Rich terminal output with context tracking
- **Process Supervision**: Robust process management with crash detection
- **Pytest Integration**: Native plugin with fixtures and markers
- **Result Export**: JSON and JUnit XML output formats
- **CLI Interface**: Modern Typer-based command line interface
- **Result Analysis**: Basic summary analysis (replacing examine_results.js)

### 🚧 Future Phases
- **Phase 2**: Cluster support, agency management, SUT checkers
- **Phase 3**: Advanced test management, multi-format results, client tools
- **Phase 4**: Crash analysis with GDB integration, sanitizer support
- **Phase 5**: Network monitoring, memory profiling, performance analysis
- **Phase 6**: Production features, comprehensive documentation
- **Phase 7**: Complex semantic test suites (traversal, CRUD divergence)

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

# With custom timeout and output
armadillo test run tests/ --timeout 300 --output-dir ./results

# Verbose mode
armadillo test run tests/ -vv
```

### Analyze Results
```bash
# Show summary
armadillo analyze summary ./results/UNITTEST_RESULT.json

# Plain text output
armadillo analyze summary ./results/UNITTEST_RESULT.json --format plain

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
- `@pytest.mark.arango_cluster`: Requires cluster (Phase 2+)
- `@pytest.mark.slow`: Long-running test
- `@pytest.mark.crash_test`: Test involves crashes
- `@pytest.mark.rta_suite("name")`: RTA test suite marker

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

**Port allocation errors:**
```bash
# Clean up port reservations
rm -f /tmp/armadillo/ports.txt
```

**Log analysis:**
```bash
# Enable debug logging
armadillo test run -vv tests/

# Check JSON logs
cat ./test-results/armadillo.log
```

## Support

- **Documentation**: See `tests/python/plan/` for detailed design docs
- **Architecture**: Refer to `implementation_plan.md` for full system overview
- **Issues**: Phase 1 focuses on core functionality; advanced features in later phases

---

*Armadillo Phase 1 - Modern ArangoDB Testing Framework*

