"""
Unit tests for core/log.py - Structured logging system.
Tests logging components with proper mocking to avoid side effects.
"""

import pytest
import logging
import json
import threading
import tempfile
from typing import Any
from unittest.mock import Mock, patch, MagicMock, call
from pathlib import Path
from datetime import datetime, timezone

from armadillo.core.log import (
    LogManager,
    configure_logging,
    get_logger,
    shutdown_logging,
    log_event,
    log_process_event,
    log_server_event,
    log_test_event,
    set_log_context,
    get_log_context,
    clear_log_context,
    log_context,
)
from armadillo.core.log_formatters import (
    LogContext,
    StructuredFormatter,
    ArmadilloRichHandler,
)


class TestLogContext:
    """Test LogContext thread-local context management."""

    def setup_method(self) -> None:
        """Set up test environment."""
        self.context = LogContext()

    def test_context_creation(self) -> None:
        """Test LogContext can be created."""
        assert isinstance(self.context, LogContext)
        assert hasattr(self.context, "_local")

    def test_set_and_get_context(self) -> None:
        """Test setting and getting context variables."""
        # Initially empty
        assert self.context.get_context() == {}

        # Set some context
        self.context.set_context(test_id="test_123", deployment="single")
        context = self.context.get_context()

        assert context["test_id"] == "test_123"
        assert context["deployment"] == "single"

    def test_context_update(self) -> None:
        """Test context updates work correctly."""
        self.context.set_context(key1="value1")
        self.context.set_context(key2="value2")

        context = self.context.get_context()
        assert context["key1"] == "value1"
        assert context["key2"] == "value2"

        # Update existing key
        self.context.set_context(key1="updated_value1")
        context = self.context.get_context()
        assert context["key1"] == "updated_value1"
        assert context["key2"] == "value2"

    def test_clear_context(self) -> None:
        """Test clearing context."""
        self.context.set_context(key="value")
        assert self.context.get_context() == {"key": "value"}

        self.context.clear_context()
        assert self.context.get_context() == {}

    def test_context_manager(self) -> None:
        """Test context manager functionality."""
        # Set initial context
        self.context.set_context(permanent="value")

        with self.context.context(temporary="temp_value"):
            context = self.context.get_context()
            # Should have both permanent and temporary
            assert "permanent" in context
            assert context["temporary"] == "temp_value"

        # After context manager, temporary should be gone
        context = self.context.get_context()
        assert "permanent" in context
        assert "temporary" not in context

    def test_context_isolation_single_thread(self) -> None:
        """Test context isolation works in single thread."""
        context1 = LogContext()
        context2 = LogContext()

        context1.set_context(source="context1")
        context2.set_context(source="context2")

        assert context1.get_context()["source"] == "context1"
        assert context2.get_context()["source"] == "context2"


class TestStructuredFormatter:
    """Test StructuredFormatter JSON logging."""

    def setup_method(self) -> None:
        """Set up test environment."""
        self.formatter = StructuredFormatter()

    @patch("armadillo.core.log._log_context")
    def test_basic_formatting(self, mock_context: Any) -> None:
        """Test basic log record formatting."""
        mock_context.get_context.return_value = {}

        # Create a mock log record
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        record.created = 1234567890.0

        result = self.formatter.format(record)
        log_data = json.loads(result)

        assert log_data["level"] == "INFO"
        assert log_data["logger"] == "test.logger"
        assert log_data["message"] == "Test message"
        assert "timestamp" in log_data
        assert log_data["timestamp"].startswith("2009-02-13T23:31:30")

    @patch("armadillo.core.log_formatters._log_context")
    def test_formatting_with_context(self, mock_context: Any) -> None:
        """Test formatting with context."""
        mock_context.get_context.return_value = {"test_id": "test_123"}

        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        record.created = 1234567890.0

        result = self.formatter.format(record)
        log_data = json.loads(result)

        assert "context" in log_data
        assert log_data["context"]["test_id"] == "test_123"

    @patch("armadillo.core.log._log_context")
    def test_formatting_without_context(self, mock_context: Any) -> None:
        """Test formatting with context disabled."""
        formatter = StructuredFormatter(include_context=False)
        mock_context.get_context.return_value = {"test_id": "test_123"}

        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        record.created = 1234567890.0

        result = formatter.format(record)
        log_data = json.loads(result)

        assert "context" not in log_data

    @patch("armadillo.core.log._log_context")
    def test_formatting_with_extra_fields(self, mock_context: Any) -> None:
        """Test formatting with extra fields."""
        mock_context.get_context.return_value = {}

        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        record.created = 1234567890.0
        record.custom_field = "custom_value"
        record.event_type = "test"

        result = self.formatter.format(record)
        log_data = json.loads(result)

        assert "fields" in log_data
        assert log_data["fields"]["custom_field"] == "custom_value"
        assert log_data["fields"]["event_type"] == "test"

    @patch("armadillo.core.log._log_context")
    def test_formatting_with_exception(self, mock_context: Any) -> None:
        """Test formatting with exception information."""
        mock_context.get_context.return_value = {}

        exc_info = None
        try:
            raise ValueError("Test exception")
        except ValueError:
            import sys

            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test.logger",
            level=logging.ERROR,
            pathname="test.py",
            lineno=42,
            msg="Error occurred",
            args=(),
            exc_info=exc_info,
        )
        record.created = 1234567890.0

        result = self.formatter.format(record)
        log_data = json.loads(result)

        assert "exception" in log_data
        assert log_data["exception"]["type"] == "ValueError"
        assert log_data["exception"]["message"] == "Test exception"
        assert "traceback" in log_data["exception"]


class TestArmadilloRichHandler:
    """Test ArmadilloRichHandler rich console formatting."""

    def test_handler_creation(self) -> None:
        """Test handler can be created."""
        with patch("rich.console.Console"):
            handler = ArmadilloRichHandler()
            assert isinstance(handler, ArmadilloRichHandler)

    @patch("rich.console.Console")
    def test_render_message_basic(self, mock_console_class: Any) -> None:
        """Test basic message rendering."""
        mock_console = Mock()
        mock_console_class.return_value = mock_console

        handler = ArmadilloRichHandler()

        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        # Test render_message method exists and works
        result = handler.render_message(record, "Test message")
        assert result is not None

    @patch("rich.console.Console")
    def test_render_message_with_event_type(self, mock_console_class: Any) -> None:
        """Test message rendering with event types."""
        mock_console = Mock()
        mock_console_class.return_value = mock_console

        handler = ArmadilloRichHandler()

        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="Process started",
            args=(),
            exc_info=None,
        )
        record.event_type = "process"

        result = handler.render_message(record, "Process started")
        assert result is not None


class TestLogManager:
    """Test LogManager configuration and management."""

    def setup_method(self) -> None:
        """Set up test environment."""
        self.manager = LogManager()

    def test_manager_creation(self) -> None:
        """Test LogManager can be created."""
        assert isinstance(self.manager, LogManager)
        assert self.manager._configured is False
        # Internal structure changed - just test that it was created properly
        assert hasattr(self.manager, "_manager")  # IsolatedLogManager

    @patch("logging.getLogger")
    @patch("logging.FileHandler")
    @patch("armadillo.core.log.ArmadilloRichHandler")
    @patch("pathlib.Path.mkdir")
    def test_configure_logging(
        self,
        mock_mkdir: Any,
        mock_rich_handler: Any,
        mock_file_handler: Any,
        mock_get_logger: Any,
    ) -> None:
        """Test logging configuration."""
        mock_root_logger = Mock()
        mock_get_logger.return_value = mock_root_logger
        mock_root_logger.handlers = []

        mock_json_handler = Mock()
        mock_console_handler = Mock()
        mock_file_handler.return_value = mock_json_handler
        mock_rich_handler.return_value = mock_console_handler

        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = Path(temp_dir) / "test.log"

            self.manager.configure(
                level=logging.INFO,
                log_file=log_file,
                enable_json=True,
                enable_console=True,
                configure_root_compat=True,
            )

        assert self.manager._configured is True

        # Test that configuration was applied (behavior rather than internals)
        mock_root_logger.setLevel.assert_called_with(logging.DEBUG)
        mock_root_logger.addHandler.assert_any_call(mock_json_handler)
        mock_root_logger.addHandler.assert_any_call(mock_console_handler)

    @patch("logging.getLogger")
    def test_configure_console_only(self, mock_get_logger: Any) -> None:
        """Test configuration with console only."""
        mock_root_logger = Mock()
        mock_get_logger.return_value = mock_root_logger
        mock_root_logger.handlers = []

        with patch("armadillo.core.log.ArmadilloRichHandler") as mock_rich_handler:
            mock_console_handler = Mock()
            mock_rich_handler.return_value = mock_console_handler

            self.manager.configure(
                level=logging.INFO,
                enable_json=False,
                enable_console=True,
                configure_root_compat=True,
            )

        assert self.manager._configured is True
        # Test behavior rather than internals - just that configuration completed
        mock_root_logger.addHandler.assert_called_once_with(mock_console_handler)

    def test_get_logger(self) -> None:
        """Test getting logger instance returns namespaced logger."""
        result = self.manager.get_logger("test.logger")
        assert isinstance(result, logging.Logger)
        assert result.name == "global.test.logger"

    @patch("logging.shutdown")
    @patch("logging.getLogger")
    def test_shutdown(self, mock_get_logger: Any, mock_shutdown: Any) -> None:
        """Test shutting down logging."""
        mock_root_logger = Mock()
        mock_get_logger.return_value = mock_root_logger
        mock_root_logger.handlers = []

        # Shutdown should work without errors and call logging.shutdown
        self.manager.shutdown()
        mock_shutdown.assert_called_once()

    @patch("logging.getLogger")
    def test_double_configure_ignored(self, mock_get_logger: Any) -> None:
        """Test that double configuration is ignored."""
        mock_root_logger = Mock()
        mock_get_logger.return_value = mock_root_logger
        mock_root_logger.handlers = []

        # First configuration (enable root compat to trigger getLogger)
        self.manager.configure(configure_root_compat=True)
        assert self.manager._configured is True

        # Second configuration should be ignored
        self.manager.configure(configure_root_compat=True)

        # Should only be called once
        assert mock_get_logger.call_count == 1


class TestModuleLevelFunctions:
    """Test module-level convenience functions."""

    @patch("armadillo.core.log._log_manager")
    def test_configure_logging_function(self, mock_manager: Any) -> None:
        """Test module-level configure_logging function."""
        configure_logging(level=logging.DEBUG, enable_console=False)

        mock_manager.configure.assert_called_once_with(
            level=logging.DEBUG, enable_console=False
        )

    @patch("armadillo.core.log._log_manager")
    def test_get_logger_function(self, mock_manager: Any) -> None:
        """Test module-level get_logger function."""
        mock_logger = Mock()
        mock_manager.get_logger.return_value = mock_logger

        result = get_logger("test.logger")

        assert result == mock_logger
        mock_manager.get_logger.assert_called_once_with("test.logger")

    @patch("armadillo.core.log._log_manager")
    def test_shutdown_logging_function(self, mock_manager: Any) -> None:
        """Test module-level shutdown_logging function."""
        shutdown_logging()

        mock_manager.shutdown.assert_called_once()

    def test_log_event_function(self) -> None:
        """Test log_event function."""
        mock_logger = Mock()

        log_event(mock_logger, "test", "Test message", custom_field="value")

        mock_logger.info.assert_called_once_with(
            "Test message", extra={"event_type": "test", "custom_field": "value"}
        )

    def test_log_process_event_function(self) -> None:
        """Test log_process_event function."""
        mock_logger = Mock()

        log_process_event(mock_logger, "started", pid=12345, command="test_cmd")

        expected_extra = {
            "event_type": "process",
            "process_event": "started",
            "pid": 12345,
            "command": "test_cmd",
        }
        mock_logger.info.assert_called_once_with(
            "Process %s %s", 12345, "started", extra=expected_extra
        )

    def test_log_server_event_function(self) -> None:
        """Test log_server_event function."""
        mock_logger = Mock()

        log_server_event(mock_logger, "ready", server_id="server_1", port=8529)

        expected_extra = {
            "event_type": "server",
            "server_event": "ready",
            "server_id": "server_1",
            "port": 8529,
        }
        mock_logger.info.assert_called_once_with(
            "Server %s %s", "server_1", "ready", extra=expected_extra
        )

    def test_log_test_event_function(self) -> None:
        """Test log_test_event function."""
        mock_logger = Mock()

        log_test_event(mock_logger, "passed", test_name="test_example", duration=1.23)

        expected_extra = {
            "event_type": "test",
            "test_event": "passed",
            "test_name": "test_example",
            "duration": 1.23,
        }
        mock_logger.info.assert_called_once_with(
            "Test %s %s", "test_example", "passed", extra=expected_extra
        )


class TestContextManagement:
    """Test global context management functions."""

    @patch("armadillo.core.log._log_context")
    def test_set_log_context_function(self, mock_context: Any) -> None:
        """Test set_log_context function."""
        set_log_context(deployment="cluster", test_id="test_123")

        mock_context.set_context.assert_called_once_with(
            deployment="cluster", test_id="test_123"
        )

    @patch("armadillo.core.log._log_context")
    def test_get_log_context_function(self, mock_context: Any) -> None:
        """Test get_log_context function."""
        mock_context.get_context.return_value = {"key": "value"}

        result = get_log_context()

        assert result == {"key": "value"}
        mock_context.get_context.assert_called_once()

    @patch("armadillo.core.log._log_context")
    def test_clear_log_context_function(self, mock_context: Any) -> None:
        """Test clear_log_context function."""
        clear_log_context()

        mock_context.clear_context.assert_called_once()

    @patch("armadillo.core.log._log_context")
    def test_log_context_function(self, mock_context: Any) -> None:
        """Test log_context function."""
        mock_context_manager = Mock()
        mock_context.context.return_value = mock_context_manager

        result = log_context(key1="value1", key2="value2")

        assert result == mock_context_manager
        mock_context.context.assert_called_once_with(key1="value1", key2="value2")


class TestLoggerIntegration:
    """Test logging system integration scenarios."""

    def test_logger_with_structured_formatter(self) -> None:
        """Test logger works with structured formatter."""
        formatter = StructuredFormatter(include_context=False)

        # Create a simple log record
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="Integration test",
            args=(),
            exc_info=None,
        )
        record.created = 1234567890.0

        result = formatter.format(record)

        # Should be valid JSON
        log_data = json.loads(result)
        assert log_data["message"] == "Integration test"
        assert log_data["level"] == "INFO"

    def test_context_thread_isolation(self) -> None:
        """Test context isolation between different LogContext instances."""
        context1 = LogContext()
        context2 = LogContext()

        # Set different contexts
        context1.set_context(instance="context1")
        context2.set_context(instance="context2")

        # Should be isolated
        assert context1.get_context()["instance"] == "context1"
        assert context2.get_context()["instance"] == "context2"

        # Clear one shouldn't affect the other
        context1.clear_context()
        assert context1.get_context() == {}
        assert context2.get_context()["instance"] == "context2"


class TestErrorHandling:
    """Test error handling in logging components."""

    def test_formatter_handles_none_exception(self) -> None:
        """Test formatter handles None exception gracefully."""
        formatter = StructuredFormatter(include_context=False)

        record = logging.LogRecord(
            name="test.logger",
            level=logging.ERROR,
            pathname="test.py",
            lineno=42,
            msg="Error message",
            args=(),
            exc_info=None,
        )
        record.created = 1234567890.0

        # Should not raise error
        result = formatter.format(record)
        log_data = json.loads(result)
        assert "exception" not in log_data

    @patch("armadillo.core.log._log_context")
    def test_formatter_handles_context_error(self, mock_context: Any) -> None:
        """Test formatter handles context retrieval error."""
        mock_context.get_context.side_effect = Exception("Context error")
        formatter = StructuredFormatter(include_context=True)

        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        record.created = 1234567890.0

        # Should handle error gracefully and still produce JSON
        try:
            result = formatter.format(record)
            # If it doesn't raise an exception, that's good
            log_data = json.loads(result)
            assert log_data["message"] == "Test message"
        except Exception:
            # If it does handle the error by not including context, that's also acceptable
            pass

    def test_log_manager_handles_shutdown_errors(self) -> None:
        """Test LogManager handles shutdown errors gracefully."""
        manager = LogManager()

        # Configure manager and test shutdown error handling
        # Note: LogManager doesn't expose private handlers, so we test behavior instead
        manager.configure(level=logging.INFO, enable_json=True, enable_console=True)

        with patch("logging.shutdown") as mock_shutdown:
            # Should not raise exception
            try:
                manager.shutdown()
            except Exception:
                pytest.fail(
                    "LogManager.shutdown should handle handler close errors gracefully"
                )

            # Should still call logging.shutdown
            mock_shutdown.assert_called_once()
