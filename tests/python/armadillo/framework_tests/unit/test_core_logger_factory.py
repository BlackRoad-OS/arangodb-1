"""Unit tests for LoggerFactory and IsolatedLogManager."""

import tempfile
import logging
import threading
import time
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from armadillo.core.logger_factory import (
    IsolatedLogManager,
    StandardLoggerFactory,
)
from armadillo.core.log import (
    log_event,
    log_process_event,
    log_server_event,
    log_test_event,
)


class TestIsolatedLogManager:
    """Test isolated log manager functionality."""

    def setup_method(self):
        """Set up test environment."""
        self.manager = IsolatedLogManager("test")

    def teardown_method(self):
        """Clean up after test."""
        self.manager.shutdown()

    def test_basic_logger_creation(self):
        """Test basic logger creation with namespace isolation."""
        self.manager.configure(enable_json=False, enable_console=False)

        logger = self.manager.create_logger("test_logger")

        assert logger.name == "test.test_logger"
        assert logger.propagate is False
        assert logger.level == logging.DEBUG

    def test_namespace_isolation(self):
        """Test that different namespaces create isolated loggers."""
        manager1 = IsolatedLogManager("ns1")
        manager2 = IsolatedLogManager("ns2")

        try:
            manager1.configure(enable_json=False, enable_console=False)
            manager2.configure(enable_json=False, enable_console=False)

            logger1 = manager1.create_logger("same_name")
            logger2 = manager2.create_logger("same_name")

            assert logger1.name == "ns1.same_name"
            assert logger2.name == "ns2.same_name"
            assert logger1 is not logger2
        finally:
            manager1.shutdown()
            manager2.shutdown()

    def test_reconfiguration_allowed(self):
        """Test that reconfiguration is allowed for test isolation."""
        # First configuration
        self.manager.configure(
            level=logging.DEBUG, enable_json=False, enable_console=False
        )
        logger1 = self.manager.create_logger("test")

        # Reconfigure
        self.manager.configure(
            level=logging.INFO, enable_json=False, enable_console=False
        )
        logger2 = self.manager.create_logger("test2")

        # Should work without errors
        assert logger1.name == "test.test"
        assert logger2.name == "test.test2"

    def test_context_management(self):
        """Test context management functionality."""
        self.manager.configure(enable_json=False, enable_console=False)

        # Initially empty context
        assert self.manager.get_context() == {}

        # Set context
        self.manager.set_context(test_id="123", component="auth")
        context = self.manager.get_context()
        assert context["test_id"] == "123"
        assert context["component"] == "auth"

        # Clear context
        self.manager.clear_context()
        assert self.manager.get_context() == {}

    def test_context_manager(self):
        """Test context manager functionality."""
        self.manager.configure(enable_json=False, enable_console=False)

        self.manager.set_context(base="value")

        with self.manager.context(temp="context"):
            context = self.manager.get_context()
            assert context["base"] == "value"
            assert context["temp"] == "context"

        # Context should be restored
        context = self.manager.get_context()
        assert context["base"] == "value"
        assert "temp" not in context

    def test_thread_isolation(self):
        """Test that context is isolated between threads."""
        pytest.skip("Threading is globally mocked - test requires real threads")

        self.manager.configure(enable_json=False, enable_console=False)

        contexts = {}
        barrier = threading.Barrier(2)

        def thread_worker(thread_id):
            self.manager.set_context(thread_id=thread_id)
            barrier.wait()  # Synchronize
            time.sleep(0.01)  # Small delay
            contexts[thread_id] = self.manager.get_context()

        thread1 = threading.Thread(target=thread_worker, args=(1,))
        thread2 = threading.Thread(target=thread_worker, args=(2,))

        thread1.start()
        thread2.start()
        thread1.join()
        thread2.join()

        # Each thread should have its own context
        assert contexts[1]["thread_id"] == 1
        assert contexts[2]["thread_id"] == 2

    def test_json_file_logging(self):
        """Test JSON file logging configuration."""
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            log_file = Path(f.name)

        try:
            self.manager.configure(
                level=logging.INFO,
                log_file=log_file,
                enable_json=True,
                enable_console=False,
            )

            logger = self.manager.create_logger("json_test")
            logger.info("Test message")

            # Force flush
            self.manager.shutdown()

            # Check file was created and contains JSON
            assert log_file.exists()
            content = log_file.read_text()
            assert "Test message" in content
            assert '"level": "INFO"' in content or '"level":"INFO"' in content
        finally:
            if log_file.exists():
                log_file.unlink()

    def test_logger_caching(self):
        """Test that loggers are cached and reused."""
        self.manager.configure(enable_json=False, enable_console=False)

        logger1 = self.manager.create_logger("cached")
        logger2 = self.manager.create_logger("cached")

        assert logger1 is logger2

    def test_shutdown_cleanup(self):
        """Test that shutdown properly cleans up resources."""
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            log_file = Path(f.name)

        try:
            self.manager.configure(
                log_file=log_file, enable_json=True, enable_console=False
            )

            logger = self.manager.create_logger("cleanup_test")
            logger.info("Test message")

            # Shutdown should work without errors
            self.manager.shutdown()

            # Context should be cleared
            assert self.manager.get_context() == {}
        finally:
            if log_file.exists():
                log_file.unlink()


class TestStandardLoggerFactory:
    """Test standard logger factory implementation."""

    def setup_method(self):
        """Set up test environment."""
        self.factory = StandardLoggerFactory(
            namespace="factory_test", enable_json=False, enable_console=False
        )

    def teardown_method(self):
        """Clean up after test."""
        self.factory.shutdown()

    def test_logger_creation(self):
        """Test logger creation through factory."""
        logger = self.factory.create_logger("test")

        assert logger.name == "factory_test.test"
        assert logger.propagate is False

    def test_context_convenience_methods(self):
        """Test context management convenience methods."""
        # Set context
        self.factory.set_context(test="value")
        assert self.factory.get_context()["test"] == "value"

        # Context manager
        with self.factory.context(temp="ctx"):
            assert self.factory.get_context()["temp"] == "ctx"

        # Clear context
        self.factory.clear_context()
        assert self.factory.get_context() == {}

    def test_protocol_compliance(self):
        """Test that StandardLoggerFactory implements LoggerFactory protocol."""
        assert hasattr(self.factory, "create_logger")
        assert hasattr(self.factory, "shutdown")
        assert callable(self.factory.create_logger)
        assert callable(self.factory.shutdown)


class TestLoggingEventFunctions:
    """Test logging event utility functions."""

    def setup_method(self):
        """Set up test environment."""
        self.mock_logger = Mock()

    def test_log_event(self):
        """Test generic event logging."""
        log_event(self.mock_logger, "custom", "Test event", extra_field="value")

        self.mock_logger.info.assert_called_once_with(
            "Test event", extra={"event_type": "custom", "extra_field": "value"}
        )

    def test_log_process_event(self):
        """Test process event logging."""
        log_process_event(self.mock_logger, "started", pid=1234, command="test")

        expected_extra = {
            "event_type": "process",
            "process_event": "started",
            "pid": 1234,
            "command": "test",
        }
        self.mock_logger.info.assert_called_once_with(
            "Process %s %s", 1234, "started", extra=expected_extra
        )

    def test_log_process_event_without_pid(self):
        """Test process event logging without PID."""
        log_process_event(self.mock_logger, "failed")

        expected_extra = {"event_type": "process", "process_event": "failed"}
        self.mock_logger.info.assert_called_once_with(
            "Process %s %s", None, "failed", extra=expected_extra
        )

    def test_log_server_event(self):
        """Test server event logging."""
        log_server_event(self.mock_logger, "startup", server_id="srv_1", port=8529)

        expected_extra = {
            "event_type": "server",
            "server_event": "startup",
            "server_id": "srv_1",
            "port": 8529,
        }
        self.mock_logger.info.assert_called_once_with(
            "Server %s %s", "srv_1", "startup", extra=expected_extra
        )

    def test_log_server_event_without_id(self):
        """Test server event logging without server ID."""
        log_server_event(self.mock_logger, "shutdown")

        expected_extra = {"event_type": "server", "server_event": "shutdown"}
        self.mock_logger.info.assert_called_once_with(
            "Server %s %s", None, "shutdown", extra=expected_extra
        )

    def test_log_test_event(self):
        """Test test event logging."""
        log_test_event(
            self.mock_logger, "started", test_name="test_feature", suite="integration"
        )

        expected_extra = {
            "event_type": "test",
            "test_event": "started",
            "test_name": "test_feature",
            "suite": "integration",
        }
        self.mock_logger.info.assert_called_once_with(
            "Test %s %s", "test_feature", "started", extra=expected_extra
        )

    def test_log_test_event_without_name(self):
        """Test test event logging without test name."""
        log_test_event(self.mock_logger, "completed")

        expected_extra = {"event_type": "test", "test_event": "completed"}
        self.mock_logger.info.assert_called_once_with(
            "Test %s %s", None, "completed", extra=expected_extra
        )


class TestLoggerFactoryIsolation:
    """Test that different logger factories are properly isolated."""

    def test_multiple_factories_isolation(self):
        """Test that multiple factories don't interfere with each other."""
        factory1 = StandardLoggerFactory(
            namespace="test1", enable_json=False, enable_console=False
        )
        factory2 = StandardLoggerFactory(
            namespace="test2", enable_json=False, enable_console=False
        )

        try:
            # Set different contexts
            factory1.set_context(factory="one")
            factory2.set_context(factory="two")

            # Contexts should be isolated
            assert factory1.get_context()["factory"] == "one"
            assert factory2.get_context()["factory"] == "two"

            # Loggers should have different namespaces
            logger1 = factory1.create_logger("same")
            logger2 = factory2.create_logger("same")

            assert logger1.name == "test1.same"
            assert logger2.name == "test2.same"
            assert logger1 is not logger2
        finally:
            factory1.shutdown()
            factory2.shutdown()

    def test_factory_context_doesnt_leak_to_global(self):
        """Test that factory context doesn't leak to global context."""
        from armadillo.core.log import get_log_context, clear_log_context

        factory = StandardLoggerFactory(
            namespace="isolated", enable_json=False, enable_console=False
        )

        try:
            # Clear any existing global context
            clear_log_context()

            # Set factory context
            factory.set_context(isolated="value")

            # Global context should remain empty
            assert get_log_context() == {}

            # Factory context should be set
            assert factory.get_context()["isolated"] == "value"
        finally:
            factory.shutdown()
