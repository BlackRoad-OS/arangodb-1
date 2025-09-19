"""Resource pooling and lifecycle management utilities."""

import threading
import atexit
from typing import Set, List, Optional, Dict, Any, Protocol, TypeVar, Generic
from contextlib import contextmanager
from pathlib import Path

from ..core.log import get_logger
from .ports import PortManager

logger = get_logger(__name__)

T = TypeVar('T')


class ResourcePool(Protocol, Generic[T]):
    """Protocol for resource pools to enable dependency injection."""

    def acquire(self, preferred: Optional[T] = None) -> T:
        """Acquire a resource from the pool."""
        ...

    def acquire_multiple(self, count: int) -> List[T]:
        """Acquire multiple resources from the pool."""
        ...

    def release(self, resource: T) -> None:
        """Release a resource back to the pool."""
        ...

    def release_multiple(self, resources: List[T]) -> None:
        """Release multiple resources back to the pool."""
        ...


class ResourceTracker:
    """Tracks allocated resources for automatic cleanup."""

    def __init__(self, name: str = "") -> None:
        """Initialize resource tracker.

        Args:
            name: Name for this tracker (for logging)
        """
        self._name = name or "unnamed"
        self._allocated_resources: Dict[str, Set[Any]] = {}
        self._lock = threading.RLock()
        self._cleanup_callbacks: Dict[str, callable] = {}

    def register_resource_type(self, resource_type: str, cleanup_callback: callable) -> None:
        """Register a resource type with its cleanup callback.

        Args:
            resource_type: Name of the resource type (e.g., "ports", "files")
            cleanup_callback: Function to call for cleanup, receives list of resources
        """
        with self._lock:
            self._cleanup_callbacks[resource_type] = cleanup_callback
            if resource_type not in self._allocated_resources:
                self._allocated_resources[resource_type] = set()

    def track_resource(self, resource_type: str, resource: Any) -> None:
        """Track an allocated resource.

        Args:
            resource_type: Type of resource
            resource: The resource to track
        """
        with self._lock:
            if resource_type not in self._allocated_resources:
                self._allocated_resources[resource_type] = set()
            self._allocated_resources[resource_type].add(resource)
            logger.debug(f"ResourceTracker[{self._name}]: Tracking {resource_type} resource: {resource}")

    def untrack_resource(self, resource_type: str, resource: Any) -> None:
        """Stop tracking a resource (when properly released).

        Args:
            resource_type: Type of resource
            resource: The resource to stop tracking
        """
        with self._lock:
            if resource_type in self._allocated_resources:
                self._allocated_resources[resource_type].discard(resource)
                logger.debug(f"ResourceTracker[{self._name}]: Untracking {resource_type} resource: {resource}")

    def get_tracked_resources(self, resource_type: str) -> List[Any]:
        """Get all currently tracked resources of a specific type.

        Args:
            resource_type: Type of resource

        Returns:
            List of currently tracked resources
        """
        with self._lock:
            return list(self._allocated_resources.get(resource_type, set()))

    def cleanup_all(self) -> None:
        """Clean up all tracked resources."""
        with self._lock:
            for resource_type, resources in self._allocated_resources.items():
                if resources and resource_type in self._cleanup_callbacks:
                    try:
                        cleanup_func = self._cleanup_callbacks[resource_type]
                        resources_list = list(resources)
                        logger.info(f"ResourceTracker[{self._name}]: Cleaning up {len(resources_list)} {resource_type} resources")
                        cleanup_func(resources_list)
                        resources.clear()
                    except Exception as e:
                        logger.error(f"ResourceTracker[{self._name}]: Failed to cleanup {resource_type} resources: {e}")

    def cleanup_type(self, resource_type: str) -> None:
        """Clean up all tracked resources of a specific type.

        Args:
            resource_type: Type of resource to clean up
        """
        with self._lock:
            if resource_type in self._allocated_resources and resource_type in self._cleanup_callbacks:
                resources = self._allocated_resources[resource_type]
                if resources:
                    try:
                        cleanup_func = self._cleanup_callbacks[resource_type]
                        resources_list = list(resources)
                        logger.info(f"ResourceTracker[{self._name}]: Cleaning up {len(resources_list)} {resource_type} resources")
                        cleanup_func(resources_list)
                        resources.clear()
                    except Exception as e:
                        logger.error(f"ResourceTracker[{self._name}]: Failed to cleanup {resource_type} resources: {e}")


class PortPool:
    """Port resource pool with automatic lifecycle management."""

    def __init__(self,
                 port_manager: Optional[PortManager] = None,
                 resource_tracker: Optional[ResourceTracker] = None,
                 name: str = "") -> None:
        """Initialize port pool.

        Args:
            port_manager: Underlying port manager (creates default if None)
            resource_tracker: Resource tracker for cleanup (creates default if None)
            name: Name for this pool (for logging and isolation)
        """
        self._port_manager = port_manager or PortManager()
        self._resource_tracker = resource_tracker or ResourceTracker(name or "port_pool")
        self._name = name or "unnamed"
        self._lock = threading.RLock()

        # Register port cleanup with the resource tracker
        self._resource_tracker.register_resource_type("ports", self._cleanup_ports)

        logger.debug(f"Created PortPool[{self._name}]")

    def acquire(self, preferred: Optional[int] = None) -> int:
        """Acquire a port from the pool."""
        port = self._port_manager.allocate_port(preferred)
        self._resource_tracker.track_resource("ports", port)
        logger.debug(f"PortPool[{self._name}]: Acquired port {port}")
        return port

    def acquire_multiple(self, count: int) -> List[int]:
        """Acquire multiple consecutive ports."""
        ports = self._port_manager.allocate_ports(count)
        for port in ports:
            self._resource_tracker.track_resource("ports", port)
        logger.debug(f"PortPool[{self._name}]: Acquired {len(ports)} ports: {ports}")
        return ports

    def release(self, port: int) -> None:
        """Release a port back to the pool."""
        self._port_manager.release_port(port)
        self._resource_tracker.untrack_resource("ports", port)
        logger.debug(f"PortPool[{self._name}]: Released port {port}")

    def release_multiple(self, ports: List[int]) -> None:
        """Release multiple ports back to the pool."""
        self._port_manager.release_ports(ports)
        for port in ports:
            self._resource_tracker.untrack_resource("ports", port)
        logger.debug(f"PortPool[{self._name}]: Released {len(ports)} ports: {ports}")

    @contextmanager
    def acquire_context(self, preferred: Optional[int] = None):
        """Context manager for automatic port cleanup."""
        port = self.acquire(preferred)
        try:
            yield port
        finally:
            self.release(port)

    @contextmanager
    def acquire_multiple_context(self, count: int):
        """Context manager for automatic cleanup of multiple ports."""
        ports = self.acquire_multiple(count)
        try:
            yield ports
        finally:
            self.release_multiple(ports)

    def get_allocated_ports(self) -> List[int]:
        """Get all currently allocated ports from this pool."""
        return self._resource_tracker.get_tracked_resources("ports")

    def cleanup_all_ports(self) -> None:
        """Clean up all allocated ports."""
        self._resource_tracker.cleanup_type("ports")

    def is_port_available(self, port: int) -> bool:
        """Check if port is available."""
        return self._port_manager.is_port_available(port)

    def shutdown(self) -> None:
        """Shutdown the port pool and clean up all resources."""
        logger.info(f"PortPool[{self._name}]: Shutting down")
        self._resource_tracker.cleanup_all()

    def _cleanup_ports(self, ports: List[int]) -> None:
        """Cleanup callback for ports."""
        if ports:
            logger.info(f"PortPool[{self._name}]: Cleaning up {len(ports)} allocated ports: {ports}")
            self._port_manager.release_ports(ports)


class ManagedPortPool(PortPool):
    """Port pool with enhanced resource management and isolation."""

    def __init__(self,
                 base_port: int = 8529,
                 max_ports: int = 1000,
                 name: str = "",
                 enable_persistence: bool = True,
                 work_dir: Optional[Path] = None) -> None:
        """Initialize managed port pool.

        Args:
            base_port: Base port number for allocation
            max_ports: Maximum number of ports to allocate
            name: Name for this pool (for logging and file isolation)
            enable_persistence: Whether to persist reservations to file
            work_dir: Working directory for persistence files
        """
        # Create isolated port manager
        port_manager = PortManager(base_port=base_port, max_ports=max_ports)

        # Set up persistence if enabled
        if enable_persistence and work_dir:
            reservation_file = work_dir / f"port_reservations_{name or 'default'}.txt"
            port_manager.set_reservation_file(reservation_file)

        # Create resource tracker with unique name
        resource_tracker = ResourceTracker(f"{name}_managed_ports" if name else "managed_ports")

        super().__init__(
            port_manager=port_manager,
            resource_tracker=resource_tracker,
            name=name or "managed"
        )

        # Register shutdown cleanup
        atexit.register(self.shutdown)

        logger.info(f"Created ManagedPortPool[{self._name}] with base_port={base_port}, max_ports={max_ports}")


# Utility functions for creating different types of port pools
def create_isolated_port_pool(name: str,
                             base_port: int = 8529,
                             max_ports: int = 1000,
                             work_dir: Optional[Path] = None) -> ManagedPortPool:
    """Create an isolated port pool for test environments.

    Args:
        name: Unique name for the pool (prevents interference)
        base_port: Base port number
        max_ports: Maximum ports to allocate
        work_dir: Working directory for persistence

    Returns:
        Isolated port pool with automatic cleanup
    """
    return ManagedPortPool(
        base_port=base_port,
        max_ports=max_ports,
        name=name,
        enable_persistence=True,
        work_dir=work_dir
    )


def create_ephemeral_port_pool(name: str = "",
                              base_port: int = 8529,
                              max_ports: int = 1000) -> ManagedPortPool:
    """Create an ephemeral port pool (no persistence).

    Args:
        name: Name for the pool
        base_port: Base port number
        max_ports: Maximum ports to allocate

    Returns:
        Ephemeral port pool with automatic cleanup
    """
    return ManagedPortPool(
        base_port=base_port,
        max_ports=max_ports,
        name=name,
        enable_persistence=False,
        work_dir=None
    )
