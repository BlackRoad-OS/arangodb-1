"""Simple randomized port allocation for test isolation."""

import random
import socket
import threading
from typing import Optional, Protocol
from ..core.errors import NetworkError
from ..core.log import get_logger

logger = get_logger(__name__)


class PortAllocator(Protocol):
    """Protocol for port allocation to enable dependency injection."""

    def allocate_port(self, preferred: Optional[int] = None) -> int:
        """Allocate an available port."""

    def release_port(self, port: int) -> None:
        """Release a previously allocated port."""


class PortManager:
    """Simple thread-safe port allocator with randomization for test isolation.

    Randomizes port selection to minimize conflicts between parallel test runs.
    """

    def __init__(self, base_port: int = 8529, max_ports: int = 1000) -> None:
        """Initialize port manager.

        Args:
            base_port: Starting port number for allocation range
            max_ports: Size of the port range
        """
        self.base_port = base_port
        self.max_ports = max_ports
        self._allocated = set()
        self._lock = threading.Lock()

    def allocate_port(self, preferred: Optional[int] = None) -> int:
        """Allocate an available port.

        If preferred port is specified and available, use it.
        Otherwise, randomly select from available ports in range.

        Args:
            preferred: Optional preferred port number

        Returns:
            Allocated port number

        Raises:
            NetworkError: If no ports available
        """
        with self._lock:
            # Try preferred port first
            if preferred and self._is_available(preferred):
                self._allocated.add(preferred)
                logger.debug("Allocated preferred port %s", preferred)
                return preferred

            # Randomize port selection for better isolation
            port_range = list(range(self.base_port, self.base_port + self.max_ports))
            random.shuffle(port_range)

            for port in port_range:
                if self._is_available(port):
                    self._allocated.add(port)
                    logger.debug("Allocated random port %s", port)
                    return port

            raise NetworkError(
                f"No available ports in range {self.base_port}-{self.base_port + self.max_ports}"
            )

    def release_port(self, port: int) -> None:
        """Release a previously allocated port.

        Args:
            port: Port number to release
        """
        with self._lock:
            self._allocated.discard(port)
            logger.debug("Released port %s", port)

    def _is_available(self, port: int) -> bool:
        """Check if port is available (not allocated and not in use).

        Args:
            port: Port number to check

        Returns:
            True if port is available
        """
        if port in self._allocated:
            return False

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(("127.0.0.1", port))
                return True
        except OSError:
            return False
