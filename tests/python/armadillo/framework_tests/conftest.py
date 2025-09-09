"""Test configuration and fixtures for framework unit tests."""

import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, patch

from armadillo.core.config import ConfigLoader
from armadillo.core.types import ArmadilloConfig, DeploymentMode


@pytest.fixture
def temp_dir():
    """Provide a temporary directory for tests."""
    temp_path = Path(tempfile.mkdtemp(prefix="armadillo_test_"))
    try:
        yield temp_path
    finally:
        if temp_path.exists():
            shutil.rmtree(temp_path, ignore_errors=True)


@pytest.fixture
def mock_config():
    """Provide a mock configuration for testing."""
    return ArmadilloConfig(
        deployment_mode=DeploymentMode.SINGLE_SERVER,
        test_timeout=60.0,
        temp_dir=Path("/tmp/test_armadillo"),
        keep_instances_on_failure=False,
        verbose=0
    )


@pytest.fixture
def isolated_environment(temp_dir):
    """Provide an isolated environment for tests."""
    # Mock environment variables
    with patch.dict('os.environ', {}, clear=True):
        # Set test temp directory
        with patch('armadillo.core.config.get_config') as mock_get_config:
            mock_get_config.return_value = ArmadilloConfig(
                deployment_mode=DeploymentMode.SINGLE_SERVER,
                temp_dir=temp_dir,
                test_timeout=30.0
            )
            yield temp_dir


@pytest.fixture
def mock_process():
    """Mock subprocess.Popen for process testing."""
    mock_popen = Mock()
    mock_popen.pid = 12345
    mock_popen.returncode = 0
    mock_popen.poll.return_value = None  # Still running
    mock_popen.communicate.return_value = ("stdout", "stderr")
    mock_popen.wait.return_value = 0

    with patch('subprocess.Popen', return_value=mock_popen):
        yield mock_popen


@pytest.fixture
def mock_logger():
    """Mock logger for testing."""
    with patch('armadillo.core.log.get_logger') as mock_get_logger:
        logger = Mock()
        mock_get_logger.return_value = logger
        yield logger


@pytest.fixture(autouse=True)
def reset_global_state():
    """Reset global state between tests."""
    # Reset any global instances that might interfere with tests
    from armadillo.core import config, time
    from armadillo.utils import codec, ports, auth, crypto

    # Clear any cached instances
    config._config_manager._config = None
    time._timeout_manager = time.TimeoutManager()

    # Reset codec manager
    codec._codec_manager = codec.CodecManager()

    # Reset other global state as needed
    yield

    # Cleanup after test
    try:
        time.stop_watchdog()
    except:
        pass
