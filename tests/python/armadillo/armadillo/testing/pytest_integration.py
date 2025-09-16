"""Pytest integration for Armadillo test isolation."""

import pytest
from typing import Generator
from pathlib import Path

from .test_context import (
    IsolatedTestContext,
    get_test_environment_factory,
    reset_test_environment
)


@pytest.fixture
def isolated_test_context(request) -> Generator[IsolatedTestContext, None, None]:
    """Pytest fixture providing an isolated test context.

    Creates a fully isolated test environment with:
    - Isolated logger factory
    - Isolated port pool factory
    - Temporary working directory
    - Automatic cleanup after test

    Usage:
        def test_something(isolated_test_context):
            logger = isolated_test_context.create_logger("test_logger")
            port_pool = isolated_test_context.create_port_pool("test_pool")
            # ... test code ...
    """
    # Get test name from pytest request
    test_name = request.node.name
    if hasattr(request.node, 'cls') and request.node.cls:
        test_name = f"{request.node.cls.__name__}.{test_name}"

    # Create isolated context
    factory = get_test_environment_factory()
    context = factory.create_context(
        test_name=test_name,
        enable_persistence=False,  # Don't persist logs for unit tests
        cleanup_on_exit=False  # We'll clean up manually
    )

    try:
        yield context
    finally:
        # Clean up the context
        context.cleanup()
        factory.cleanup_context(test_name)


@pytest.fixture
def test_environment(request) -> Generator[IsolatedTestContext, None, None]:
    """Pytest fixture providing a test environment with persistence.

    Similar to isolated_test_context but enables persistence for debugging.
    Useful for integration tests where you might want to inspect logs.

    Usage:
        def test_integration(test_environment):
            logger = test_environment.create_logger("integration")
            logger.info("This will be saved to test.log")
            # ... test code ...
    """
    # Get test name from pytest request
    test_name = request.node.name
    if hasattr(request.node, 'cls') and request.node.cls:
        test_name = f"{request.node.cls.__name__}.{test_name}"

    # Create isolated context with persistence
    factory = get_test_environment_factory()
    context = factory.create_context(
        test_name=test_name,
        enable_persistence=True,  # Enable persistence for debugging
        cleanup_on_exit=False  # We'll clean up manually
    )

    try:
        yield context
    finally:
        # Clean up the context
        context.cleanup()
        factory.cleanup_context(test_name)


@pytest.fixture(autouse=True, scope="function")
def reset_test_state():
    """Auto-use fixture that resets test state after each test.

    This fixture automatically runs after each test to ensure clean state.
    It resets global managers and cleans up any lingering resources.
    """
    yield  # Let the test run

    # Reset global state after test
    try:
        reset_test_environment()
    except Exception:
        # Ignore errors during cleanup - tests should still pass
        pass


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_session():
    """Session-scoped fixture that ensures cleanup at end of test session."""
    yield  # Let all tests run

    # Final cleanup at end of session
    try:
        factory = get_test_environment_factory()
        factory.cleanup_all()
        reset_test_environment()
    except Exception:
        # Ignore errors during final cleanup
        pass


class ContextTestManager:
    """Context manager for managing test isolation in non-pytest environments."""

    def __init__(self, test_name: str, **kwargs):
        """Initialize test context manager.

        Args:
            test_name: Name of the test
            **kwargs: Additional arguments for IsolatedTestContext
        """
        self._test_name = test_name
        self._context_kwargs = kwargs
        self._context = None

    def __enter__(self) -> IsolatedTestContext:
        """Enter the test context."""
        factory = get_test_environment_factory()
        self._context = factory.create_context(
            test_name=self._test_name,
            cleanup_on_exit=False,  # We'll clean up manually
            **self._context_kwargs
        )
        return self._context

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit the test context with cleanup."""
        if self._context:
            self._context.cleanup()
            factory = get_test_environment_factory()
            factory.cleanup_context(self._test_name)

        # Reset global state
        reset_test_environment()


def context_for_test(test_name: str, **kwargs) -> ContextTestManager:
    """Create a test context manager for non-pytest environments.

    Usage:
        with context_for_test("my_test") as ctx:
            logger = ctx.create_logger("test")
            pool = ctx.create_port_pool("ports")
            # ... test code ...
    """
    return ContextTestManager(test_name, **kwargs)


# Utility functions for manual test management
def create_test_environment(test_name: str, **kwargs) -> IsolatedTestContext:
    """Create a test environment for manual management.

    Note: Remember to call cleanup() or use the context manager instead.
    """
    factory = get_test_environment_factory()
    return factory.create_context(test_name, **kwargs)


def cleanup_test_environment(test_name: str) -> None:
    """Clean up a specific test environment."""
    factory = get_test_environment_factory()
    factory.cleanup_context(test_name)
    reset_test_environment()


# Pytest markers for test categorization
def pytest_configure(config):
    """Configure pytest markers for test isolation."""
    config.addinivalue_line(
        "markers", "isolated: mark test as requiring full isolation"
    )
    config.addinivalue_line(
        "markers", "no_isolation: mark test as not requiring isolation (for performance)"
    )
