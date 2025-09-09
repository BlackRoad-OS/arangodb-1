"""Comprehensive error hierarchy and exception system for Armadillo framework."""

from typing import Optional, Dict, Any


class ArmadilloError(Exception):
    """Base exception for all Armadillo framework errors."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


# Configuration and Setup Errors
class ConfigurationError(ArmadilloError):
    """Error in framework configuration."""
    pass


class EnvironmentError(ArmadilloError):
    """Error in environment setup or detection."""
    pass


# Process and Instance Management Errors
class ProcessError(ArmadilloError):
    """Base class for process-related errors."""
    pass


class ProcessStartupError(ProcessError):
    """Error during process startup."""
    pass


class ProcessTimeoutError(ProcessError):
    """Process operation timed out."""

    def __init__(self, message: str, timeout: float, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, details)
        self.timeout = timeout


class ProcessCrashError(ProcessError):
    """Process crashed unexpectedly."""

    def __init__(self, message: str, exit_code: int, signal: Optional[int] = None,
                 details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, details)
        self.exit_code = exit_code
        self.signal = signal


# Server and Instance Errors
class ServerError(ArmadilloError):
    """Base class for ArangoDB server-related errors."""
    pass


class ServerStartupError(ServerError):
    """Error starting ArangoDB server."""
    pass


class ServerShutdownError(ServerError):
    """Error shutting down ArangoDB server."""
    pass


class HealthCheckError(ServerError):
    """Server health check failed."""

    def __init__(self, message: str, response_code: Optional[int] = None,
                 response_time: Optional[float] = None, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, details)
        self.response_code = response_code
        self.response_time = response_time


class NetworkError(ArmadilloError):
    """Network-related error."""
    pass


class ConnectionError(NetworkError):
    """Connection establishment failed."""
    pass


# Authentication and Security Errors
class AuthenticationError(ArmadilloError):
    """Authentication-related error."""
    pass


class JWTError(AuthenticationError):
    """JWT token-related error."""
    pass


class NonceReplayError(AuthenticationError):
    """Nonce replay attack detected."""
    pass


# Data and Codec Errors
class CodecError(ArmadilloError):
    """Data encoding/decoding error."""
    pass


class SerializationError(CodecError):
    """Data serialization error."""
    pass


class DeserializationError(CodecError):
    """Data deserialization error."""
    pass


# Filesystem and IO Errors
class FilesystemError(ArmadilloError):
    """Filesystem operation error."""
    pass


class PathError(FilesystemError):
    """Path resolution or validation error."""
    pass


class AtomicWriteError(FilesystemError):
    """Atomic write operation failed."""
    pass


# Test Execution Errors
class TestExecutionError(ArmadilloError):
    """Error during test execution."""
    pass


class TestTimeoutError(TestExecutionError):
    """Test execution timed out."""

    def __init__(self, message: str, timeout: float, test_name: Optional[str] = None,
                 details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, details)
        self.timeout = timeout
        self.test_name = test_name


class TestSetupError(TestExecutionError):
    """Error during test setup."""
    pass


class TestTeardownError(TestExecutionError):
    """Error during test teardown."""
    pass


# Cluster and Agency Errors
class ClusterError(ArmadilloError):
    """Cluster operation error."""
    pass


class AgencyError(ClusterError):
    """Agency consensus error."""
    pass


class LeaderElectionError(AgencyError):
    """Leader election failed."""
    pass


# Monitoring and Analysis Errors
class MonitoringError(ArmadilloError):
    """Monitoring system error."""
    pass


class CrashAnalysisError(MonitoringError):
    """Crash analysis error."""
    pass


class GdbError(CrashAnalysisError):
    """GDB debugger error."""
    pass


class SanitizerError(MonitoringError):
    """Sanitizer report processing error."""
    pass


# Result Processing Errors
class ResultProcessingError(ArmadilloError):
    """Result processing error."""
    pass


class ResultExportError(ResultProcessingError):
    """Result export error."""
    pass


class AnalysisError(ResultProcessingError):
    """Result analysis error."""
    pass


# Timeout Management Errors
class TimeoutError(ArmadilloError):
    """Timeout management error."""
    pass


class DeadlineExceededError(TimeoutError):
    """Global deadline exceeded."""

    def __init__(self, message: str, deadline: float, elapsed: float,
                 details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, details)
        self.deadline = deadline
        self.elapsed = elapsed


class WatchdogTimeoutError(TimeoutError):
    """Watchdog timeout triggered."""

    def __init__(self, message: str, watchdog_timeout: float,
                 details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, details)
        self.watchdog_timeout = watchdog_timeout


# SUT Checker Errors
class CheckerError(ArmadilloError):
    """SUT checker error."""
    pass


class InvariantViolationError(CheckerError):
    """SUT invariant violation detected."""

    def __init__(self, message: str, checker_name: str, violations: Optional[Dict[str, Any]] = None,
                 details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, details)
        self.checker_name = checker_name
        self.violations = violations or {}


class ResourceLeakError(CheckerError):
    """Resource leak detected."""
    pass


# Plugin and Extension Errors
class PluginError(ArmadilloError):
    """Plugin system error."""
    pass


class PluginLoadError(PluginError):
    """Plugin loading error."""
    pass


class FixtureError(PluginError):
    """Pytest fixture error."""
    pass

