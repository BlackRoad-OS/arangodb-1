"""Logger factory for creating isolated logging environments."""

import logging
import threading
from typing import Any, Dict, Optional, Union, Protocol
from pathlib import Path
from contextlib import contextmanager


from .log_formatters import StructuredFormatter, ArmadilloRichHandler, LogContext


class LoggerFactory(Protocol):
    """Protocol for logger factories to enable dependency injection."""

    def create_logger(self, name: str) -> logging.Logger:
        """Create a logger instance."""

    def shutdown(self) -> None:
        """Shutdown the logging system."""


class IsolatedLogManager:
    """Non-singleton log manager for isolated logging environments."""

    def __init__(self, namespace: str = "") -> None:
        """Initialize isolated log manager.

        Args:
            namespace: Namespace prefix for logger names to ensure isolation
        """
        self._namespace = namespace
        self._configured = False
        self._log_file: Optional[Path] = None
        self._json_handler: Optional[logging.Handler] = None
        self._console_handler: Optional[logging.Handler] = None
        self._loggers: Dict[str, logging.Logger] = {}
        self._context = LogContext()
        self._lock = threading.RLock()

    def configure(self,
                  level: Union[int, str] = logging.INFO,
                  log_file: Optional[Path] = None,
                  enable_json: bool = True,
                  enable_console: bool = True,
                  console_level: Optional[Union[int, str]] = None) -> None:
        """Configure this logging instance."""
        with self._lock:
            # Allow reconfiguration for test isolation
            if self._configured:
                self._clear_configuration()

            # Configure JSON file logging
            if enable_json and log_file:
                self._log_file = Path(log_file)
                self._log_file.parent.mkdir(parents=True, exist_ok=True)

                self._json_handler = logging.FileHandler(self._log_file)
                self._json_handler.setFormatter(StructuredFormatter(include_context=True))
                self._json_handler.setLevel(level)

            # Configure console logging
            if enable_console:
                console_level = console_level or level
                self._console_handler = ArmadilloRichHandler(
                    show_time=True,
                    show_path=False,
                    markup=True
                )
                self._console_handler.setLevel(console_level)

            self._configured = True

    def create_logger(self, name: str) -> logging.Logger:
        """Create a logger instance with namespace isolation."""
        with self._lock:
            # Add namespace prefix for isolation
            full_name = f"{self._namespace}.{name}" if self._namespace else name

            if full_name in self._loggers:
                return self._loggers[full_name]

            logger = logging.getLogger(full_name)

            # Ensure logger doesn't propagate to root to avoid global interference
            logger.propagate = False
            logger.setLevel(logging.DEBUG)

            # Add our handlers if configured
            if self._json_handler:
                logger.addHandler(self._json_handler)
            if self._console_handler:
                logger.addHandler(self._console_handler)

            self._loggers[full_name] = logger
            return logger

    def get_context(self) -> Dict[str, Any]:
        """Get current logging context for this instance."""
        return self._context.get_context()

    def set_context(self, **kwargs: Any) -> None:
        """Set logging context for this instance."""
        self._context.set_context(**kwargs)

    def clear_context(self) -> None:
        """Clear logging context for this instance."""
        self._context.clear_context()

    @contextmanager
    def context(self, **kwargs: Any):
        """Context manager for temporary context variables."""
        with self._context.context(**kwargs):
            yield

    def shutdown(self) -> None:
        """Shutdown this logging instance."""
        with self._lock:
            self._clear_configuration()
            self._loggers.clear()
            self._context.clear_context()

    def _clear_configuration(self) -> None:
        """Clear current configuration and handlers."""
        # Remove handlers from all managed loggers
        for logger in self._loggers.values():
            for handler in logger.handlers[:]:
                logger.removeHandler(handler)

        # Close and clean up handlers
        if self._json_handler:
            try:
                self._json_handler.close()
            except (OSError, RuntimeError):
                pass  # Ignore handler close errors
            self._json_handler = None

        if self._console_handler:
            try:
                self._console_handler.close()
            except (OSError, RuntimeError):
                pass  # Ignore handler close errors
            self._console_handler = None

        self._configured = False


class StandardLoggerFactory:
    """Standard implementation of LoggerFactory using IsolatedLogManager."""

    def __init__(self,
                 namespace: Optional[str] = None,
                 level: Union[int, str] = logging.INFO,
                 log_file: Optional[Path] = None,
                 enable_json: bool = True,
                 enable_console: bool = True,
                 console_level: Optional[Union[int, str]] = None) -> None:
        """Initialize standard logger factory.

        Args:
            namespace: Namespace for logger isolation
            level: Default logging level
            log_file: Optional log file path
            enable_json: Whether to enable JSON file logging
            enable_console: Whether to enable console logging
            console_level: Console logging level (defaults to level)
        """
        self._manager = IsolatedLogManager(namespace or "")
        self._manager.configure(
            level=level,
            log_file=log_file,
            enable_json=enable_json,
            enable_console=enable_console,
            console_level=console_level
        )

    def create_logger(self, name: str) -> logging.Logger:
        """Create a logger instance."""
        return self._manager.create_logger(name)

    def shutdown(self) -> None:
        """Shutdown the logging system."""
        self._manager.shutdown()

    # Context management convenience methods
    def get_context(self) -> Dict[str, Any]:
        """Get current logging context."""
        return self._manager.get_context()

    def set_context(self, **kwargs: Any) -> None:
        """Set logging context."""
        self._manager.set_context(**kwargs)

    def clear_context(self) -> None:
        """Clear logging context."""
        self._manager.clear_context()

    @contextmanager
    def context(self, **kwargs: Any):
        """Context manager for temporary context variables."""
        with self._manager.context(**kwargs):
            yield


# Utility functions for logging events with factory-created loggers
def log_event(logger: logging.Logger, event_type: str, message: str, **kwargs) -> None:
    """Log a structured event with context."""
    logger.info(message, extra={'event_type': event_type, **kwargs})


def log_process_event(logger: logging.Logger, event: str, pid: Optional[int] = None, **kwargs) -> None:
    """Log a process-related event."""
    extra = {'event_type': 'process', 'process_event': event}
    if pid is not None:
        extra['pid'] = pid
    extra.update(kwargs)
    logger.info("Process %s", event, extra=extra)


def log_server_event(logger: logging.Logger, event: str, server_id: Optional[str] = None, **kwargs) -> None:
    """Log a server-related event."""
    extra = {'event_type': 'server', 'server_event': event}
    if server_id is not None:
        extra['server_id'] = server_id
    extra.update(kwargs)
    logger.info("Server %s", event, extra=extra)


def log_test_event(logger: logging.Logger, event: str, test_name: Optional[str] = None, **kwargs) -> None:
    """Log a test-related event."""
    extra = {'event_type': 'test', 'test_event': event}
    if test_name is not None:
        extra['test_name'] = test_name
    extra.update(kwargs)
    logger.info("Test %s", event, extra=extra)
