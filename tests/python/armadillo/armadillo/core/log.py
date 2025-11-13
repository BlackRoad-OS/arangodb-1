"""Structured logging system with JSON output and rich terminal formatting."""

import logging
from typing import Any, Dict, Optional, Union, Protocol
from pathlib import Path


from .log_formatters import StructuredFormatter, ArmadilloRichHandler, _log_context
from .value_objects import ServerContext, ServerId


class Logger(Protocol):
    """Protocol for logger instances to enable dependency injection."""

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log debug message."""

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log info message."""

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log warning message."""

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log error message."""

    def exception(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log exception with traceback."""


class LogManager:
    """Central logging configuration and management.

    This class provides a simplified interface to the IsolatedLogManager architecture.
    """

    def __init__(self) -> None:
        # Import here to avoid circular imports
        from .logger_factory import IsolatedLogManager

        self._manager = IsolatedLogManager("global")
        self._configured = False

    def configure(
        self,
        level: Union[int, str] = logging.INFO,
        log_file: Optional[Path] = None,
        enable_json: bool = True,
        enable_console: bool = True,
        console_level: Optional[Union[int, str]] = None,
        configure_root_compat: bool = False,
    ) -> None:
        """Configure logging system.

        By default, only the isolated manager is configured. Set
        configure_root_compat=True to mirror handlers to the root logger
        for third-party library capture.
        """
        if self._configured:
            return

        # Configure the underlying isolated manager
        self._manager.configure(
            level=level,
            log_file=log_file,
            enable_json=enable_json,
            enable_console=enable_console,
            console_level=console_level,
        )

        if configure_root_compat:
            # Configure root logger for compatibility with code
            # that might use logging.getLogger() directly
            root_logger = logging.getLogger()
            root_logger.setLevel(logging.DEBUG)

            # Remove any existing handlers to prevent duplication
            for handler in root_logger.handlers[:]:
                root_logger.removeHandler(handler)

            # Add handlers to root logger for compatibility
            if enable_json and log_file:
                json_handler = logging.FileHandler(log_file)
                json_handler.setFormatter(StructuredFormatter())
                json_handler.setLevel(level)
                root_logger.addHandler(json_handler)

            if enable_console:
                console_level = console_level or level
                console_handler = ArmadilloRichHandler(
                    show_time=True, show_path=False, markup=True
                )
                console_handler.setLevel(console_level)
                root_logger.addHandler(console_handler)

        self._configured = True

    def get_logger(self, name: str) -> logging.Logger:
        """Get a logger instance."""
        # Use the isolated manager for new loggers
        return self._manager.create_logger(name)

    def shutdown(self) -> None:
        """Shutdown logging system."""
        self._manager.shutdown()

        # Also shutdown root logger for compatibility
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            try:
                handler.close()
            except (OSError, RuntimeError):
                pass  # Ignore handler close errors
            root_logger.removeHandler(handler)

        logging.shutdown()

    def reset_configuration(self) -> None:
        """Reset configuration to allow reconfiguration.

        This is useful for test isolation where different tests
        might need different logging configurations.
        """
        self._configured = False
        self._manager.shutdown()

        # Re-create isolated manager
        from .logger_factory import IsolatedLogManager

        self._manager = IsolatedLogManager("global")


# Global log manager instance
_log_manager = LogManager()


def configure_logging(**kwargs: Any) -> None:
    """Configure the global logging system."""
    _log_manager.configure(**kwargs)


def add_file_logging(log_file: Path, level: Union[int, str] = logging.DEBUG) -> None:
    """Add file logging to already-configured logging system.

    This is useful for adding detailed file logging after the temp directory
    is created, without disrupting the already-configured console logging.

    Args:
        log_file: Path to the log file
        level: Logging level for the file handler (default: DEBUG for detailed logs)
    """
    # Ensure parent directory exists
    log_file = Path(log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    # Create file handler with structured formatter
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(
        StructuredFormatter(
            include_context=True,
            context_getter=_log_manager._manager._context.get_context,
        )
    )
    file_handler.setLevel(level)

    # Add handler to all existing loggers in the isolated manager
    for logger in _log_manager._manager._loggers.values():
        logger.addHandler(file_handler)

    # Store the handler so we can add it to newly created loggers
    _log_manager._manager._json_handler = file_handler


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance."""
    return _log_manager.get_logger(name)


def shutdown_logging() -> None:
    """Shutdown the logging system."""
    _log_manager.shutdown()


def reset_logging() -> None:
    """Reset logging configuration to allow reconfiguration.

    This is useful for test isolation where different tests
    might need different logging configurations.
    """
    _log_manager.reset_configuration()


def log_event(
    logger: Logger, event_type: str, message: str, **kwargs: Any
) -> None:
    """Log a structured event with context."""
    logger.info(message, extra={"event_type": event_type, **kwargs})


def log_process_event(
    logger: Logger, event: str, pid: Optional[int] = None, **kwargs: Any
) -> None:
    """Log a process-related event."""
    extra: Dict[str, Any] = {"event_type": "process", "process_event": event}
    if pid is not None:
        extra["pid"] = pid
    extra.update(kwargs)
    logger.info("Process %s %s", pid, event, extra=extra)


def log_server_event(
    logger: Logger,
    event: str,
    server_id: Union[str, ServerContext, ServerId, None] = None,
    **kwargs: Any,
) -> None:
    """Log a server-related event.

    Accepts either a string server_id, ServerId, or a ServerContext for enriched logging
    with PID information.
    """
    extra: Dict[str, Any] = {"event_type": "server", "server_event": event}

    if isinstance(server_id, ServerContext):
        # Enriched logging with PID
        extra["server_id"] = str(server_id.server_id)
        extra["role"] = server_id.role.value
        if server_id.pid is not None:
            extra["pid"] = server_id.pid
        display_id = str(server_id)  # Uses ServerContext.__str__()
    elif isinstance(server_id, ServerId):
        # ServerId object
        extra["server_id"] = str(server_id)
        display_id = str(server_id)
    elif server_id is not None:
        # Legacy string server_id
        extra["server_id"] = server_id
        display_id = server_id
    else:
        display_id = None

    extra.update(kwargs)
    logger.info("Server %s %s", display_id, event, extra=extra)


def log_test_event(
    logger: Logger, event: str, test_name: Optional[str] = None, **kwargs: Any
) -> None:
    """Log a test-related event."""
    extra: Dict[str, Any] = {"event_type": "test", "test_event": event}
    if test_name is not None:
        extra["test_name"] = test_name
    extra.update(kwargs)
    logger.info("Test %s %s", test_name, event, extra=extra)


# Context management shortcuts
def set_log_context(**kwargs: Any) -> None:
    """Set logging context for current thread."""
    _log_context.set_context(**kwargs)


def get_log_context() -> Dict[str, Any]:
    """Get current logging context."""
    return _log_context.get_context()


def clear_log_context() -> None:
    """Clear current logging context."""
    _log_context.clear_context()


def log_context(**kwargs: Any) -> Any:
    """Context manager for temporary logging context."""
    return _log_context.context(**kwargs)
