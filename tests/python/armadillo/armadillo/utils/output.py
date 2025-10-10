"""Output utilities for writing to stdout/stderr with proper flushing."""

import sys
from typing import Optional


def write_stdout(message: str, flush: bool = True) -> None:
    """Write message to stdout with optional flushing.

    Args:
        message: Message to write
        flush: Whether to flush after writing (default: True)
    """
    sys.stdout.write(message)
    if flush:
        sys.stdout.flush()


def write_stderr(message: str, flush: bool = True) -> None:
    """Write message to stderr with optional flushing.

    Args:
        message: Message to write
        flush: Whether to flush after writing (default: True)
    """
    sys.stderr.write(message)
    if flush:
        sys.stderr.flush()


def print_status(message: str, prefix: Optional[str] = None) -> None:
    """Print a status message to stdout.

    Status messages are always visible and provide important user-facing
    information about framework operations (e.g., "Starting cluster").

    Args:
        message: Status message to print
        prefix: Optional prefix (e.g., "🚀", "✅", "🧹")
    """
    if prefix:
        full_message = f"{prefix} {message}\n"
    else:
        full_message = f"{message}\n"
    write_stdout(full_message)


def print_error(message: str, prefix: str = "❌") -> None:
    """Print an error message to stderr.

    Args:
        message: Error message to print
        prefix: Prefix for the error (default: "❌")
    """
    full_message = f"{prefix} {message}\n"
    write_stderr(full_message)
