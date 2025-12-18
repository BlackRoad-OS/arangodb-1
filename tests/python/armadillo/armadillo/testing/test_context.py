"""Test context system for isolated testing environments."""

import shutil
import tempfile
import threading
import atexit
from typing import Optional, List, Protocol, Callable, Iterator, Any
from pathlib import Path
from contextlib import contextmanager
from ..core.logger_factory import LoggerFactory, StandardLoggerFactory
from ..utils.ports import PortManager
from ..core.log import get_logger

logger = get_logger(__name__)


class TestContext(Protocol):
    """Protocol for test contexts to enable dependency injection."""

    def get_logger_factory(self) -> LoggerFactory:
        """Get the logger factory for this test context."""

    def get_port_manager(self) -> PortManager:
        """Get the port manager for this test context."""

    def get_work_dir(self) -> Path:
        """Get the working directory for this test context."""

    def cleanup(self) -> None:
        """Clean up all resources in this test context."""


class IsolatedTestContext:
    """Isolated test context with independent resources."""

    def __init__(
        self,
        test_name: str = "",
        work_dir: Optional[Path] = None,
        enable_persistence: bool = False,
        cleanup_on_exit: bool = True,
    ) -> None:
        """Initialize isolated test context.

        Args:
            test_name: Name of the test (for isolation and logging)
            work_dir: Working directory (creates temp dir if None)
            enable_persistence: Whether to enable resource persistence
            cleanup_on_exit: Whether to register atexit cleanup
        """
        self._test_name = test_name or f"test_{id(self)}"
        self._enable_persistence = enable_persistence
        self._cleanup_on_exit = cleanup_on_exit
        self._temp_dir: Optional[str] = None  # Initialize to None for proper state tracking
        if work_dir:
            self._work_dir = work_dir
            self._owns_work_dir = False
        else:
            self._temp_dir = tempfile.mkdtemp(prefix=f"armadillo_{self._test_name}_")
            self._work_dir = Path(self._temp_dir)
            self._owns_work_dir = True
        self._work_dir.mkdir(parents=True, exist_ok=True)
        self._logger_factory = StandardLoggerFactory(
            namespace=f"test_{self._test_name}",
            enable_json=enable_persistence,
            enable_console=False,
            log_file=self._work_dir / "test.log" if enable_persistence else None,
        )
        self._port_manager = PortManager()
        self._allocated_ports: List[int] = []
        self._cleanup_callbacks: List[Callable[[], None]] = []
        self._lock = threading.RLock()
        self._cleaned_up = False
        if cleanup_on_exit:
            atexit.register(self.cleanup)
        self._logger = self._logger_factory.create_logger("test_context")
        self._logger.debug("Created IsolatedTestContext: %s", self._test_name)

    @property
    def test_name(self) -> str:
        """Get the test name for this context."""
        return self._test_name

    def get_logger_factory(self) -> LoggerFactory:
        """Get the logger factory for this test context."""
        return self._logger_factory

    def get_port_manager(self) -> PortManager:
        """Get the port manager for this test context."""
        return self._port_manager

    def get_work_dir(self) -> Path:
        """Get the working directory for this test context."""
        return self._work_dir

    def create_logger(self, name: str) -> Any:
        """Create a logger within this test context."""
        return self._logger_factory.create_logger(name)

    def allocate_port(self, preferred: Optional[int] = None) -> int:
        """Allocate a port within this test context."""
        port = self._port_manager.allocate_port(preferred)
        with self._lock:
            self._allocated_ports.append(port)
        return port

    def release_port(self, port: int) -> None:
        """Release a port within this test context."""
        self._port_manager.release_port(port)
        with self._lock:
            if port in self._allocated_ports:
                self._allocated_ports.remove(port)

    def add_cleanup_callback(self, callback: Callable[[], None]) -> None:
        """Add a cleanup callback to be called during context cleanup."""
        with self._lock:
            self._cleanup_callbacks.append(callback)

    @contextmanager
    def temp_logger(self, name: str) -> Iterator[Any]:
        """Context manager for temporary logger that cleans up after use."""
        logger_obj = self.create_logger(name)
        try:
            yield logger_obj
        finally:
            pass

    @contextmanager
    def temp_port(self, preferred: Optional[int] = None) -> Iterator[int]:
        """Context manager for temporary port that releases after use."""
        port = self.allocate_port(preferred)
        try:
            yield port
        finally:
            self.release_port(port)

    def cleanup(self) -> None:
        """Clean up all resources in this test context."""
        with self._lock:
            if self._cleaned_up:
                return
            self._logger.debug("Cleaning up IsolatedTestContext: %s", self._test_name)

            # Run cleanup callbacks
            for callback in reversed(self._cleanup_callbacks):
                try:
                    callback()
                except (RuntimeError, OSError, AttributeError, Exception) as e:
                    self._logger.error("Error in cleanup callback: %s", e)

            # Release allocated ports
            for port in self._allocated_ports:
                try:
                    self._port_manager.release_port(port)
                except Exception as e:
                    self._logger.error("Error releasing port %s: %s", port, e)
            self._allocated_ports.clear()

            # Shutdown logger factory
            try:
                self._logger_factory.shutdown()
            except (RuntimeError, OSError):
                pass

            # Clean up work directory if we own it
            if self._owns_work_dir and self._temp_dir is not None:
                try:
                    shutil.rmtree(self._temp_dir, ignore_errors=True)
                except (OSError, PermissionError):
                    pass

            self._cleanup_callbacks.clear()
            self._cleaned_up = True


def create_test_context(test_name: str, **kwargs: Any) -> IsolatedTestContext:
    """Create an isolated test context."""
    return IsolatedTestContext(test_name=test_name, **kwargs)


@contextmanager
def temp_test_context(test_name: str = "", **kwargs: Any) -> Iterator[IsolatedTestContext]:
    """Context manager for temporary test context."""
    context = create_test_context(test_name, cleanup_on_exit=False, **kwargs)
    try:
        yield context
    finally:
        context.cleanup()


def reset_test_environment() -> None:
    """Reset the entire test environment."""
    try:
        from ..core.log import reset_logging

        reset_logging()
    except (ImportError, AttributeError):
        pass
