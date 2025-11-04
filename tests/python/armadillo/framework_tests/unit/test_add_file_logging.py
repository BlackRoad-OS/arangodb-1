"""Test add_file_logging functionality."""

import logging
import tempfile
from pathlib import Path

import pytest

from armadillo.core.log import (
    configure_logging,
    add_file_logging,
    get_logger,
    reset_logging,
)


@pytest.fixture
def clean_logging():
    """Reset logging before and after each test."""
    reset_logging()
    yield
    reset_logging()


@pytest.fixture
def temp_log_file():
    """Create a temporary log file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        log_path = Path(f.name)
    yield log_path
    # Cleanup
    if log_path.exists():
        log_path.unlink()


def test_add_file_logging_after_initial_config(clean_logging, temp_log_file):
    """Test that file logging can be added after initial configuration."""
    # Initial configuration (console only)
    configure_logging(enable_console=False, enable_json=False)

    # Get a logger and log something
    logger1 = get_logger("test.initial")
    logger1.info("Before file logging")

    # Add file logging
    add_file_logging(temp_log_file, level=logging.DEBUG)

    # Log after file logging is enabled
    logger1.info("After file logging")

    # Create a new logger after file logging is enabled
    logger2 = get_logger("test.new")
    logger2.debug("New logger message")

    # Flush handlers
    for handler in logger1.handlers:
        handler.flush()
    for handler in logger2.handlers:
        handler.flush()

    # Read the log file
    log_content = temp_log_file.read_text()

    # Should contain messages from after file logging was enabled
    assert "After file logging" in log_content
    assert "New logger message" in log_content
    # Should NOT contain message from before file logging
    assert "Before file logging" not in log_content


def test_add_file_logging_creates_parent_directory(clean_logging):
    """Test that add_file_logging creates parent directories."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = Path(tmpdir) / "subdir" / "nested" / "test.log"
        assert not log_file.parent.exists()

        # Configure logging first
        configure_logging(enable_console=False, enable_json=False)

        # Add file logging - should create parent directories
        add_file_logging(log_file)

        # Verify directory was created
        assert log_file.parent.exists()

        # Log something
        logger = get_logger("test.nested")
        logger.info("Test message")

        # Flush handler
        for handler in logger.handlers:
            handler.flush()

        # Verify file was created and contains the message
        assert log_file.exists()
        assert "Test message" in log_file.read_text()


def test_add_file_logging_respects_level(clean_logging, temp_log_file):
    """Test that file handler respects the specified log level."""
    configure_logging(enable_console=False, enable_json=False)

    # Add file logging with INFO level
    add_file_logging(temp_log_file, level=logging.INFO)

    logger = get_logger("test.level")
    logger.debug("Debug message")  # Should NOT appear
    logger.info("Info message")  # Should appear
    logger.warning("Warning message")  # Should appear

    # Flush handlers
    for handler in logger.handlers:
        handler.flush()

    log_content = temp_log_file.read_text()

    # Should contain INFO and WARNING but not DEBUG
    assert "Debug message" not in log_content
    assert "Info message" in log_content
    assert "Warning message" in log_content


def test_add_file_logging_with_context(clean_logging, temp_log_file):
    """Test that file logging includes context information."""
    from armadillo.core.log import set_log_context

    configure_logging(enable_console=False, enable_json=False)
    add_file_logging(temp_log_file, level=logging.DEBUG)

    # Set context (using proper context field names)
    set_log_context(test_name="test_example", server_id="server-1")

    logger = get_logger("test.context")
    logger.info("Message with context")

    # Flush handlers
    for handler in logger.handlers:
        handler.flush()

    log_content = temp_log_file.read_text()

    # Should contain the message
    assert "Message with context" in log_content
    # Should contain JSON fields section
    assert "fields" in log_content
    # Log content should be valid JSON with structured data
    assert "global.test.context" in log_content  # logger name
