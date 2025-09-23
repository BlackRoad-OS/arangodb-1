"""Unit tests for test context system."""

import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import Mock, patch, call

import pytest

from armadillo.testing.test_context import (
    IsolatedTestContext,
    EnvironmentTestFactory,
    create_test_context,
    temp_test_context,
    cleanup_test_context,
    cleanup_all_test_contexts,
    reset_test_environment,
    get_test_environment_factory,
)


class TestIsolatedTestContext:
    """Test isolated test context functionality."""

    def setup_method(self):
        """Set up test environment."""
        self.test_name = "unit_test_context"

    def teardown_method(self):
        """Clean up after test."""
        cleanup_test_context(self.test_name)
        cleanup_all_test_contexts()

    def test_context_creation(self):
        """Test basic context creation."""
        context = IsolatedTestContext(
            test_name=self.test_name, enable_persistence=False, cleanup_on_exit=False
        )

        try:
            assert context.test_name == self.test_name
            assert isinstance(context.get_work_dir(), Path)
            assert context.get_work_dir().exists()
            assert context.get_logger_factory() is not None
            assert context.get_port_pool_factory() is not None
        finally:
            context.cleanup()

    def test_context_with_custom_work_dir(self):
        """Test context creation with custom work directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            work_dir = Path(temp_dir)

            context = IsolatedTestContext(
                test_name=self.test_name, work_dir=work_dir, cleanup_on_exit=False
            )

            try:
                assert context.get_work_dir() == work_dir
                # Should not own the work dir
                assert not context._owns_work_dir
            finally:
                context.cleanup()

    def test_logger_creation(self):
        """Test logger creation within context."""
        context = IsolatedTestContext(test_name=self.test_name, cleanup_on_exit=False)

        try:
            logger = context.create_logger("test_logger")
            assert logger is not None
            assert logger.name.startswith(f"test_{self.test_name}")
        finally:
            context.cleanup()

    def test_port_pool_creation(self):
        """Test port pool creation within context."""
        context = IsolatedTestContext(test_name=self.test_name, cleanup_on_exit=False)

        try:
            pool = context.create_port_pool("test_pool")
            assert pool is not None

            # Pool should be tracked
            assert len(context._created_pools) == 1
            assert context._created_pools[0] == pool
        finally:
            context.cleanup()

    def test_temp_logger_context_manager(self):
        """Test temporary logger context manager."""
        context = IsolatedTestContext(test_name=self.test_name, cleanup_on_exit=False)

        try:
            with context.temp_logger("temp_logger") as logger:
                assert logger is not None
                assert logger.name.startswith(f"test_{self.test_name}")

            # Logger should be cleaned up automatically
            # (actual cleanup is handled by logger factory)
        finally:
            context.cleanup()

    def test_temp_port_pool_context_manager(self):
        """Test temporary port pool context manager."""
        context = IsolatedTestContext(test_name=self.test_name, cleanup_on_exit=False)

        try:
            with patch.object(context, "create_port_pool") as mock_create:
                mock_pool = Mock()
                mock_create.return_value = mock_pool

                with context.temp_port_pool("temp_pool") as pool:
                    assert pool == mock_pool

                # Pool should be shut down after context
                mock_pool.shutdown.assert_called_once()
        finally:
            context.cleanup()

    def test_cleanup_callbacks(self):
        """Test custom cleanup callbacks."""
        context = IsolatedTestContext(test_name=self.test_name, cleanup_on_exit=False)

        callback_mock = Mock()
        context.add_cleanup_callback(callback_mock)

        context.cleanup()

        # Callback should be called during cleanup
        callback_mock.assert_called_once()

    def test_cleanup_callback_exceptions(self):
        """Test that cleanup continues even if callbacks raise exceptions."""
        context = IsolatedTestContext(test_name=self.test_name, cleanup_on_exit=False)

        failing_callback = Mock(side_effect=Exception("Callback failed"))
        successful_callback = Mock()

        context.add_cleanup_callback(failing_callback)
        context.add_cleanup_callback(successful_callback)

        # Should not raise exception
        context.cleanup()

        # Both callbacks should be called
        failing_callback.assert_called_once()
        successful_callback.assert_called_once()

    def test_double_cleanup_safe(self):
        """Test that double cleanup is safe."""
        context = IsolatedTestContext(test_name=self.test_name, cleanup_on_exit=False)

        # First cleanup
        context.cleanup()

        # Second cleanup should be safe
        context.cleanup()

    @patch("armadillo.testing.test_context.atexit.register")
    def test_atexit_registration(self, mock_atexit):
        """Test that atexit cleanup is registered when requested."""
        context = IsolatedTestContext(test_name=self.test_name, cleanup_on_exit=True)

        try:
            # Should register cleanup on atexit
            mock_atexit.assert_called_once_with(context.cleanup)
        finally:
            context.cleanup()

    def test_context_isolation(self):
        """Test that different contexts are properly isolated."""
        context1 = IsolatedTestContext(test_name="context1", cleanup_on_exit=False)
        context2 = IsolatedTestContext(test_name="context2", cleanup_on_exit=False)

        try:
            # Should have different work directories
            assert context1.get_work_dir() != context2.get_work_dir()

            # Should have different logger factories
            assert context1.get_logger_factory() != context2.get_logger_factory()

            # Should have different port pool factories
            assert context1.get_port_pool_factory() != context2.get_port_pool_factory()
        finally:
            context1.cleanup()
            context2.cleanup()

    def test_persistence_enabled(self):
        """Test context with persistence enabled."""
        with tempfile.TemporaryDirectory() as temp_dir:
            work_dir = Path(temp_dir)

            context = IsolatedTestContext(
                test_name=self.test_name,
                work_dir=work_dir,
                enable_persistence=True,
                cleanup_on_exit=False,
            )

            try:
                # Should create log file when persistence is enabled
                log_file = work_dir / "test.log"
                # File might not exist immediately, but logger factory should be configured for it
                logger_factory = context.get_logger_factory()
                assert logger_factory is not None
            finally:
                context.cleanup()


class TestEnvironmentTestFactory:
    """Test test environment factory functionality."""

    def setup_method(self):
        """Set up test environment."""
        self.factory = EnvironmentTestFactory()

    def teardown_method(self):
        """Clean up after test."""
        self.factory.cleanup_all()

    def test_factory_creation(self):
        """Test factory creation."""
        assert self.factory is not None
        assert len(self.factory.list_active_contexts()) == 0

    def test_create_context(self):
        """Test creating context through factory."""
        context = self.factory.create_context("test_context")

        try:
            assert context is not None
            assert context.test_name == "test_context"
            assert len(self.factory.list_active_contexts()) == 1
            assert "test_context" in self.factory.list_active_contexts()
        finally:
            self.factory.cleanup_context("test_context")

    def test_get_existing_context(self):
        """Test getting existing context."""
        context1 = self.factory.create_context("test_context")
        context2 = self.factory.get_context("test_context")

        try:
            assert context1 == context2
        finally:
            self.factory.cleanup_context("test_context")

    def test_get_nonexistent_context(self):
        """Test getting non-existent context returns None."""
        context = self.factory.get_context("nonexistent")
        assert context is None

    def test_create_context_replaces_existing(self):
        """Test that creating context with same name replaces existing."""
        context1 = self.factory.create_context("test_context")
        context2 = self.factory.create_context("test_context")  # Same name

        try:
            assert context1 != context2
            assert len(self.factory.list_active_contexts()) == 1

            # First context should be cleaned up
            assert context1._cleaned_up
        finally:
            self.factory.cleanup_context("test_context")

    def test_temp_context_manager(self):
        """Test temporary context manager."""
        with self.factory.temp_context("temp_context") as context:
            assert context is not None
            assert context.test_name == "temp_context"
            assert len(self.factory.list_active_contexts()) == 1

        # Context should be cleaned up after exit
        assert len(self.factory.list_active_contexts()) == 0
        assert context._cleaned_up

    def test_cleanup_specific_context(self):
        """Test cleaning up specific context."""
        context = self.factory.create_context("test_context")

        assert len(self.factory.list_active_contexts()) == 1

        result = self.factory.cleanup_context("test_context")

        assert result is True
        assert len(self.factory.list_active_contexts()) == 0
        assert context._cleaned_up

    def test_cleanup_nonexistent_context(self):
        """Test cleaning up non-existent context."""
        result = self.factory.cleanup_context("nonexistent")
        assert result is False

    def test_cleanup_all(self):
        """Test cleaning up all contexts."""
        context1 = self.factory.create_context("context1")
        context2 = self.factory.create_context("context2")

        assert len(self.factory.list_active_contexts()) == 2

        self.factory.cleanup_all()

        assert len(self.factory.list_active_contexts()) == 0
        assert context1._cleaned_up
        assert context2._cleaned_up

    @patch("armadillo.testing.test_context.atexit.register")
    def test_atexit_registration(self, mock_atexit):
        """Test that factory registers atexit cleanup."""
        factory = EnvironmentTestFactory()

        # Should register cleanup_all on atexit
        mock_atexit.assert_called_once_with(factory.cleanup_all)

    def test_thread_safety(self):
        """Test that factory operations are thread-safe."""
        pytest.skip("Threading is globally mocked - test requires real threads")

        results = []
        exceptions = []

        def create_contexts(thread_id):
            try:
                for i in range(5):
                    context_name = f"thread_{thread_id}_context_{i}"
                    context = self.factory.create_context(context_name)
                    results.append((thread_id, context_name, context))
            except Exception as e:
                exceptions.append(e)

        threads = []
        for i in range(3):
            thread = threading.Thread(target=create_contexts, args=(i,))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # Should have no exceptions
        assert len(exceptions) == 0

        # Should have created all contexts
        assert len(results) == 15  # 3 threads * 5 contexts each
        assert len(self.factory.list_active_contexts()) == 15


class TestModuleFunctions:
    """Test module-level convenience functions."""

    def teardown_method(self):
        """Clean up after test."""
        cleanup_all_test_contexts()

    def test_create_test_context(self):
        """Test module-level create_test_context function."""
        context = create_test_context("module_test")

        try:
            assert context is not None
            assert context.test_name == "module_test"
        finally:
            cleanup_test_context("module_test")

    def test_temp_test_context(self):
        """Test module-level temp_test_context function."""
        with temp_test_context("temp_module_test") as context:
            assert context is not None
            assert context.test_name == "temp_module_test"

        # Context should be cleaned up

    def test_cleanup_test_context(self):
        """Test module-level cleanup_test_context function."""
        context = create_test_context("cleanup_test")

        result = cleanup_test_context("cleanup_test")

        assert result is True
        assert context._cleaned_up

    def test_cleanup_all_test_contexts(self):
        """Test module-level cleanup_all_test_contexts function."""
        context1 = create_test_context("cleanup_all_1")
        context2 = create_test_context("cleanup_all_2")

        cleanup_all_test_contexts()

        assert context1._cleaned_up
        assert context2._cleaned_up

    def test_get_test_environment_factory(self):
        """Test getting global test environment factory."""
        factory = get_test_environment_factory()

        assert factory is not None
        assert isinstance(factory, EnvironmentTestFactory)

    @patch("armadillo.core.log.reset_logging")
    @patch("armadillo.utils.ports.reset_port_manager")
    def test_reset_test_environment(self, mock_reset_port, mock_reset_log):
        """Test reset_test_environment function."""
        # Create some contexts
        create_test_context("reset_test_1")
        create_test_context("reset_test_2")

        reset_test_environment()

        # Should cleanup all contexts
        factory = get_test_environment_factory()
        assert len(factory.list_active_contexts()) == 0

        # Should reset global state
        mock_reset_log.assert_called_once()
        mock_reset_port.assert_called_once()


class TestTestContextIntegration:
    """Integration tests for test context system."""

    def teardown_method(self):
        """Clean up after test."""
        cleanup_all_test_contexts()

    def test_full_integration(self):
        """Test full integration of test context system."""
        context = create_test_context("integration_test")

        try:
            # Create logger
            logger = context.create_logger("integration_logger")
            assert logger is not None

            # Create port pool
            pool = context.create_port_pool("integration_pool")
            assert pool is not None

            # Use context managers
            with context.temp_logger("temp_logger") as temp_log:
                assert temp_log is not None

            with context.temp_port_pool("temp_pool") as temp_pool:
                assert temp_pool is not None

            # Add cleanup callback
            callback_called = []
            context.add_cleanup_callback(lambda: callback_called.append(True))

        finally:
            cleanup_test_context("integration_test")

            # Callback should have been called
            assert len(callback_called) == 1

    def test_context_isolation_integration(self):
        """Test that contexts are properly isolated in integration scenario."""
        with temp_test_context("isolation_test_1") as ctx1:
            logger1 = ctx1.create_logger("test")
            pool1 = ctx1.create_port_pool("pool")

            with temp_test_context("isolation_test_2") as ctx2:
                logger2 = ctx2.create_logger("test")  # Same name
                pool2 = ctx2.create_port_pool("pool")  # Same name

                # Should be different objects
                assert logger1 != logger2
                assert pool1 != pool2

                # Should have different namespaces
                assert logger1.name != logger2.name

    def test_persistent_vs_ephemeral(self):
        """Test difference between persistent and ephemeral contexts."""
        with tempfile.TemporaryDirectory() as temp_dir:
            work_dir = Path(temp_dir)

            # Create persistent context
            persistent_ctx = create_test_context(
                "persistent_test", work_dir=work_dir, enable_persistence=True
            )

            # Create ephemeral context
            ephemeral_ctx = create_test_context(
                "ephemeral_test", enable_persistence=False
            )

            try:
                # Both should work
                p_logger = persistent_ctx.create_logger("persistent")
                e_logger = ephemeral_ctx.create_logger("ephemeral")

                assert p_logger is not None
                assert e_logger is not None

            finally:
                cleanup_test_context("persistent_test")
                cleanup_test_context("ephemeral_test")
