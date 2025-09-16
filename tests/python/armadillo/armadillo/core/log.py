"""Structured logging system with JSON output and rich terminal formatting."""

import sys
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional, TextIO, Union, Protocol
from pathlib import Path
from contextlib import contextmanager

from rich.console import Console
from rich.logging import RichHandler
from rich.text import Text
from rich.theme import Theme

from .errors import ArmadilloError


class Logger(Protocol):
    """Protocol for logger instances to enable dependency injection."""

    def debug(self, msg: str, *args, **kwargs) -> None:
        """Log debug message."""
        ...

    def info(self, msg: str, *args, **kwargs) -> None:
        """Log info message."""
        ...

    def warning(self, msg: str, *args, **kwargs) -> None:
        """Log warning message."""
        ...

    def error(self, msg: str, *args, **kwargs) -> None:
        """Log error message."""
        ...

    def exception(self, msg: str, *args, **kwargs) -> None:
        """Log exception with traceback."""
        ...


class LogContext:
    """Thread-local logging context for structured metadata."""

    def __init__(self) -> None:
        self._local = threading.local()

    def set_context(self, **kwargs: Any) -> None:
        """Set context variables for current thread."""
        if not hasattr(self._local, 'context'):
            self._local.context = {}
        self._local.context.update(kwargs)

    def get_context(self) -> Dict[str, Any]:
        """Get current thread context."""
        if not hasattr(self._local, 'context'):
            return {}
        return self._local.context.copy()

    def clear_context(self) -> None:
        """Clear context for current thread."""
        if hasattr(self._local, 'context'):
            self._local.context.clear()

    @contextmanager
    def context(self, **kwargs: Any):
        """Context manager for temporary context variables."""
        old_context = self.get_context()
        try:
            self.set_context(**kwargs)
            yield
        finally:
            self.clear_context()
            self.set_context(**old_context)


# Global logging context
_log_context = LogContext()


class StructuredFormatter(logging.Formatter):
    """JSON formatter for structured logging."""

    def __init__(self, include_context: bool = True) -> None:
        super().__init__()
        self.include_context = include_context

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_entry = {
            'timestamp': datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
        }

        # Add exception information if present
        if record.exc_info:
            log_entry['exception'] = {
                'type': record.exc_info[0].__name__ if record.exc_info[0] else None,
                'message': str(record.exc_info[1]) if record.exc_info[1] else None,
                'traceback': self.formatException(record.exc_info) if record.exc_info else None,
            }

        # Add extra fields from record
        extra_fields = {}
        for key, value in record.__dict__.items():
            if key not in {'name', 'msg', 'args', 'levelname', 'levelno', 'pathname',
                          'filename', 'module', 'exc_info', 'exc_text', 'stack_info',
                          'lineno', 'funcName', 'created', 'msecs', 'relativeCreated',
                          'thread', 'threadName', 'processName', 'process', 'message'}:
                extra_fields[key] = value

        if extra_fields:
            log_entry['fields'] = extra_fields

        # Add thread context if enabled
        if self.include_context:
            context = _log_context.get_context()
            if context:
                log_entry['context'] = context

        return json.dumps(log_entry, default=str)


class ArmadilloRichHandler(RichHandler):
    """Custom Rich handler with structured log formatting."""

    def __init__(self, *args, **kwargs):
        # Configure rich console with armadillo theme
        theme = Theme({
            "logging.level.debug": "dim cyan",
            "logging.level.info": "dim blue",
            "logging.level.warning": "yellow",
            "logging.level.error": "red",
            "logging.level.critical": "bold red",
            "armadillo.event": "bright_green",
            "armadillo.process": "bright_blue",
            "armadillo.server": "bright_cyan",
            "armadillo.test": "bright_magenta",
        })

        console = Console(theme=theme, stderr=True)
        super().__init__(*args, console=console, **kwargs)

    def render_message(self, record: logging.LogRecord, message: str) -> Text:
        """Render message with context-aware styling."""
        text = Text(message)

        # Apply styling based on event type or logger name
        event_type = getattr(record, 'event_type', None)
        if event_type:
            style_map = {
                'process': 'armadillo.process',
                'server': 'armadillo.server',
                'test': 'armadillo.test',
                'event': 'armadillo.event',
            }
            if event_type in style_map:
                text.stylize(style_map[event_type])

        return text


class LogManager:
    """Central logging configuration and management."""

    def __init__(self) -> None:
        self._configured = False
        self._log_file: Optional[Path] = None
        self._json_handler: Optional[logging.Handler] = None
        self._console_handler: Optional[logging.Handler] = None

    def configure(self,
                  level: Union[int, str] = logging.INFO,
                  log_file: Optional[Path] = None,
                  enable_json: bool = True,
                  enable_console: bool = True,
                  console_level: Optional[Union[int, str]] = None) -> None:
        """Configure logging system."""
        if self._configured:
            return

        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)

        # Remove any existing handlers
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)

        # Configure JSON file logging
        if enable_json and log_file:
            self._log_file = Path(log_file)
            self._log_file.parent.mkdir(parents=True, exist_ok=True)

            self._json_handler = logging.FileHandler(self._log_file)
            self._json_handler.setFormatter(StructuredFormatter())
            self._json_handler.setLevel(level)
            root_logger.addHandler(self._json_handler)

        # Configure console logging
        if enable_console:
            console_level = console_level or level
            self._console_handler = ArmadilloRichHandler(
                show_time=True,
                show_path=False,
                markup=True
            )
            self._console_handler.setLevel(console_level)
            root_logger.addHandler(self._console_handler)

        self._configured = True

    def get_logger(self, name: str) -> logging.Logger:
        """Get a logger instance."""
        return logging.getLogger(name)

    def shutdown(self) -> None:
        """Shutdown logging system."""
        if self._json_handler:
            try:
                self._json_handler.close()
            except Exception:
                pass  # Ignore handler close errors
        if self._console_handler:
            try:
                self._console_handler.close()
            except Exception:
                pass  # Ignore handler close errors

        logging.shutdown()


# Global log manager instance
_log_manager = LogManager()


def configure_logging(**kwargs) -> None:
    """Configure the global logging system."""
    _log_manager.configure(**kwargs)


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance."""
    return _log_manager.get_logger(name)


def shutdown_logging() -> None:
    """Shutdown the logging system."""
    _log_manager.shutdown()


def log_event(logger: logging.Logger, event_type: str, message: str, **kwargs) -> None:
    """Log a structured event with context."""
    logger.info(message, extra={'event_type': event_type, **kwargs})


def log_process_event(logger: logging.Logger, event: str, pid: Optional[int] = None, **kwargs) -> None:
    """Log a process-related event."""
    extra = {'event_type': 'process', 'process_event': event}
    if pid is not None:
        extra['pid'] = pid
    extra.update(kwargs)
    logger.info(f"Process {event}", extra=extra)


def log_server_event(logger: logging.Logger, event: str, server_id: Optional[str] = None, **kwargs) -> None:
    """Log a server-related event."""
    extra = {'event_type': 'server', 'server_event': event}
    if server_id is not None:
        extra['server_id'] = server_id
    extra.update(kwargs)
    logger.info(f"Server {event}", extra=extra)


def log_test_event(logger: logging.Logger, event: str, test_name: Optional[str] = None, **kwargs) -> None:
    """Log a test-related event."""
    extra = {'event_type': 'test', 'test_event': event}
    if test_name is not None:
        extra['test_name'] = test_name
    extra.update(kwargs)
    logger.info(f"Test {event}", extra=extra)


# Context management shortcuts
def set_log_context(**kwargs) -> None:
    """Set logging context for current thread."""
    _log_context.set_context(**kwargs)


def get_log_context() -> Dict[str, Any]:
    """Get current logging context."""
    return _log_context.get_context()


def clear_log_context() -> None:
    """Clear current logging context."""
    _log_context.clear_context()


def log_context(**kwargs):
    """Context manager for temporary logging context."""
    return _log_context.context(**kwargs)

