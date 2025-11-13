"""Tests for error hierarchy and exception handling."""

import pytest

from armadillo.core.errors import (
    ArmadilloError,
    ConfigurationError,
    ArmadilloEnvironmentError,
    ProcessError,
    ProcessStartupError,
    ProcessTimeoutError,
    ProcessCrashError,
    ServerError,
    ServerStartupError,
    ServerShutdownError,
    HealthCheckError,
    NetworkError,
    ServerConnectionError,
    AuthenticationError,
    JWTError,
    NonceReplayError,
    CodecError,
    SerializationError,
    DeserializationError,
    FilesystemError,
    PathError,
    AtomicWriteError,
    ExecutionError,
    ExecutionTimeoutError,
    SetupError,
    TeardownError,
    ClusterError,
    AgencyError,
    LeaderElectionError,
    MonitoringError,
    CrashAnalysisError,
    GdbError,
    SanitizerError,
    ResultProcessingError,
    ResultExportError,
    AnalysisError,
    ArmadilloTimeoutError,
    DeadlineExceededError,
    WatchdogTimeoutError,
    CheckerError,
    InvariantViolationError,
    ResourceLeakError,
    PluginError,
    PluginLoadError,
    FixtureError,
)


class TestBaseError:
    """Test base ArmadilloError class."""

    def test_basic_error_creation(self) -> None:
        """Test basic error creation."""
        error = ArmadilloError("Test error")
        assert str(error) == "Test error"
        assert error.message == "Test error"
        assert error.details == {}

    def test_error_with_details(self) -> None:
        """Test error creation with details."""
        details = {"code": 500, "context": "test"}
        error = ArmadilloError("Test error", details)
        assert error.details == details

    def test_error_inheritance(self) -> None:
        """Test that all custom errors inherit from ArmadilloError."""
        assert issubclass(ConfigurationError, ArmadilloError)
        assert issubclass(ProcessError, ArmadilloError)
        assert issubclass(ServerError, ArmadilloError)
        assert issubclass(NetworkError, ArmadilloError)


class TestProcessErrors:
    """Test process-related errors."""

    def test_process_timeout_error(self) -> None:
        """Test ProcessTimeoutError with timeout value."""
        error = ProcessTimeoutError("Command timed out", 30.0)
        assert error.timeout == 30.0
        assert str(error) == "Command timed out"

    def test_process_crash_error(self) -> None:
        """Test ProcessCrashError with exit code and signal."""
        error = ProcessCrashError("Process crashed", 1, 9)  # Exit code 1, signal 9
        assert error.exit_code == 1
        assert error.signal == 9

    def test_process_crash_error_without_signal(self) -> None:
        """Test ProcessCrashError without signal."""
        error = ProcessCrashError("Process crashed", -1)
        assert error.exit_code == -1
        assert error.signal is None


class TestServerErrors:
    """Test server-related errors."""

    def test_health_check_error(self) -> None:
        """Test HealthCheckError with response details."""
        error = HealthCheckError("Health check failed", 500, 2.5)
        assert error.response_code == 500
        assert error.response_time == 2.5

    def test_health_check_error_minimal(self) -> None:
        """Test HealthCheckError with minimal information."""
        error = HealthCheckError("Connection refused")
        assert error.response_code is None
        assert error.response_time is None


class TestExecutionErrors:
    """Test test execution related errors."""

    def test_test_timeout_error(self) -> None:
        """Test ExecutionTimeoutError with test name."""
        error = ExecutionTimeoutError("Test timed out", 60.0, "test_example")
        assert error.timeout == 60.0
        assert error.test_name == "test_example"

    def test_test_timeout_error_without_name(self) -> None:
        """Test ExecutionTimeoutError without test name."""
        error = ExecutionTimeoutError("Test timed out", 30.0)
        assert error.timeout == 30.0
        assert error.test_name is None


class ExecutionTimeoutErrors:
    """Test timeout management errors."""

    def test_deadline_exceeded_error(self) -> None:
        """Test DeadlineExceededError with timing information."""
        error = DeadlineExceededError("Deadline exceeded", 120.0, 125.0)
        assert error.deadline == 120.0
        assert error.elapsed == 125.0

    def test_watchdog_timeout_error(self) -> None:
        """Test WatchdogTimeoutError."""
        error = WatchdogTimeoutError("Watchdog timeout", 300.0)
        assert error.watchdog_timeout == 300.0


class TestCheckerErrors:
    """Test SUT checker errors."""

    def test_invariant_violation_error(self) -> None:
        """Test InvariantViolationError with violations."""
        violations = {"leaked_collections": ["test_col1", "test_col2"]}
        error = InvariantViolationError("Invariant violated", "collections", violations)
        assert error.checker_name == "collections"
        assert error.violations == violations

    def test_invariant_violation_error_without_violations(self) -> None:
        """Test InvariantViolationError without violations."""
        error = InvariantViolationError("Invariant violated", "tasks")
        assert error.checker_name == "tasks"
        assert error.violations == {}


class TestErrorHierarchy:
    """Test error hierarchy relationships."""

    def test_process_error_hierarchy(self) -> None:
        """Test process error hierarchy."""
        assert issubclass(ProcessStartupError, ProcessError)
        assert issubclass(ProcessTimeoutError, ProcessError)
        assert issubclass(ProcessCrashError, ProcessError)

    def test_server_error_hierarchy(self) -> None:
        """Test server error hierarchy."""
        assert issubclass(ServerStartupError, ServerError)
        assert issubclass(ServerShutdownError, ServerError)
        assert issubclass(HealthCheckError, ServerError)

    def test_auth_error_hierarchy(self) -> None:
        """Test authentication error hierarchy."""
        assert issubclass(JWTError, AuthenticationError)
        assert issubclass(NonceReplayError, AuthenticationError)

    def test_codec_error_hierarchy(self) -> None:
        """Test codec error hierarchy."""
        assert issubclass(SerializationError, CodecError)
        assert issubclass(DeserializationError, CodecError)

    def test_filesystem_error_hierarchy(self) -> None:
        """Test filesystem error hierarchy."""
        assert issubclass(PathError, FilesystemError)
        assert issubclass(AtomicWriteError, FilesystemError)

    def test_cluster_error_hierarchy(self) -> None:
        """Test cluster error hierarchy."""
        assert issubclass(AgencyError, ClusterError)
        assert issubclass(LeaderElectionError, AgencyError)

    def test_monitoring_error_hierarchy(self) -> None:
        """Test monitoring error hierarchy."""
        assert issubclass(CrashAnalysisError, MonitoringError)
        assert issubclass(GdbError, CrashAnalysisError)
        assert issubclass(SanitizerError, MonitoringError)

    def test_result_error_hierarchy(self) -> None:
        """Test result processing error hierarchy."""
        assert issubclass(ResultExportError, ResultProcessingError)
        assert issubclass(AnalysisError, ResultProcessingError)

    def test_checker_error_hierarchy(self) -> None:
        """Test checker error hierarchy."""
        assert issubclass(InvariantViolationError, CheckerError)
        assert issubclass(ResourceLeakError, CheckerError)


class TestErrorUsage:
    """Test practical error usage scenarios."""

    def test_error_with_context(self) -> None:
        """Test error with contextual information."""
        details = {"command": ["arangod", "--help"], "cwd": "/tmp", "timeout": 30}
        error = ProcessTimeoutError("Command execution timed out", 30.0, details)

        assert "command" in error.details
        assert error.details["timeout"] == 30
        assert error.timeout == 30.0

    def test_error_chaining(self) -> None:
        """Test error chaining with cause."""
        try:
            raise ValueError("Original error")
        except ValueError as e:
            error = ConfigurationError("Configuration failed")
            error.__cause__ = e
            assert error.__cause__ is e

    def test_multiple_error_types(self) -> None:
        """Test different error types can be distinguished."""
        errors = [
            ProcessTimeoutError("Timeout", 30.0),
            HealthCheckError("Health failed"),
            InvariantViolationError("Violation", "checker"),
        ]

        # Should be able to handle different error types
        for error in errors:
            assert isinstance(error, ArmadilloError)
            if isinstance(error, ProcessTimeoutError):
                assert hasattr(error, "timeout")
            elif isinstance(error, HealthCheckError):
                assert hasattr(error, "response_code")
            elif isinstance(error, InvariantViolationError):
                assert hasattr(error, "checker_name")
