# testing.js - Main Test Framework Entry Point

## Purpose
Main orchestration module that serves as the entry point for the entire ArangoDB testing framework. Provides command-line interface, test suite discovery, execution coordination, and result aggregation.

## Core Functionality

### Test Suite Management
- **Dynamic Test Suite Loading**: Automatically discovers and loads test suites from `@arangodb/testsuites/` directory
- **Test Function Registry**: Maintains a registry of all available test functions with documentation
- **Module Option Registration**: Collects configuration options from all framework modules
- **Wildcard Expansion**: Supports wildcard patterns in test suite names (e.g., `cluster*`)

### Test Discovery and Filtering
- **Test Case Discovery**: `findTestCases()` scans test paths and applies filters
- **Pattern Matching**: Supports complex test filtering by name patterns and file paths
- **Cluster Test Detection**: Automatically detects cluster-specific tests by naming convention
- **Auto Test Resolution**: `autoTest()` automatically finds and runs matching test suites

### Command-Line Interface
- **Argument Parsing**: Comprehensive CLI argument processing with defaults
- **Usage Documentation**: Dynamic help generation from registered test functions
- **Option Validation**: Configuration option validation and normalization
- **Completion Support**: `dumpCompletions()` provides shell completion data

### Test Execution Orchestration
- **Sequential Execution**: `iterateTests()` manages ordered test suite execution
- **Failed Test Re-runs**: Support for re-running only previously failed tests
- **Multiple Option Sets**: Support for running same test with different configurations via `optionsJson`
- **Instance Management**: Coordinates with instance manager for test isolation

### Result Processing and Aggregation
- **Status Aggregation**: Collects and normalizes results across all test suites
- **Global Status Tracking**: Maintains overall pass/fail status across test runs
- **Crash Detection**: Integrates with process utilities to detect server crashes
- **Result Normalization**: Standardizes result formats from different test runners

### Configuration Management
- **Default Options**: Comprehensive set of default configuration options
- **Option Inheritance**: Supports option inheritance and overrides
- **Environment Integration**: Integrates with environment variables and external configuration
- **Module Registration**: Allows test modules to register their own configuration options

### Error Handling and Debugging
- **Exception Handling**: Comprehensive exception handling during test execution
- **Verbose Logging**: Multiple verbosity levels for debugging
- **Signal Handling**: Interrupt handling for graceful test termination
- **Error Propagation**: Proper error propagation with stack traces

## Key Configuration Options

### Execution Control
- `force`: Continue execution even if tests fail
- `cleanup`: Whether to remove data files and logs after tests
- `extremeVerbosity`: Detailed logging for debugging
- `failed`: Re-run only previously failed tests
- `oneTestTimeout`: Timeout for individual test suites

### Protocol and Communication
- `protocol`: Communication protocol (tcp, ssl, unix)
- `vst`/`http2`: Enable VST or HTTP/2 protocols
- `forceJson`: Disable VPack compression for debugging
- `username`/`password`: Authentication credentials

### Test Selection and Filtering
- `test`: Test name filter patterns
- `testBuckets`: Test bucketing for parallel execution
- `suffix`: Append suffix to test result names

## Integration Points
- **Process Utils**: Binary setup and process management
- **Result Processing**: Result collection and export
- **Crash Utils**: Crash detection and analysis
- **Test Utils**: Test discovery and filtering utilities
- **Instance Management**: Server instance coordination

## Special Features
- **Auto Mode**: Automatically discovers and runs tests matching filter criteria
- **Find Mode**: Searches and lists available tests without execution
- **Bucket Support**: Supports test partitioning for parallel execution
- **Signal Handling**: Proper interrupt handling for clean shutdown
- **Module Discovery**: Dynamic module loading and option registration
