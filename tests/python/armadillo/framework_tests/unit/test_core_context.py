"""Unit tests for ApplicationContext.

Tests the core dependency injection container to ensure:
1. Context is immutable
2. Default dependencies are created correctly
3. Custom dependencies can be injected
4. Testing factory creates appropriate defaults
"""

import pytest
from pathlib import Path
from unittest.mock import Mock

from armadillo.core.context import ApplicationContext
from armadillo.core.types import ArmadilloConfig, DeploymentMode
from armadillo.core.log import Logger
from armadillo.utils.ports import PortAllocator
from armadillo.utils.auth import AuthProvider
from armadillo.utils.filesystem import FilesystemService
from armadillo.core.process import ProcessSupervisor


class TestApplicationContext:
    """Test ApplicationContext creation and immutability."""

    def test_context_is_immutable(self):
        """ApplicationContext should be frozen/immutable."""
        ctx = ApplicationContext.for_testing()

        # Attempting to modify should raise FrozenInstanceError
        with pytest.raises(Exception):  # dataclass FrozenInstanceError
            ctx.config = ArmadilloConfig()

        with pytest.raises(Exception):
            ctx.logger = Mock()

    def test_create_with_all_defaults(self):
        """Should create valid context with all default dependencies."""
        config = ArmadilloConfig(
            deployment_mode=DeploymentMode.SINGLE_SERVER,
            temp_dir=Path("/tmp/armadillo-test"),
        )

        ctx = ApplicationContext.create(config)

        # Verify all dependencies are created
        assert ctx.config is config
        assert ctx.logger is not None
        assert ctx.port_allocator is not None
        assert ctx.auth_provider is not None
        assert ctx.filesystem is not None
        assert ctx.process_supervisor is not None

    def test_create_with_custom_logger(self):
        """Should accept custom logger implementation."""
        config = ArmadilloConfig(
            deployment_mode=DeploymentMode.SINGLE_SERVER,
            temp_dir=Path("/tmp/armadillo-test"),
        )
        mock_logger = Mock(spec=Logger)

        ctx = ApplicationContext.create(config, logger=mock_logger)

        assert ctx.logger is mock_logger

    def test_create_with_custom_port_allocator(self):
        """Should accept custom port allocator implementation."""
        config = ArmadilloConfig(
            deployment_mode=DeploymentMode.SINGLE_SERVER,
            temp_dir=Path("/tmp/armadillo-test"),
        )
        mock_allocator = Mock(spec=PortAllocator)

        ctx = ApplicationContext.create(config, port_allocator=mock_allocator)

        assert ctx.port_allocator is mock_allocator

    def test_create_with_custom_auth_provider(self):
        """Should accept custom auth provider implementation."""
        config = ArmadilloConfig(
            deployment_mode=DeploymentMode.SINGLE_SERVER,
            temp_dir=Path("/tmp/armadillo-test"),
        )
        mock_auth = Mock(spec=AuthProvider)

        ctx = ApplicationContext.create(config, auth_provider=mock_auth)

        assert ctx.auth_provider is mock_auth

    def test_create_with_custom_filesystem(self):
        """Should accept custom filesystem service implementation."""
        config = ArmadilloConfig(
            deployment_mode=DeploymentMode.SINGLE_SERVER,
            temp_dir=Path("/tmp/armadillo-test"),
        )
        mock_fs = Mock(spec=FilesystemService)

        ctx = ApplicationContext.create(config, filesystem=mock_fs)

        assert ctx.filesystem is mock_fs

    def test_create_with_custom_process_supervisor(self):
        """Should accept custom process supervisor implementation."""
        config = ArmadilloConfig(
            deployment_mode=DeploymentMode.SINGLE_SERVER,
            temp_dir=Path("/tmp/armadillo-test"),
        )
        mock_supervisor = Mock(spec=ProcessSupervisor)

        ctx = ApplicationContext.create(config, process_supervisor=mock_supervisor)

        assert ctx.process_supervisor is mock_supervisor

    def test_create_with_multiple_custom_dependencies(self):
        """Should accept multiple custom dependencies simultaneously."""
        config = ArmadilloConfig(
            deployment_mode=DeploymentMode.SINGLE_SERVER,
            temp_dir=Path("/tmp/armadillo-test"),
        )
        mock_logger = Mock(spec=Logger)
        mock_allocator = Mock(spec=PortAllocator)
        mock_auth = Mock(spec=AuthProvider)

        ctx = ApplicationContext.create(
            config,
            logger=mock_logger,
            port_allocator=mock_allocator,
            auth_provider=mock_auth,
        )

        assert ctx.logger is mock_logger
        assert ctx.port_allocator is mock_allocator
        assert ctx.auth_provider is mock_auth
        # Other dependencies should still use defaults
        assert ctx.filesystem is not None
        assert ctx.process_supervisor is not None


class TestApplicationContextForTesting:
    """Test the testing-specific factory method."""

    def test_for_testing_creates_minimal_config(self):
        """for_testing() should create minimal test configuration."""
        ctx = ApplicationContext.for_testing()

        assert ctx.config is not None
        assert ctx.config.deployment_mode == DeploymentMode.SINGLE_SERVER
        assert ctx.config.is_test_mode is True
        assert ctx.config.temp_dir == Path("/tmp/armadillo-test")

    def test_for_testing_accepts_custom_config(self):
        """for_testing() should accept custom test configuration."""
        custom_config = ArmadilloConfig(
            deployment_mode=DeploymentMode.CLUSTER,
            temp_dir=Path("/custom/test/path"),
            is_test_mode=True,
        )

        ctx = ApplicationContext.for_testing(config=custom_config)

        assert ctx.config is custom_config
        assert ctx.config.deployment_mode == DeploymentMode.CLUSTER

    def test_for_testing_accepts_mock_dependencies(self):
        """for_testing() should accept mock dependencies for testing."""
        mock_logger = Mock(spec=Logger)
        mock_allocator = Mock(spec=PortAllocator)

        ctx = ApplicationContext.for_testing(
            logger=mock_logger,
            port_allocator=mock_allocator,
        )

        assert ctx.logger is mock_logger
        assert ctx.port_allocator is mock_allocator

    def test_for_testing_all_dependencies_present(self):
        """for_testing() should create all required dependencies."""
        ctx = ApplicationContext.for_testing()

        # Verify no None values
        assert ctx.config is not None
        assert ctx.logger is not None
        assert ctx.port_allocator is not None
        assert ctx.auth_provider is not None
        assert ctx.filesystem is not None
        assert ctx.process_supervisor is not None


class TestApplicationContextIntegration:
    """Integration tests for ApplicationContext with real dependencies."""

    def test_context_with_real_dependencies(self, tmp_path):
        """Should work with real dependency implementations."""
        config = ArmadilloConfig(
            deployment_mode=DeploymentMode.SINGLE_SERVER,
            temp_dir=tmp_path / "armadillo",
            test_timeout=120.0,
            is_test_mode=True,
        )

        ctx = ApplicationContext.create(config)

        # Verify we can use the dependencies
        assert ctx.logger is not None

        # Port allocator should work
        port = ctx.port_allocator.allocate_port()
        assert 1 <= port <= 65535
        ctx.port_allocator.release_port(port)

        # Auth provider should work
        headers = ctx.auth_provider.get_auth_headers()
        assert "Authorization" in headers
        assert headers["Authorization"].startswith("Bearer ")

        # Filesystem should work
        test_dir = ctx.filesystem.work_dir()
        assert test_dir.exists()

    def test_multiple_contexts_are_independent(self, tmp_path):
        """Multiple contexts should not interfere with each other."""
        config1 = ArmadilloConfig(
            deployment_mode=DeploymentMode.SINGLE_SERVER,
            temp_dir=tmp_path / "ctx1",
            is_test_mode=True,
        )
        config2 = ArmadilloConfig(
            deployment_mode=DeploymentMode.CLUSTER,
            temp_dir=tmp_path / "ctx2",
            is_test_mode=True,
        )

        ctx1 = ApplicationContext.create(config1)
        ctx2 = ApplicationContext.create(config2)

        # Contexts should be independent
        assert ctx1.config is not ctx2.config
        assert ctx1.config.deployment_mode != ctx2.config.deployment_mode
        assert ctx1.config.temp_dir != ctx2.config.temp_dir

        # Each should have its own dependencies
        assert ctx1.port_allocator is not ctx2.port_allocator
        assert ctx1.auth_provider is not ctx2.auth_provider
        assert ctx1.filesystem is not ctx2.filesystem
