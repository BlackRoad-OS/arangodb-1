"""Shared logging formatters and context management."""

import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict
from contextlib import contextmanager

from rich.console import Console
from rich.logging import RichHandler
from rich.text import Text
from rich.theme import Theme


class LogContext:
    """Thread-local logging context for structured metadata."""

    def __init__(self) -> None:
        self._local = threading.local()

    def set_context(self, **kwargs: Any) -> None:
        """Set context variables for current thread."""
        if not hasattr(self._local, "context"):
            self._local.context = {}
        self._local.context.update(kwargs)

    def get_context(self) -> Dict[str, Any]:
        """Get current thread context."""
        if not hasattr(self._local, "context"):
            return {}
        return self._local.context.copy()

    def clear_context(self) -> None:
        """Clear context for current thread."""
        if hasattr(self._local, "context"):
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
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add exception information if present
        if record.exc_info:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": (
                    self.formatException(record.exc_info) if record.exc_info else None
                ),
            }

        # Add extra fields from record
        extra_fields = {}
        for key, value in record.__dict__.items():
            if key not in {
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "message",
            }:
                extra_fields[key] = value

        if extra_fields:
            log_entry["fields"] = extra_fields

        # Add thread context if enabled
        if self.include_context:
            context = _log_context.get_context()
            if context:
                log_entry["context"] = context

        return json.dumps(log_entry, default=str)


class ArmadilloRichHandler(RichHandler):
    """Custom Rich handler with structured log formatting."""

    def __init__(self, *args, **kwargs):
        # Configure rich console with armadillo theme
        theme = Theme(
            {
                "logging.level.debug": "dim cyan",
                "logging.level.info": "dim blue",
                "logging.level.warning": "yellow",
                "logging.level.error": "red",
                "logging.level.critical": "bold red",
                "armadillo.event": "bright_green",
                "armadillo.process": "bright_blue",
                "armadillo.server": "bright_cyan",
                "armadillo.test": "bright_magenta",
            }
        )

        console = Console(theme=theme, stderr=True)
        super().__init__(*args, console=console, **kwargs)

    def render_message(self, record: logging.LogRecord, message: str) -> Text:
        """Render message with context-aware styling."""
        text = Text(message)

        # Apply styling based on event type or logger name
        event_type = getattr(record, "event_type", None)
        if event_type:
            style_map = {
                "process": "armadillo.process",
                "server": "armadillo.server",
                "test": "armadillo.test",
                "event": "armadillo.event",
            }
            if event_type in style_map:
                text.stylize(style_map[event_type])

        return text
