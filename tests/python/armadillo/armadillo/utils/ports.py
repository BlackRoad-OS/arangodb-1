"""Port allocation and management utilities."""

import socket
import threading
import time
from typing import Set, Optional, List, Protocol
from pathlib import Path
from ..core.errors import NetworkError
from ..core.log import get_logger
from .filesystem import atomic_write, read_text

logger = get_logger(__name__)


class PortAllocator(Protocol):
    """Protocol for port allocation to enable dependency injection."""

    def allocate_port(self, preferred: Optional[int] = None) -> int:
        """Allocate an available port."""

    def allocate_ports(self, count: int) -> List[int]:
        """Allocate multiple ports."""

    def release_port(self, port: int) -> None:
        """Release a previously allocated port."""

    def release_ports(self, ports: List[int]) -> None:
        """Release multiple previously allocated ports."""


class PortManager:
    """Manages port allocation with collision avoidance."""

    def __init__(self, base_port: int = 8529, max_ports: int = 1000) -> None:
        self.base_port = base_port
        self.max_ports = max_ports
        self.reserved_ports: Set[int] = set()
        self.lock = threading.Lock()
        self.reservation_file: Optional[Path] = None

    def set_reservation_file(self, path: Path) -> None:
        """Set file for persistent port reservations."""
        self.reservation_file = path
        self._load_reservations()

    def allocate_port(self, preferred: Optional[int] = None) -> int:
        """Allocate an available port."""
        with self.lock:
            if preferred and self._is_port_available(preferred):
                self._reserve_port(preferred)
                return preferred
            for offset in range(self.max_ports):
                port = self.base_port + offset
                if self._is_port_available(port):
                    self._reserve_port(port)
                    return port
            raise NetworkError(
                f"No available ports in range {self.base_port}-{self.base_port + self.max_ports}"
            )

    def allocate_ports(self, count: int) -> List[int]:
        """Allocate multiple consecutive ports."""
        with self.lock:
            allocated = []
            start_port = self.base_port
            while (
                len(allocated) < count and start_port < self.base_port + self.max_ports
            ):
                consecutive = []
                for i in range(count):
                    port = start_port + i
                    if port >= self.base_port + self.max_ports:
                        break
                    if not self._is_port_available(port):
                        break
                    consecutive.append(port)
                if len(consecutive) == count:
                    for port in consecutive:
                        self._reserve_port(port)
                    return consecutive
                start_port += 1
            raise NetworkError(f"Cannot allocate {count} consecutive ports")

    def release_port(self, port: int) -> None:
        """Release a previously allocated port."""
        with self.lock:
            if port in self.reserved_ports:
                self.reserved_ports.remove(port)
                self._save_reservations()
                logger.debug("Released port %s", port)

    def release_ports(self, ports: List[int]) -> None:
        """Release multiple ports."""
        with self.lock:
            for port in ports:
                if port in self.reserved_ports:
                    self.reserved_ports.remove(port)
            self._save_reservations()
            logger.debug("Released ports %s", ports)

    def is_port_available(self, port: int) -> bool:
        """Check if port is available."""
        with self.lock:
            return self._is_port_available(port)

    def get_reserved_ports(self) -> List[int]:
        """Get list of currently reserved ports."""
        with self.lock:
            return sorted(list(self.reserved_ports))

    def clear_reservations(self) -> None:
        """Clear all port reservations."""
        with self.lock:
            self.reserved_ports.clear()
            self._save_reservations()
            logger.info("Cleared all port reservations")

    def _is_port_available(self, port: int) -> bool:
        """Check if port is available (not reserved and not in use)."""
        if port in self.reserved_ports:
            return False
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(("localhost", port))
                return True
        except OSError:
            return False

    def _reserve_port(self, port: int) -> None:
        """Reserve a port."""
        self.reserved_ports.add(port)
        self._save_reservations()
        logger.debug("Reserved port %s", port)

    def _save_reservations(self) -> None:
        """Save reservations to file."""
        if self.reservation_file:
            try:
                data = "\n".join(map(str, sorted(self.reserved_ports)))
                atomic_write(self.reservation_file, data)
            except (OSError, PermissionError, Exception) as e:
                logger.warning("Failed to save port reservations: %s", e)

    def _load_reservations(self) -> None:
        """Load reservations from file."""
        if self.reservation_file and self.reservation_file.exists():
            try:
                content = read_text(self.reservation_file).strip()
                if content:
                    ports = [
                        int(line.strip())
                        for line in content.split("\n")
                        if line.strip()
                    ]
                    self.reserved_ports.update(ports)
                    logger.debug("Loaded %s port reservations", len(ports))
            except (OSError, PermissionError, ValueError, Exception) as e:
                logger.warning("Failed to load port reservations: %s", e)


def find_free_port(start_port: int = 8529, max_attempts: int = 1000) -> int:
    """Find a free port starting from the given port."""
    for port in range(start_port, start_port + max_attempts):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(("localhost", port))
                return port
        except OSError:
            continue
    raise NetworkError(
        f"No free port found in range {start_port}-{start_port + max_attempts}"
    )


def check_port_available(host: str, port: int) -> bool:
    """Check if a specific port is available on host."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1.0)
            result = sock.connect_ex((host, port))
            return result != 0
    except (socket.error, OSError, Exception):
        return True


def wait_for_port(host: str, port: int, timeout: float = 30.0) -> bool:
    """Wait for a port to become available for connection."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(1.0)
                result = sock.connect_ex((host, port))
                if result == 0:
                    return True
        except (socket.error, OSError, Exception):
            pass
        time.sleep(0.5)
    return False


_port_manager: Optional[PortManager] = None


def get_port_manager(base_port: int = 8529, max_ports: int = 1000) -> PortManager:
    """Get or create global port manager."""
    global _port_manager
    if _port_manager is None:
        _port_manager = PortManager(base_port, max_ports)
    return _port_manager


def reset_port_manager() -> None:
    """Reset the global port manager.

    This is useful for test isolation where different tests
    might need different port manager configurations.
    """
    global _port_manager
    if _port_manager:
        _port_manager.clear_reservations()
        _port_manager = None
        logger.debug("Reset global port manager")


def allocate_port(preferred: Optional[int] = None) -> int:
    """Allocate port using global manager."""
    return get_port_manager().allocate_port(preferred)


def allocate_ports(count: int) -> List[int]:
    """Allocate multiple ports using global manager."""
    return get_port_manager().allocate_ports(count)


def release_port(port: int) -> None:
    """Release port using global manager."""
    get_port_manager().release_port(port)


def release_ports(ports: List[int]) -> None:
    """Release ports using global manager."""
    get_port_manager().release_ports(ports)
