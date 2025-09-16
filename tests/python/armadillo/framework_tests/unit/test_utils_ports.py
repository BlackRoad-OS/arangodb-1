"""
Unit tests for utils/ports.py - Port allocation and management utilities.
Tests port management with proper mocking to avoid actual network operations.
"""

import pytest
import tempfile
import threading
from unittest.mock import Mock, patch, MagicMock, call
from pathlib import Path

from armadillo.utils.ports import (
    PortManager, find_free_port, check_port_available, wait_for_port,
    get_port_manager, allocate_port, allocate_ports, release_port, release_ports,
    reset_port_manager
)
from armadillo.core.errors import NetworkError


class TestPortManager:
    """Test PortManager port allocation and management."""

    def setup_method(self):
        """Set up test environment."""
        self.manager = PortManager(base_port=9000, max_ports=100)

    def test_manager_creation(self):
        """Test PortManager can be created."""
        assert isinstance(self.manager, PortManager)
        assert self.manager.base_port == 9000
        assert self.manager.max_ports == 100
        assert isinstance(self.manager.reserved_ports, set)
        assert len(self.manager.reserved_ports) == 0

    def test_manager_with_defaults(self):
        """Test PortManager with default parameters."""
        manager = PortManager()
        assert manager.base_port == 8529
        assert manager.max_ports == 1000

    @patch('socket.socket')
    def test_allocate_port_basic(self, mock_socket_class):
        """Test basic port allocation."""
        mock_socket = MagicMock()
        mock_socket_class.return_value.__enter__.return_value = mock_socket
        mock_socket.bind.return_value = None  # Success

        port = self.manager.allocate_port()

        assert port == 9000  # First available port
        assert port in self.manager.reserved_ports
        mock_socket.bind.assert_called_with(('localhost', 9000))

    @patch('socket.socket')
    def test_allocate_preferred_port(self, mock_socket_class):
        """Test allocating preferred port."""
        mock_socket = MagicMock()
        mock_socket_class.return_value.__enter__.return_value = mock_socket
        mock_socket.bind.return_value = None  # Success

        port = self.manager.allocate_port(preferred=9050)

        assert port == 9050
        assert 9050 in self.manager.reserved_ports
        mock_socket.bind.assert_called_with(('localhost', 9050))

    @patch('socket.socket')
    def test_allocate_port_skip_unavailable(self, mock_socket_class):
        """Test port allocation skips unavailable ports."""
        mock_socket = MagicMock()
        mock_socket_class.return_value.__enter__.return_value = mock_socket

        # First port is unavailable, second is available
        mock_socket.bind.side_effect = [OSError("Port in use"), None]

        port = self.manager.allocate_port()

        assert port == 9001  # Should skip 9000 and use 9001
        assert 9001 in self.manager.reserved_ports

    @patch('socket.socket')
    def test_allocate_port_exhausted(self, mock_socket_class):
        """Test port allocation when all ports are exhausted."""
        mock_socket = MagicMock()
        mock_socket_class.return_value.__enter__.return_value = mock_socket
        mock_socket.bind.side_effect = OSError("Port in use")  # All ports unavailable

        with pytest.raises(NetworkError, match="No available ports in range"):
            self.manager.allocate_port()

    @patch('socket.socket')
    def test_allocate_multiple_ports(self, mock_socket_class):
        """Test allocating multiple consecutive ports."""
        mock_socket = MagicMock()
        mock_socket_class.return_value.__enter__.return_value = mock_socket
        mock_socket.bind.return_value = None  # All ports available

        ports = self.manager.allocate_ports(3)

        assert ports == [9000, 9001, 9002]
        for port in ports:
            assert port in self.manager.reserved_ports

    @patch('socket.socket')
    def test_allocate_multiple_ports_with_gap(self, mock_socket_class):
        """Test allocating multiple ports when some are unavailable."""
        mock_socket = MagicMock()
        mock_socket_class.return_value.__enter__.return_value = mock_socket

        # Simulate 9001 being unavailable
        def mock_bind(addr):
            if addr[1] == 9001:
                raise OSError("Port in use")

        mock_socket.bind.side_effect = mock_bind

        ports = self.manager.allocate_ports(3)

        # Should find 3 consecutive ports starting from 9002
        assert ports == [9002, 9003, 9004]
        for port in ports:
            assert port in self.manager.reserved_ports

    @patch('socket.socket')
    def test_allocate_multiple_ports_insufficient(self, mock_socket_class):
        """Test allocating multiple ports when insufficient consecutive ports."""
        # Create a small manager
        manager = PortManager(base_port=9000, max_ports=3)

        mock_socket = MagicMock()
        mock_socket_class.return_value.__enter__.return_value = mock_socket
        mock_socket.bind.side_effect = OSError("Port in use")  # No ports available

        with pytest.raises(NetworkError, match="Cannot allocate 5 consecutive ports"):
            manager.allocate_ports(5)

    def test_release_port(self):
        """Test releasing a port."""
        # Manually add a port to test release
        self.manager.reserved_ports.add(9050)

        self.manager.release_port(9050)

        assert 9050 not in self.manager.reserved_ports

    def test_release_nonexistent_port(self):
        """Test releasing a port that wasn't reserved."""
        # Should not raise error
        self.manager.release_port(9999)
        assert 9999 not in self.manager.reserved_ports

    def test_release_multiple_ports(self):
        """Test releasing multiple ports."""
        # Manually add ports to test release
        self.manager.reserved_ports.update([9050, 9051, 9052])

        self.manager.release_ports([9050, 9051, 9052, 9999])  # Include non-existent port

        assert 9050 not in self.manager.reserved_ports
        assert 9051 not in self.manager.reserved_ports
        assert 9052 not in self.manager.reserved_ports

    @patch('socket.socket')
    def test_is_port_available_free(self, mock_socket_class):
        """Test checking if a free port is available."""
        mock_socket = MagicMock()
        mock_socket_class.return_value.__enter__.return_value = mock_socket
        mock_socket.bind.return_value = None  # Port is free

        assert self.manager.is_port_available(9050) is True
        mock_socket.bind.assert_called_with(('localhost', 9050))

    @patch('socket.socket')
    def test_is_port_available_in_use(self, mock_socket_class):
        """Test checking if an in-use port is available."""
        mock_socket = MagicMock()
        mock_socket_class.return_value.__enter__.return_value = mock_socket
        mock_socket.bind.side_effect = OSError("Port in use")

        assert self.manager.is_port_available(9050) is False

    def test_is_port_available_reserved(self):
        """Test checking if a reserved port is available."""
        self.manager.reserved_ports.add(9050)

        assert self.manager.is_port_available(9050) is False

    def test_get_reserved_ports(self):
        """Test getting list of reserved ports."""
        self.manager.reserved_ports.update([9050, 9001, 9030])

        ports = self.manager.get_reserved_ports()

        assert ports == [9001, 9030, 9050]  # Should be sorted

    def test_clear_reservations(self):
        """Test clearing all reservations."""
        self.manager.reserved_ports.update([9050, 9051, 9052])

        self.manager.clear_reservations()

        assert len(self.manager.reserved_ports) == 0

    def test_thread_safety(self):
        """Test thread safety of port allocation."""
        # This is a basic test - proper thread safety testing would be more complex
        assert hasattr(self.manager, 'lock')
        assert isinstance(self.manager.lock, threading.Lock)


class TestPortManagerPersistence:
    """Test PortManager file persistence functionality."""

    def setup_method(self):
        """Set up test environment."""
        self.manager = PortManager(base_port=9000, max_ports=100)

    @patch('armadillo.utils.ports.atomic_write')
    def test_save_reservations(self, mock_atomic_write):
        """Test saving reservations to file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            reservation_file = Path(temp_dir) / "ports.txt"
            self.manager.set_reservation_file(reservation_file)
            self.manager.reserved_ports.update([9001, 9003, 9002])

            self.manager._save_reservations()

            mock_atomic_write.assert_called_once_with(reservation_file, "9001\n9002\n9003")

    @patch('armadillo.utils.ports.read_text')
    @patch('pathlib.Path.exists', return_value=True)
    def test_load_reservations(self, mock_exists, mock_read_text):
        """Test loading reservations from file."""
        mock_read_text.return_value = "9001\n9003\n9002\n"

        with tempfile.TemporaryDirectory() as temp_dir:
            reservation_file = Path(temp_dir) / "ports.txt"
            self.manager.set_reservation_file(reservation_file)

        assert 9001 in self.manager.reserved_ports
        assert 9002 in self.manager.reserved_ports
        assert 9003 in self.manager.reserved_ports

    @patch('armadillo.utils.ports.read_text')
    @patch('pathlib.Path.exists', return_value=True)
    def test_load_empty_reservations(self, mock_exists, mock_read_text):
        """Test loading empty reservations file."""
        mock_read_text.return_value = ""

        with tempfile.TemporaryDirectory() as temp_dir:
            reservation_file = Path(temp_dir) / "ports.txt"
            self.manager.set_reservation_file(reservation_file)

        assert len(self.manager.reserved_ports) == 0

    @patch('armadillo.utils.ports.read_text')
    @patch('pathlib.Path.exists', return_value=True)
    def test_load_reservations_error_handling(self, mock_exists, mock_read_text):
        """Test error handling when loading reservations fails."""
        mock_read_text.side_effect = Exception("File read error")

        with tempfile.TemporaryDirectory() as temp_dir:
            reservation_file = Path(temp_dir) / "ports.txt"
            # Should not raise exception
            self.manager.set_reservation_file(reservation_file)

        assert len(self.manager.reserved_ports) == 0

    @patch('armadillo.utils.ports.atomic_write')
    def test_save_reservations_error_handling(self, mock_atomic_write):
        """Test error handling when saving reservations fails."""
        mock_atomic_write.side_effect = Exception("File write error")

        with tempfile.TemporaryDirectory() as temp_dir:
            reservation_file = Path(temp_dir) / "ports.txt"
            self.manager.set_reservation_file(reservation_file)
            self.manager.reserved_ports.add(9001)

            # Should not raise exception
            self.manager._save_reservations()


class TestUtilityFunctions:
    """Test module-level utility functions."""

    @patch('socket.socket')
    def test_find_free_port_success(self, mock_socket_class):
        """Test finding a free port."""
        mock_socket = MagicMock()
        mock_socket_class.return_value.__enter__.return_value = mock_socket
        mock_socket.bind.return_value = None  # First port is free

        port = find_free_port(start_port=9000)

        assert port == 9000
        mock_socket.bind.assert_called_with(('localhost', 9000))

    @patch('socket.socket')
    def test_find_free_port_skip_busy(self, mock_socket_class):
        """Test finding free port when first ports are busy."""
        mock_socket = MagicMock()
        mock_socket_class.return_value.__enter__.return_value = mock_socket

        # First two ports busy, third is free
        mock_socket.bind.side_effect = [OSError("Port in use"), OSError("Port in use"), None]

        port = find_free_port(start_port=9000)

        assert port == 9002

    @patch('socket.socket')
    def test_find_free_port_exhausted(self, mock_socket_class):
        """Test finding free port when all are exhausted."""
        mock_socket = MagicMock()
        mock_socket_class.return_value.__enter__.return_value = mock_socket
        mock_socket.bind.side_effect = OSError("Port in use")  # All ports busy

        with pytest.raises(NetworkError, match="No free port found in range"):
            find_free_port(start_port=9000, max_attempts=10)

    @patch('socket.socket')
    def test_check_port_available_free(self, mock_socket_class):
        """Test checking if port is available (not in use)."""
        mock_socket = MagicMock()
        mock_socket_class.return_value.__enter__.return_value = mock_socket
        mock_socket.connect_ex.return_value = 1  # Connection failed = port free

        assert check_port_available("localhost", 9000) is True
        mock_socket.connect_ex.assert_called_with(("localhost", 9000))

    @patch('socket.socket')
    def test_check_port_available_in_use(self, mock_socket_class):
        """Test checking if port is in use."""
        mock_socket = MagicMock()
        mock_socket_class.return_value.__enter__.return_value = mock_socket
        mock_socket.connect_ex.return_value = 0  # Connection succeeded = port in use

        assert check_port_available("localhost", 9000) is False

    @patch('socket.socket')
    def test_check_port_available_error(self, mock_socket_class):
        """Test checking port availability handles errors."""
        mock_socket_class.side_effect = Exception("Socket error")

        # Should assume available if can't check
        assert check_port_available("localhost", 9000) is True

    @patch('socket.socket')
    @patch('time.sleep')
    def test_wait_for_port_success(self, mock_sleep, mock_socket_class):
        """Test waiting for port to become available."""
        mock_socket = MagicMock()
        mock_socket_class.return_value.__enter__.return_value = mock_socket
        mock_socket.connect_ex.return_value = 0  # Connection successful

        result = wait_for_port("localhost", 9000, timeout=5.0)

        assert result is True
        mock_socket.connect_ex.assert_called_with(("localhost", 9000))

    @patch('socket.socket')
    @patch('time.sleep')
    @patch('time.time')
    def test_wait_for_port_timeout(self, mock_time, mock_sleep, mock_socket_class):
        """Test waiting for port times out."""
        mock_socket = MagicMock()
        mock_socket_class.return_value.__enter__.return_value = mock_socket
        mock_socket.connect_ex.return_value = 1  # Connection failed

        # Mock time to simulate timeout
        mock_time.side_effect = [0, 1, 2, 3, 4, 5, 6]  # Exceed 5 second timeout

        result = wait_for_port("localhost", 9000, timeout=5.0)

        assert result is False

    @patch('socket.socket')
    @patch('time.sleep')
    @patch('time.time')
    def test_wait_for_port_eventually_available(self, mock_time, mock_sleep, mock_socket_class):
        """Test waiting for port that becomes available after some time."""
        mock_socket = MagicMock()
        mock_socket_class.return_value.__enter__.return_value = mock_socket

        # Fail first few times, then succeed
        mock_socket.connect_ex.side_effect = [1, 1, 0]  # Fail, fail, success
        mock_time.side_effect = [0, 1, 2, 3]

        result = wait_for_port("localhost", 9000, timeout=10.0)

        assert result is True

    @patch('socket.socket')
    @patch('time.sleep')
    def test_wait_for_port_handles_errors(self, mock_sleep, mock_socket_class):
        """Test wait_for_port handles socket errors gracefully."""
        mock_socket = MagicMock()
        mock_socket_class.return_value.__enter__.return_value = mock_socket
        mock_socket.connect_ex.side_effect = Exception("Socket error")

        # Should not raise exception, should return False on timeout
        result = wait_for_port("localhost", 9000, timeout=0.1)

        assert result is False


class TestGlobalPortManager:
    """Test global port manager functions."""

    def setup_method(self):
        """Reset global port manager."""
        import armadillo.utils.ports
        armadillo.utils.ports._port_manager = None

    def test_get_port_manager_singleton(self):
        """Test global port manager is singleton."""
        manager1 = get_port_manager()
        manager2 = get_port_manager()

        assert manager1 is manager2
        assert isinstance(manager1, PortManager)

    def test_get_port_manager_with_params(self):
        """Test global port manager with custom parameters."""
        manager = get_port_manager(base_port=9500, max_ports=200)

        assert manager.base_port == 9500
        assert manager.max_ports == 200

    def test_get_port_manager_subsequent_calls_ignore_params(self):
        """Test that subsequent calls ignore parameters."""
        manager1 = get_port_manager(base_port=9500, max_ports=200)
        manager2 = get_port_manager(base_port=10000, max_ports=300)

        assert manager1 is manager2
        assert manager1.base_port == 9500  # Should keep original parameters
        assert manager1.max_ports == 200

    @patch('armadillo.utils.ports.get_port_manager')
    def test_allocate_port_function(self, mock_get_port_manager):
        """Test module-level allocate_port function."""
        mock_manager = Mock()
        mock_manager.allocate_port.return_value = 9050
        mock_get_port_manager.return_value = mock_manager

        port = allocate_port(preferred=9050)

        assert port == 9050
        mock_manager.allocate_port.assert_called_once_with(9050)

    @patch('armadillo.utils.ports.get_port_manager')
    def test_allocate_ports_function(self, mock_get_port_manager):
        """Test module-level allocate_ports function."""
        mock_manager = Mock()
        mock_manager.allocate_ports.return_value = [9050, 9051, 9052]
        mock_get_port_manager.return_value = mock_manager

        ports = allocate_ports(3)

        assert ports == [9050, 9051, 9052]
        mock_manager.allocate_ports.assert_called_once_with(3)

    @patch('armadillo.utils.ports.get_port_manager')
    def test_release_port_function(self, mock_get_port_manager):
        """Test module-level release_port function."""
        mock_manager = Mock()
        mock_get_port_manager.return_value = mock_manager

        release_port(9050)

        mock_manager.release_port.assert_called_once_with(9050)

    @patch('armadillo.utils.ports.get_port_manager')
    def test_release_ports_function(self, mock_get_port_manager):
        """Test module-level release_ports function."""
        mock_manager = Mock()
        mock_get_port_manager.return_value = mock_manager

        release_ports([9050, 9051, 9052])

        mock_manager.release_ports.assert_called_once_with([9050, 9051, 9052])

    def test_reset_port_manager_function(self):
        """Test module-level reset_port_manager function."""
        from armadillo.utils.ports import reset_port_manager
        import armadillo.utils.ports

        # Set up a mock manager in the global variable
        mock_manager = Mock()
        armadillo.utils.ports._port_manager = mock_manager

        # Call reset_port_manager
        reset_port_manager()

        # Should clear reservations and reset global manager
        mock_manager.clear_reservations.assert_called_once()

        # Check that global manager is reset to None
        assert armadillo.utils.ports._port_manager is None


class TestPortManagerIntegration:
    """Test PortManager integration scenarios."""

    @patch('socket.socket')
    def test_full_allocation_cycle(self, mock_socket_class):
        """Test complete port allocation and release cycle."""
        manager = PortManager(base_port=9000, max_ports=10)

        mock_socket = MagicMock()
        mock_socket_class.return_value.__enter__.return_value = mock_socket
        mock_socket.bind.return_value = None  # All ports available

        # Allocate some ports
        port1 = manager.allocate_port()
        port2 = manager.allocate_port()
        ports = manager.allocate_ports(2)

        assert port1 == 9000
        assert port2 == 9001
        assert ports == [9002, 9003]

        # Check reservations
        reserved = manager.get_reserved_ports()
        expected = [9000, 9001, 9002, 9003]
        assert reserved == expected

        # Release some ports
        manager.release_port(port1)
        manager.release_ports(ports)

        # Check remaining reservations
        reserved = manager.get_reserved_ports()
        assert reserved == [9001]

    def test_port_manager_bounds_checking(self):
        """Test port manager respects bounds."""
        manager = PortManager(base_port=9000, max_ports=2)

        # Mock all ports as unavailable
        with patch('socket.socket') as mock_socket_class:
            mock_socket = MagicMock()
            mock_socket_class.return_value.__enter__.return_value = mock_socket
            mock_socket.bind.side_effect = OSError("Port in use")

            with pytest.raises(NetworkError, match="No available ports in range 9000-9002"):
                manager.allocate_port()


class TestErrorHandling:
    """Test error handling in port utilities."""

    def test_port_manager_handles_invalid_ports(self):
        """Test port manager handles invalid port numbers."""
        manager = PortManager()

        # Test with negative port
        assert manager.is_port_available(-1) is False

        # Test with very high port
        with patch('socket.socket') as mock_socket_class:
            mock_socket = MagicMock()
            mock_socket_class.return_value.__enter__.return_value = mock_socket
            mock_socket.bind.side_effect = OSError("Invalid port")

            assert manager.is_port_available(99999) is False

    def test_thread_safety_under_concurrent_access(self):
        """Test basic thread safety."""
        manager = PortManager(base_port=9000, max_ports=10)

        # This is a basic test - proper concurrency testing would be more complex
        with patch('socket.socket') as mock_socket_class:
            mock_socket = MagicMock()
            mock_socket_class.return_value.__enter__.return_value = mock_socket
            mock_socket.bind.return_value = None

            # Multiple rapid allocations should work
            ports = []
            for _ in range(5):
                port = manager.allocate_port()
                ports.append(port)

            # All ports should be different
            assert len(set(ports)) == len(ports)

            # All should be reserved
            for port in ports:
                assert port in manager.reserved_ports