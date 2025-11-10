"""Tests for simplified port management."""

import pytest
from armadillo.utils.ports import PortManager
from armadillo.core.errors import NetworkError


class TestPortManager:
    """Test PortManager basic functionality."""

    def test_allocate_port(self):
        """Test port allocation."""
        pm = PortManager()
        port = pm.allocate_port()
        assert 8529 <= port < 9529
        assert port in pm._allocated

    def test_allocate_preferred_port(self):
        """Test preferred port allocation."""
        pm = PortManager()
        port = pm.allocate_port(preferred=9000)
        assert port == 9000
        assert port in pm._allocated

    def test_release_port(self):
        """Test port release."""
        pm = PortManager()
        port = pm.allocate_port()
        pm.release_port(port)
        assert port not in pm._allocated

    def test_randomization(self):
        """Test that port allocation is randomized."""
        pm = PortManager()
        ports = [pm.allocate_port() for _ in range(10)]
        # Should not be sequential (very unlikely with randomization)
        sequential = all(ports[i] == ports[i - 1] + 1 for i in range(1, len(ports)))
        assert not sequential, "Ports should be randomized, not sequential"

    def test_no_duplicate_allocation(self):
        """Test that allocated ports aren't reallocated."""
        pm = PortManager()
        ports = {pm.allocate_port() for _ in range(50)}
        assert len(ports) == 50, "All ports should be unique"

    def test_thread_safety(self):
        """Test basic thread safety."""
        import threading

        pm = PortManager()
        ports = []
        errors = []

        def allocate():
            try:
                ports.append(pm.allocate_port())
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=allocate) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(set(ports)) == len(ports), "No duplicate ports"

    def test_exhaustion(self):
        """Test port exhaustion error."""
        pm = PortManager(base_port=8529, max_ports=5)
        # Allocate all ports
        for _ in range(5):
            pm.allocate_port()
        # Next allocation should fail
        with pytest.raises(NetworkError):
            pm.allocate_port()

    def test_release_and_reuse(self):
        """Test that released ports can be reused."""
        pm = PortManager(base_port=8529, max_ports=5)
        # Allocate all ports
        ports = [pm.allocate_port() for _ in range(5)]
        # Release one
        pm.release_port(ports[2])
        # Should be able to allocate again
        new_port = pm.allocate_port()
        assert new_port is not None
