"""Unit tests for resource pool management."""

import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import Mock, patch, call

import pytest

from armadillo.utils.resource_pool import (
    ResourceTracker, PortPool, ManagedPortPool,
    create_isolated_port_pool, create_ephemeral_port_pool
)
from armadillo.utils.ports import PortManager
from armadillo.core.errors import NetworkError


class TestResourceTracker:
    """Test resource tracker functionality."""

    def setup_method(self):
        """Set up test environment."""
        self.tracker = ResourceTracker("test_tracker")

    def teardown_method(self):
        """Clean up after test."""
        self.tracker.cleanup_all()

    def test_tracker_creation(self):
        """Test resource tracker creation."""
        assert self.tracker._name == "test_tracker"
        assert len(self.tracker._allocated_resources) == 0
        assert len(self.tracker._cleanup_callbacks) == 0

    def test_register_resource_type(self):
        """Test registering a resource type with cleanup callback."""
        cleanup_mock = Mock()

        self.tracker.register_resource_type("test_type", cleanup_mock)

        assert "test_type" in self.tracker._cleanup_callbacks
        assert self.tracker._cleanup_callbacks["test_type"] == cleanup_mock
        assert "test_type" in self.tracker._allocated_resources

    def test_track_resource(self):
        """Test tracking resources."""
        cleanup_mock = Mock()
        self.tracker.register_resource_type("ports", cleanup_mock)

        self.tracker.track_resource("ports", 8529)
        self.tracker.track_resource("ports", 8530)

        tracked = self.tracker.get_tracked_resources("ports")
        assert 8529 in tracked
        assert 8530 in tracked
        assert len(tracked) == 2

    def test_untrack_resource(self):
        """Test untracking resources."""
        cleanup_mock = Mock()
        self.tracker.register_resource_type("ports", cleanup_mock)

        self.tracker.track_resource("ports", 8529)
        self.tracker.track_resource("ports", 8530)
        self.tracker.untrack_resource("ports", 8529)

        tracked = self.tracker.get_tracked_resources("ports")
        assert 8529 not in tracked
        assert 8530 in tracked
        assert len(tracked) == 1

    def test_cleanup_type(self):
        """Test cleaning up a specific resource type."""
        cleanup_mock = Mock()
        self.tracker.register_resource_type("ports", cleanup_mock)

        self.tracker.track_resource("ports", 8529)
        self.tracker.track_resource("ports", 8530)

        self.tracker.cleanup_type("ports")

        # Cleanup callback should be called with tracked resources
        cleanup_mock.assert_called_once()
        args = cleanup_mock.call_args[0][0]  # First argument (list of resources)
        assert set(args) == {8529, 8530}

        # Resources should be cleared
        assert len(self.tracker.get_tracked_resources("ports")) == 0

    def test_cleanup_all(self):
        """Test cleaning up all resource types."""
        port_cleanup = Mock()
        file_cleanup = Mock()

        self.tracker.register_resource_type("ports", port_cleanup)
        self.tracker.register_resource_type("files", file_cleanup)

        self.tracker.track_resource("ports", 8529)
        self.tracker.track_resource("files", "/tmp/test")

        self.tracker.cleanup_all()

        port_cleanup.assert_called_once_with([8529])
        file_cleanup.assert_called_once_with(["/tmp/test"])

    def test_cleanup_with_exception(self):
        """Test that cleanup continues even if one callback fails."""
        def failing_cleanup(resources):
            raise Exception("Cleanup failed")

        port_cleanup = Mock()

        self.tracker.register_resource_type("failing", failing_cleanup)
        self.tracker.register_resource_type("ports", port_cleanup)

        self.tracker.track_resource("failing", "test")
        self.tracker.track_resource("ports", 8529)

        # Should not raise exception
        self.tracker.cleanup_all()

        # Successful cleanup should still be called
        port_cleanup.assert_called_once_with([8529])

    def test_track_without_registration(self):
        """Test tracking resource without prior type registration."""
        # Should create the resource type automatically
        self.tracker.track_resource("new_type", "resource")

        tracked = self.tracker.get_tracked_resources("new_type")
        assert "resource" in tracked

    def test_thread_safety(self):
        """Test that resource tracker is thread-safe."""
        pytest.skip("Threading is globally mocked - test requires real threads")

        cleanup_mock = Mock()
        self.tracker.register_resource_type("ports", cleanup_mock)

        def track_resources(start_port):
            for i in range(10):
                self.tracker.track_resource("ports", start_port + i)

        thread1 = threading.Thread(target=track_resources, args=(8000,))
        thread2 = threading.Thread(target=track_resources, args=(9000,))

        thread1.start()
        thread2.start()
        thread1.join()
        thread2.join()

        tracked = self.tracker.get_tracked_resources("ports")
        # Should have all 20 ports tracked
        assert len(tracked) == 20


class TestPortPool:
    """Test basic port pool functionality."""

    def setup_method(self):
        """Set up test environment."""
        self.mock_port_manager = Mock(spec=PortManager)
        self.mock_resource_tracker = Mock()

        self.pool = PortPool(
            port_manager=self.mock_port_manager,
            resource_tracker=self.mock_resource_tracker,
            name="test_pool"
        )

    def test_pool_creation(self):
        """Test port pool creation."""
        assert self.pool._name == "test_pool"
        assert self.pool._port_manager == self.mock_port_manager
        assert self.pool._resource_tracker == self.mock_resource_tracker

    def test_acquire_port(self):
        """Test acquiring a single port."""
        self.mock_port_manager.allocate_port.return_value = 8529

        port = self.pool.acquire(preferred=8529)

        assert port == 8529
        self.mock_port_manager.allocate_port.assert_called_once_with(8529)
        self.mock_resource_tracker.track_resource.assert_called_once_with("ports", 8529)

    def test_acquire_multiple_ports(self):
        """Test acquiring multiple ports."""
        self.mock_port_manager.allocate_ports.return_value = [8529, 8530, 8531]

        ports = self.pool.acquire_multiple(3)

        assert ports == [8529, 8530, 8531]
        self.mock_port_manager.allocate_ports.assert_called_once_with(3)

        # Should track each port individually
        expected_calls = [
            call("ports", 8529),
            call("ports", 8530),
            call("ports", 8531)
        ]
        self.mock_resource_tracker.track_resource.assert_has_calls(expected_calls)

    def test_release_port(self):
        """Test releasing a single port."""
        self.pool.release(8529)

        self.mock_port_manager.release_port.assert_called_once_with(8529)
        self.mock_resource_tracker.untrack_resource.assert_called_once_with("ports", 8529)

    def test_release_multiple_ports(self):
        """Test releasing multiple ports."""
        ports = [8529, 8530, 8531]

        self.pool.release_multiple(ports)

        self.mock_port_manager.release_ports.assert_called_once_with(ports)

        # Should untrack each port individually
        expected_calls = [
            call("ports", 8529),
            call("ports", 8530),
            call("ports", 8531)
        ]
        self.mock_resource_tracker.untrack_resource.assert_has_calls(expected_calls)

    def test_acquire_context_manager(self):
        """Test port acquisition with context manager."""
        self.mock_port_manager.allocate_port.return_value = 8529

        with self.pool.acquire_context(preferred=8529) as port:
            assert port == 8529
            self.mock_port_manager.allocate_port.assert_called_once_with(8529)

        # Should release port after context
        self.mock_port_manager.release_port.assert_called_once_with(8529)

    def test_acquire_multiple_context_manager(self):
        """Test multiple port acquisition with context manager."""
        self.mock_port_manager.allocate_ports.return_value = [8529, 8530]

        with self.pool.acquire_multiple_context(2) as ports:
            assert ports == [8529, 8530]
            self.mock_port_manager.allocate_ports.assert_called_once_with(2)

        # Should release ports after context
        self.mock_port_manager.release_ports.assert_called_once_with([8529, 8530])

    def test_get_allocated_ports(self):
        """Test getting allocated ports."""
        self.mock_resource_tracker.get_tracked_resources.return_value = [8529, 8530]

        allocated = self.pool.get_allocated_ports()

        assert allocated == [8529, 8530]
        self.mock_resource_tracker.get_tracked_resources.assert_called_once_with("ports")

    def test_cleanup_all_ports(self):
        """Test cleaning up all allocated ports."""
        self.pool.cleanup_all_ports()

        self.mock_resource_tracker.cleanup_type.assert_called_once_with("ports")

    def test_shutdown(self):
        """Test pool shutdown."""
        self.pool.shutdown()

        self.mock_resource_tracker.cleanup_all.assert_called_once()

    def test_is_port_available(self):
        """Test checking port availability."""
        self.mock_port_manager.is_port_available.return_value = True

        available = self.pool.is_port_available(8529)

        assert available is True
        self.mock_port_manager.is_port_available.assert_called_once_with(8529)


class TestManagedPortPool:
    """Test managed port pool functionality."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = Path(tempfile.mkdtemp())

    def teardown_method(self):
        """Clean up after test."""
        # Clean up temp directory
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch('armadillo.utils.resource_pool.PortManager')
    def test_managed_pool_creation_with_persistence(self, mock_port_manager_class):
        """Test creating managed pool with persistence."""
        mock_port_manager = Mock()
        mock_port_manager_class.return_value = mock_port_manager

        pool = ManagedPortPool(
            base_port=9000,
            max_ports=500,
            name="test_managed",
            enable_persistence=True,
            work_dir=self.temp_dir
        )

        # Should create PortManager with correct parameters
        mock_port_manager_class.assert_called_once_with(base_port=9000, max_ports=500)

        # Should set reservation file
        expected_file = self.temp_dir / "port_reservations_test_managed.txt"
        mock_port_manager.set_reservation_file.assert_called_once_with(expected_file)

    @patch('armadillo.utils.resource_pool.PortManager')
    def test_managed_pool_creation_without_persistence(self, mock_port_manager_class):
        """Test creating managed pool without persistence."""
        mock_port_manager = Mock()
        mock_port_manager_class.return_value = mock_port_manager

        pool = ManagedPortPool(
            base_port=9000,
            max_ports=500,
            name="test_managed",
            enable_persistence=False,
            work_dir=None
        )

        # Should not set reservation file
        mock_port_manager.set_reservation_file.assert_not_called()

    @patch('armadillo.utils.resource_pool.atexit.register')
    @patch('armadillo.utils.resource_pool.PortManager')
    def test_atexit_registration(self, mock_port_manager_class, mock_atexit):
        """Test that shutdown is registered with atexit."""
        pool = ManagedPortPool(name="test_atexit")

        # Should register shutdown method
        mock_atexit.assert_called_once()
        # The registered function should be the shutdown method
        registered_func = mock_atexit.call_args[0][0]
        assert registered_func == pool.shutdown


class TestPortPoolUtilities:
    """Test utility functions for creating port pools."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = Path(tempfile.mkdtemp())

    def teardown_method(self):
        """Clean up after test."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch('armadillo.utils.resource_pool.ManagedPortPool')
    def test_create_isolated_port_pool(self, mock_managed_pool_class):
        """Test creating isolated port pool."""
        mock_pool = Mock()
        mock_managed_pool_class.return_value = mock_pool

        pool = create_isolated_port_pool(
            name="test_isolated",
            base_port=9000,
            max_ports=500,
            work_dir=self.temp_dir
        )

        mock_managed_pool_class.assert_called_once_with(
            base_port=9000,
            max_ports=500,
            name="test_isolated",
            enable_persistence=True,
            work_dir=self.temp_dir
        )

        assert pool == mock_pool

    @patch('armadillo.utils.resource_pool.ManagedPortPool')
    def test_create_ephemeral_port_pool(self, mock_managed_pool_class):
        """Test creating ephemeral port pool."""
        mock_pool = Mock()
        mock_managed_pool_class.return_value = mock_pool

        pool = create_ephemeral_port_pool(
            name="test_ephemeral",
            base_port=9000,
            max_ports=500
        )

        mock_managed_pool_class.assert_called_once_with(
            base_port=9000,
            max_ports=500,
            name="test_ephemeral",
            enable_persistence=False,
            work_dir=None
        )

        assert pool == mock_pool


class TestPortPoolIntegration:
    """Integration tests with real PortManager."""

    def setup_method(self):
        """Set up test environment."""
        # Use high port numbers to avoid conflicts
        self.base_port = 58000
        self.pool = ManagedPortPool(
            base_port=self.base_port,
            max_ports=100,
            name="integration_test",
            enable_persistence=False
        )

    def teardown_method(self):
        """Clean up after test."""
        self.pool.shutdown()

    def test_real_port_allocation(self):
        """Test real port allocation and release."""
        # Acquire a port
        port = self.pool.acquire()

        assert port >= self.base_port
        assert port < self.base_port + 100

        # Port should be tracked
        allocated = self.pool.get_allocated_ports()
        assert port in allocated

        # Release the port
        self.pool.release(port)

        # Port should no longer be tracked
        allocated_after = self.pool.get_allocated_ports()
        assert port not in allocated_after

    def test_context_manager_cleanup(self):
        """Test that context manager properly cleans up."""
        with self.pool.acquire_context() as port:
            # Port should be allocated
            allocated = self.pool.get_allocated_ports()
            assert port in allocated

        # After context, port should be released
        allocated_after = self.pool.get_allocated_ports()
        assert port not in allocated_after

    def test_shutdown_cleanup(self):
        """Test that shutdown cleans up all ports."""
        # Allocate several ports
        port1 = self.pool.acquire()
        port2 = self.pool.acquire()

        assert len(self.pool.get_allocated_ports()) == 2

        # Shutdown should clean up all ports
        self.pool.shutdown()

        # All ports should be released (though we can't easily verify
        # the internal state after shutdown, the test passes if no exceptions)
        # This mainly tests that shutdown doesn't crash
