"""
Pytest configuration and fixtures for framework unit tests.
Provides comprehensive cleanup to prevent resource accumulation and state leakage.
"""

import pytest
import logging
import threading
import time
from unittest.mock import patch


@pytest.fixture(autouse=True)
def cleanup_logging():
    """Clean up logging system after each test."""
    yield

    # For unit tests, minimal cleanup is sufficient
    # Only do expensive cleanup for integration tests that actually create resources


@pytest.fixture(autouse=True)
def cleanup_global_state():
    """Clean up global state after each test."""
    yield

    # For unit tests, skip expensive global state cleanup
    # Unit tests should be isolated and not create real global resources


@pytest.fixture(autouse=True)
def cleanup_threads():
    """Clean up background threads after each test."""
    yield

    # For unit tests, skip expensive thread cleanup and sleeps
    # Unit tests should not create real background threads


@pytest.fixture(autouse=True)
def reset_filesystem_state():
    """Reset filesystem-related global state."""
    yield

    # Reset the global session ID to prevent test interference
    import armadillo.utils.filesystem as fs
    fs._test_session_id = None
    # Also clear any cached filesystem service
    if hasattr(fs, '_filesystem_service'):
        fs._filesystem_service._work_dir = None


@pytest.fixture(autouse=True)
def patch_dangerous_operations():
    """Patch potentially dangerous operations during unit tests."""

    with patch('subprocess.Popen') as mock_popen, \
         patch('socket.socket') as mock_socket, \
         patch('os.kill') as mock_kill, \
         patch('os.killpg') as mock_killpg, \
         patch('psutil.Process') as mock_psutil_process, \
         patch('threading.Thread') as mock_thread:

        # Configure safe defaults for Popen mock
        mock_subprocess = mock_popen.return_value
        mock_subprocess.pid = 12345
        mock_subprocess.poll.return_value = 0  # Process finished successfully
        mock_subprocess.terminate.return_value = None
        mock_subprocess.kill.return_value = None
        mock_subprocess.wait.return_value = 0
        mock_subprocess.returncode = 0

        # Configure stdout/stderr to prevent infinite loops
        # Set to None to simulate console inheritance (no streaming)
        mock_subprocess.stdout = None
        mock_subprocess.stderr = None

        # Configure socket mock
        mock_socket_instance = mock_socket.return_value.__enter__.return_value

        def mock_bind(addr):
            host, port = addr
            # Reject invalid ports
            if port < 1 or port > 65535:
                raise OSError(f"Invalid port: {port}")
            return None

        mock_socket_instance.bind.side_effect = mock_bind
        mock_socket_instance.connect_ex.return_value = 1  # Connection failed (port free)
        mock_socket_instance.settimeout.return_value = None

        # Configure process killing mocks
        mock_kill.return_value = None
        mock_killpg.return_value = None

        # Configure psutil process mock
        mock_psutil_instance = mock_psutil_process.return_value
        mock_psutil_instance.children.return_value = []
        mock_psutil_instance.terminate.return_value = None
        mock_psutil_instance.kill.return_value = None
        mock_psutil_instance.pid = 12345

        # Configure threading mock to prevent background threads
        mock_thread_instance = mock_thread.return_value
        mock_thread_instance.start.return_value = None
        mock_thread_instance.join.return_value = None
        mock_thread_instance.is_alive.return_value = False
        mock_thread_instance.daemon = True

        yield {
            'popen': mock_popen,
            'socket': mock_socket,
            'kill': mock_kill,
            'killpg': mock_killpg,
            'psutil_process': mock_psutil_process,
            'thread': mock_thread
        }


@pytest.fixture
def isolated_port_manager():
    """Provide an isolated PortManager for testing."""
    from armadillo.utils.ports import PortManager

    manager = PortManager(base_port=19000, max_ports=100)  # Use high ports to avoid conflicts
    yield manager

    # Cleanup
    manager.clear_reservations()


@pytest.fixture
def isolated_log_manager():
    """Provide an isolated LogManager for testing."""
    from armadillo.core.log import LogManager

    manager = LogManager()
    yield manager

    # Cleanup
    try:
        manager.shutdown()
    except Exception:
        pass


@pytest.fixture
def isolated_process_supervisor():
    """Provide an isolated ProcessSupervisor for testing."""
    from armadillo.core.process import ProcessSupervisor

    supervisor = ProcessSupervisor()
    yield supervisor

    # Cleanup
    try:
        for process_id in list(supervisor._processes.keys()):
            supervisor.stop(process_id)
        supervisor._processes.clear()
        supervisor._process_info.clear()
        if hasattr(supervisor, '_streaming_threads'):
            supervisor._streaming_threads.clear()
    except Exception:
        pass


@pytest.fixture
def no_actual_processes():
    """Prevent actual process creation during tests."""
    with patch('subprocess.Popen') as mock_popen:
        # Create a mock process that behaves safely
        mock_process = mock_popen.return_value
        mock_process.pid = 99999
        mock_process.poll.return_value = None  # Running
        mock_process.terminate.return_value = None
        mock_process.kill.return_value = None
        mock_process.stdout = None
        mock_process.stderr = None

        yield mock_popen


@pytest.fixture
def no_actual_sockets():
    """Prevent actual socket operations during tests."""
    with patch('socket.socket') as mock_socket_class:
        mock_socket = mock_socket_class.return_value.__enter__.return_value
        mock_socket.bind.return_value = None
        mock_socket.connect_ex.return_value = 1  # Connection failed
        mock_socket.settimeout.return_value = None

        yield mock_socket_class


@pytest.fixture
def no_actual_filesystem():
    """Mock filesystem operations to prevent actual file I/O."""
    with patch('pathlib.Path.mkdir') as mock_mkdir, \
         patch('pathlib.Path.exists', return_value=False) as mock_exists, \
         patch('pathlib.Path.is_dir', return_value=True) as mock_is_dir, \
         patch('pathlib.Path.is_file', return_value=True) as mock_is_file, \
         patch('shutil.rmtree') as mock_rmtree, \
         patch('armadillo.utils.filesystem.atomic_write') as mock_atomic_write, \
         patch('armadillo.utils.filesystem.read_text', return_value="") as mock_read_text:

        yield {
            'mkdir': mock_mkdir,
            'exists': mock_exists,
            'is_dir': mock_is_dir,
            'is_file': mock_is_file,
            'rmtree': mock_rmtree,
            'atomic_write': mock_atomic_write,
            'read_text': mock_read_text
        }


# Session-level cleanup
@pytest.fixture(scope="session", autouse=True)
def session_cleanup():
    """Perform session-wide cleanup."""
    yield

    # For unit tests, skip expensive session cleanup
    # Unit tests should not create persistent resources


def pytest_runtest_setup(item):
    """Setup for each test."""
    # Ensure clean start
    pass


def pytest_runtest_teardown(item, nextitem):
    """Teardown after each test."""
    # Force garbage collection
    import gc
    gc.collect()

    # Small delay to allow cleanup
    time.sleep(0.01)


def pytest_sessionstart(session):
    """Called after the Session object has been created."""
    # Set up session-wide test isolation
    pass


def pytest_sessionfinish(session, exitstatus):
    """Called after whole test run finished."""
    # Final cleanup
    logging.shutdown()

    # Wait for threads to finish
    time.sleep(0.1)

    # Force final garbage collection
    import gc
    gc.collect()
