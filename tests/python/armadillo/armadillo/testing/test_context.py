"""Test context system for isolated testing environments."""
import tempfile
import threading
import atexit
from typing import Optional, Dict, List, Protocol, ContextManager
from pathlib import Path
from contextlib import contextmanager
from ..core.logger_factory import LoggerFactory, StandardLoggerFactory
from ..utils.port_pool_factory import PortPoolFactory, create_test_port_pool_factory
from ..utils.resource_pool import PortPool
from ..core.log import get_logger
logger = get_logger(__name__)

class TestContext(Protocol):
    """Protocol for test contexts to enable dependency injection."""

    def get_logger_factory(self) -> LoggerFactory:
        """Get the logger factory for this test context."""

    def get_port_pool_factory(self) -> PortPoolFactory:
        """Get the port pool factory for this test context."""

    def get_work_dir(self) -> Path:
        """Get the working directory for this test context."""

    def cleanup(self) -> None:
        """Clean up all resources in this test context."""

class IsolatedTestContext:
    """Isolated test context with independent resources."""

    def __init__(self, test_name: str='', work_dir: Optional[Path]=None, enable_persistence: bool=False, cleanup_on_exit: bool=True) -> None:
        """Initialize isolated test context.

        Args:
            test_name: Name of the test (for isolation and logging)
            work_dir: Working directory (creates temp dir if None)
            enable_persistence: Whether to enable resource persistence
            cleanup_on_exit: Whether to register atexit cleanup
        """
        self._test_name = test_name or f'test_{id(self)}'
        self._enable_persistence = enable_persistence
        self._cleanup_on_exit = cleanup_on_exit
        if work_dir:
            self._work_dir = work_dir
            self._owns_work_dir = False
        else:
            self._temp_dir = tempfile.mkdtemp(prefix=f'armadillo_{self._test_name}_')
            self._work_dir = Path(self._temp_dir)
            self._owns_work_dir = True
        self._work_dir.mkdir(parents=True, exist_ok=True)
        self._logger_factory = StandardLoggerFactory(namespace=f'test_{self._test_name}', enable_json=enable_persistence, enable_console=False, log_file=self._work_dir / 'test.log' if enable_persistence else None)
        self._port_pool_factory = create_test_port_pool_factory(test_name=self._test_name, logger_factory=self._logger_factory)
        self._created_pools: List[PortPool] = []
        self._cleanup_callbacks: List[callable] = []
        self._lock = threading.RLock()
        self._cleaned_up = False
        if cleanup_on_exit:
            atexit.register(self.cleanup)
        self._logger = self._logger_factory.create_logger('test_context')
        self._logger.debug('Created IsolatedTestContext: %s', self._test_name)

    @property
    def test_name(self) -> str:
        """Get the test name for this context."""
        return self._test_name

    def get_logger_factory(self) -> LoggerFactory:
        """Get the logger factory for this test context."""
        return self._logger_factory

    def get_port_pool_factory(self) -> PortPoolFactory:
        """Get the port pool factory for this test context."""
        return self._port_pool_factory

    def get_work_dir(self) -> Path:
        """Get the working directory for this test context."""
        return self._work_dir

    def create_logger(self, name: str):
        """Create a logger within this test context."""
        return self._logger_factory.create_logger(name)

    def create_port_pool(self, name: str='', **kwargs) -> PortPool:
        """Create a port pool within this test context."""
        if 'work_dir' not in kwargs:
            kwargs['work_dir'] = self._work_dir
        pool = self._port_pool_factory.create_port_pool(name=name, **kwargs)
        with self._lock:
            self._created_pools.append(pool)
        return pool

    def add_cleanup_callback(self, callback: callable) -> None:
        """Add a cleanup callback to be called during context cleanup."""
        with self._lock:
            self._cleanup_callbacks.append(callback)

    @contextmanager
    def temp_logger(self, name: str):
        """Context manager for temporary logger that cleans up after use."""
        logger_obj = self.create_logger(name)
        try:
            yield logger_obj
        finally:
            pass

    @contextmanager
    def temp_port_pool(self, name: str='', **kwargs):
        """Context manager for temporary port pool that cleans up after use."""
        pool = self.create_port_pool(name=name, **kwargs)
        try:
            yield pool
        finally:
            if hasattr(pool, 'shutdown'):
                try:
                    pool.shutdown()
                except (RuntimeError, OSError) as e:
                    self._logger.error('Error shutting down temp port pool: %s', e)

    def cleanup(self) -> None:
        """Clean up all resources in this test context."""
        with self._lock:
            if self._cleaned_up:
                return
            self._logger.debug('Cleaning up IsolatedTestContext: %s', self._test_name)
            for callback in reversed(self._cleanup_callbacks):
                try:
                    callback()
                except (RuntimeError, OSError, AttributeError) as e:
                    self._logger.error('Error in cleanup callback: %s', e)
            for pool in self._created_pools:
                try:
                    if hasattr(pool, 'shutdown'):
                        pool.shutdown()
                except (RuntimeError, OSError) as e:
                    self._logger.error('Error shutting down port pool: %s', e)
            if hasattr(self._port_pool_factory, 'cleanup_all_pools'):
                try:
                    self._port_pool_factory.cleanup_all_pools()
                except (RuntimeError, OSError) as e:
                    self._logger.error('Error cleaning up port pool factory: %s', e)
            try:
                self._logger_factory.shutdown()
            except (RuntimeError, OSError):
                pass
            if self._owns_work_dir and hasattr(self, '_temp_dir'):
                try:
                    import shutil
                    shutil.rmtree(self._temp_dir, ignore_errors=True)
                except (OSError, PermissionError):
                    pass
            self._cleanup_callbacks.clear()
            self._created_pools.clear()
            self._cleaned_up = True

class EnvironmentTestFactory:
    """Factory for creating isolated test environments."""

    def __init__(self) -> None:
        self._active_contexts: Dict[str, IsolatedTestContext] = {}
        self._lock = threading.RLock()
        atexit.register(self.cleanup_all)

    def create_context(self, test_name: str, work_dir: Optional[Path]=None, enable_persistence: bool=False, cleanup_on_exit: bool=True) -> IsolatedTestContext:
        """Create an isolated test context.

        Args:
            test_name: Unique name for the test context
            work_dir: Optional working directory
            enable_persistence: Whether to enable resource persistence
            cleanup_on_exit: Whether to register atexit cleanup

        Returns:
            Isolated test context
        """
        with self._lock:
            if test_name in self._active_contexts:
                self._active_contexts[test_name].cleanup()
                del self._active_contexts[test_name]
            context = IsolatedTestContext(test_name=test_name, work_dir=work_dir, enable_persistence=enable_persistence, cleanup_on_exit=cleanup_on_exit)
            self._active_contexts[test_name] = context
            return context

    @contextmanager
    def temp_context(self, test_name: str='', **kwargs) -> ContextManager[IsolatedTestContext]:
        """Context manager for temporary test context that cleans up automatically."""
        test_name = test_name or f'temp_{id(threading.current_thread())}'
        context = self.create_context(test_name, cleanup_on_exit=False, **kwargs)
        try:
            yield context
        finally:
            context.cleanup()
            with self._lock:
                if test_name in self._active_contexts:
                    del self._active_contexts[test_name]

    def get_context(self, test_name: str) -> Optional[IsolatedTestContext]:
        """Get an existing test context by name."""
        with self._lock:
            return self._active_contexts.get(test_name)

    def cleanup_context(self, test_name: str) -> bool:
        """Clean up a specific test context.

        Returns:
            True if context was found and cleaned up, False otherwise
        """
        with self._lock:
            context = self._active_contexts.pop(test_name, None)
            if context:
                context.cleanup()
                return True
            return False

    def cleanup_all(self) -> None:
        """Clean up all active test contexts."""
        with self._lock:
            contexts = list(self._active_contexts.items())
            self._active_contexts.clear()
        for test_name, context in contexts:
            try:
                context.cleanup()
            except (RuntimeError, OSError, AttributeError):
                pass

    def list_active_contexts(self) -> List[str]:
        """Get list of active context names."""
        with self._lock:
            return list(self._active_contexts.keys())
_test_env_factory = EnvironmentTestFactory()

def get_test_environment_factory() -> EnvironmentTestFactory:
    """Get the global test environment factory."""
    return _test_env_factory

def create_test_context(test_name: str, **kwargs) -> IsolatedTestContext:
    """Create an isolated test context using the global factory."""
    return _test_env_factory.create_context(test_name, **kwargs)

@contextmanager
def temp_test_context(test_name: str='', **kwargs) -> ContextManager[IsolatedTestContext]:
    """Context manager for temporary test context."""
    with _test_env_factory.temp_context(test_name, **kwargs) as context:
        yield context

def cleanup_test_context(test_name: str) -> bool:
    """Clean up a specific test context."""
    return _test_env_factory.cleanup_context(test_name)

def cleanup_all_test_contexts() -> None:
    """Clean up all test contexts."""
    _test_env_factory.cleanup_all()

def reset_test_environment() -> None:
    """Reset the entire test environment."""
    cleanup_all_test_contexts()
    try:
        from ..core.log import reset_logging
        reset_logging()
    except ImportError:
        pass
    try:
        from ..utils.ports import reset_port_manager
        reset_port_manager()
    except ImportError:
        pass