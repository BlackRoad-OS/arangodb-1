"""Factory for creating port pools with dependency injection."""

from typing import Optional, Protocol
from pathlib import Path
from ..core.log import get_logger
from .resource_pool import (
    PortPool,
    ManagedPortPool,
    create_isolated_port_pool,
    create_ephemeral_port_pool,
)

logger = get_logger(__name__)


class PortPoolFactory(Protocol):
    """Protocol for port pool factories to enable dependency injection."""

    def create_port_pool(
        self,
        name: str = "",
        base_port: int = 8529,
        max_ports: int = 1000,
        work_dir: Optional[Path] = None,
        enable_persistence: bool = True,
    ) -> PortPool:
        """Create a port pool instance."""

    def create_isolated_pool(
        self,
        name: str,
        base_port: int = 8529,
        max_ports: int = 1000,
        work_dir: Optional[Path] = None,
    ) -> PortPool:
        """Create an isolated port pool for test environments."""

    def create_ephemeral_pool(
        self, name: str = "", base_port: int = 8529, max_ports: int = 1000
    ) -> PortPool:
        """Create an ephemeral port pool (no persistence)."""


class StandardPortPoolFactory:
    """Standard implementation of PortPoolFactory."""

    def __init__(self, logger_factory=None) -> None:
        """Initialize port pool factory.

        Args:
            logger_factory: Optional logger factory for isolated logging
        """
        self._logger_factory = logger_factory
        self._logger = (
            logger_factory.create_logger(__name__)
            if logger_factory
            else get_logger(__name__)
        )
        self._logger.debug("Created StandardPortPoolFactory")

    def create_port_pool(
        self,
        name: str = "",
        base_port: int = 8529,
        max_ports: int = 1000,
        work_dir: Optional[Path] = None,
        enable_persistence: bool = True,
    ) -> PortPool:
        """Create a managed port pool instance."""
        self._logger.debug(
            "Creating managed port pool: name=%s, base_port=%s, max_ports=%s",
            name,
            base_port,
            max_ports,
        )
        return ManagedPortPool(
            base_port=base_port,
            max_ports=max_ports,
            name=name,
            enable_persistence=enable_persistence,
            work_dir=work_dir,
        )

    def create_isolated_pool(
        self,
        name: str,
        base_port: int = 8529,
        max_ports: int = 1000,
        work_dir: Optional[Path] = None,
    ) -> PortPool:
        """Create an isolated port pool for test environments."""
        self._logger.debug(
            "Creating isolated port pool: name=%s, base_port=%s", name, base_port
        )
        return create_isolated_port_pool(
            name=name, base_port=base_port, max_ports=max_ports, work_dir=work_dir
        )

    def create_ephemeral_pool(
        self, name: str = "", base_port: int = 8529, max_ports: int = 1000
    ) -> PortPool:
        """Create an ephemeral port pool (no persistence)."""
        self._logger.debug(
            "Creating ephemeral port pool: name=%s, base_port=%s", name, base_port
        )
        return create_ephemeral_port_pool(
            name=name, base_port=base_port, max_ports=max_ports
        )


class PortPoolTestFactory(StandardPortPoolFactory):
    """Port pool factory specialized for testing environments."""

    def __init__(self, logger_factory=None, test_name: str = "") -> None:
        """Initialize test port pool factory.

        Args:
            logger_factory: Optional logger factory for isolated logging
            test_name: Name of the test (for resource isolation)
        """
        super().__init__(logger_factory)
        self._test_name = test_name
        self._created_pools = []
        self._logger.debug("Created PortPoolTestFactory for test: %s", test_name)

    def create_port_pool(
        self,
        name: str = "",
        base_port: int = 8529,
        max_ports: int = 1000,
        work_dir: Optional[Path] = None,
        enable_persistence: bool = False,
    ) -> PortPool:
        """Create a test port pool with automatic cleanup tracking."""
        pool_name = (
            f"test_{self._test_name}_{name}" if self._test_name else f"test_{name}"
        )
        pool = super().create_port_pool(
            name=pool_name,
            base_port=base_port,
            max_ports=max_ports,
            work_dir=work_dir,
            enable_persistence=False,
        )
        self._created_pools.append(pool)
        return pool

    def create_isolated_pool(
        self,
        name: str,
        base_port: int = 8529,
        max_ports: int = 1000,
        work_dir: Optional[Path] = None,
    ) -> PortPool:
        """Create an isolated test pool."""
        pool_name = (
            f"test_{self._test_name}_{name}" if self._test_name else f"test_{name}"
        )
        pool = super().create_isolated_pool(
            name=pool_name, base_port=base_port, max_ports=max_ports, work_dir=work_dir
        )
        self._created_pools.append(pool)
        return pool

    def cleanup_all_pools(self) -> None:
        """Clean up all pools created by this factory."""
        for pool in self._created_pools:
            try:
                if hasattr(pool, "shutdown"):
                    pool.shutdown()
            except (RuntimeError, OSError, Exception) as e:
                self._logger.error("Failed to shutdown pool: %s", e)
        self._created_pools.clear()
        self._logger.debug("Cleaned up all pools for test: %s", self._test_name)


def create_port_pool_factory(logger_factory=None) -> StandardPortPoolFactory:
    """Create a standard port pool factory.

    Args:
        logger_factory: Optional logger factory for isolated logging

    Returns:
        Port pool factory instance
    """
    return StandardPortPoolFactory(logger_factory=logger_factory)


def create_test_port_pool_factory(
    test_name: str = "", logger_factory=None
) -> PortPoolTestFactory:
    """Create a port pool factory for testing.

    Args:
        test_name: Name of the test for resource isolation
        logger_factory: Optional logger factory for isolated logging

    Returns:
        Test-specific port pool factory with automatic cleanup
    """
    return PortPoolTestFactory(logger_factory=logger_factory, test_name=test_name)
