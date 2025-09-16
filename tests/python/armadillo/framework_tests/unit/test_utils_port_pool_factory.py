"""Unit tests for port pool factory."""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, call

import pytest

from armadillo.utils.port_pool_factory import (
    StandardPortPoolFactory, PortPoolTestFactory,
    create_port_pool_factory, create_test_port_pool_factory
)


class TestStandardPortPoolFactory:
    """Test standard port pool factory functionality."""

    def setup_method(self):
        """Set up test environment."""
        self.mock_logger_factory = Mock()
        self.mock_logger = Mock()
        self.mock_logger_factory.create_logger.return_value = self.mock_logger

        self.factory = StandardPortPoolFactory(logger_factory=self.mock_logger_factory)

    def test_factory_creation_with_logger_factory(self):
        """Test factory creation with logger factory."""
        assert self.factory._logger_factory == self.mock_logger_factory
        assert self.factory._logger == self.mock_logger
        self.mock_logger_factory.create_logger.assert_called_once()

    def test_factory_creation_without_logger_factory(self):
        """Test factory creation without logger factory."""
        with patch('armadillo.utils.port_pool_factory.get_logger') as mock_get_logger:
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger

            factory = StandardPortPoolFactory()

            assert factory._logger_factory is None
            assert factory._logger == mock_logger

    @patch('armadillo.utils.port_pool_factory.ManagedPortPool')
    def test_create_port_pool(self, mock_managed_pool_class):
        """Test creating a managed port pool."""
        mock_pool = Mock()
        mock_managed_pool_class.return_value = mock_pool

        work_dir = Path("/tmp/test")

        pool = self.factory.create_port_pool(
            name="test_pool",
            base_port=9000,
            max_ports=500,
            work_dir=work_dir,
            enable_persistence=True
        )

        mock_managed_pool_class.assert_called_once_with(
            base_port=9000,
            max_ports=500,
            name="test_pool",
            enable_persistence=True,
            work_dir=work_dir
        )

        assert pool == mock_pool
        self.mock_logger.debug.assert_called()

    @patch('armadillo.utils.port_pool_factory.create_isolated_port_pool')
    def test_create_isolated_pool(self, mock_create_isolated):
        """Test creating an isolated port pool."""
        mock_pool = Mock()
        mock_create_isolated.return_value = mock_pool

        work_dir = Path("/tmp/test")

        pool = self.factory.create_isolated_pool(
            name="isolated_test",
            base_port=9000,
            max_ports=500,
            work_dir=work_dir
        )

        mock_create_isolated.assert_called_once_with(
            name="isolated_test",
            base_port=9000,
            max_ports=500,
            work_dir=work_dir
        )

        assert pool == mock_pool
        self.mock_logger.debug.assert_called()

    @patch('armadillo.utils.port_pool_factory.create_ephemeral_port_pool')
    def test_create_ephemeral_pool(self, mock_create_ephemeral):
        """Test creating an ephemeral port pool."""
        mock_pool = Mock()
        mock_create_ephemeral.return_value = mock_pool

        pool = self.factory.create_ephemeral_pool(
            name="ephemeral_test",
            base_port=9000,
            max_ports=500
        )

        mock_create_ephemeral.assert_called_once_with(
            name="ephemeral_test",
            base_port=9000,
            max_ports=500
        )

        assert pool == mock_pool
        self.mock_logger.debug.assert_called()


class TestPortPoolTestFactory:
    """Test port pool factory for testing environments."""

    def setup_method(self):
        """Set up test environment."""
        self.mock_logger_factory = Mock()
        self.mock_logger = Mock()
        self.mock_logger_factory.create_logger.return_value = self.mock_logger

        self.factory = PortPoolTestFactory(
            logger_factory=self.mock_logger_factory,
            test_name="my_test"
        )

    def test_test_factory_creation(self):
        """Test test factory creation."""
        assert self.factory._test_name == "my_test"
        assert self.factory._created_pools == []
        self.mock_logger.debug.assert_called_with("Created PortPoolTestFactory for test: my_test")

    @patch('armadillo.utils.port_pool_factory.StandardPortPoolFactory.create_port_pool')
    def test_create_port_pool_with_test_prefix(self, mock_super_create):
        """Test creating pool with test prefix."""
        mock_pool = Mock()
        mock_super_create.return_value = mock_pool

        pool = self.factory.create_port_pool(
            name="my_pool",
            base_port=9000,
            max_ports=500,
            enable_persistence=True  # Should be overridden to False
        )

        # Should call parent with test prefix and no persistence
        mock_super_create.assert_called_once_with(
            name="test_my_test_my_pool",
            base_port=9000,
            max_ports=500,
            work_dir=None,
            enable_persistence=False  # Default to False for tests
        )

        assert pool == mock_pool
        assert pool in self.factory._created_pools

    @patch('armadillo.utils.port_pool_factory.StandardPortPoolFactory.create_isolated_pool')
    def test_create_isolated_pool_with_test_prefix(self, mock_super_create):
        """Test creating isolated pool with test prefix."""
        mock_pool = Mock()
        mock_super_create.return_value = mock_pool

        work_dir = Path("/tmp/test")

        pool = self.factory.create_isolated_pool(
            name="isolated_pool",
            base_port=9000,
            max_ports=500,
            work_dir=work_dir
        )

        mock_super_create.assert_called_once_with(
            name="test_my_test_isolated_pool",
            base_port=9000,
            max_ports=500,
            work_dir=work_dir
        )

        assert pool == mock_pool
        assert pool in self.factory._created_pools

    def test_cleanup_all_pools(self):
        """Test cleaning up all created pools."""
        # Create some mock pools
        mock_pool1 = Mock()
        mock_pool2 = Mock()
        mock_pool3 = Mock()

        # Add them to the factory's tracking
        self.factory._created_pools = [mock_pool1, mock_pool2, mock_pool3]

        # Cleanup all pools
        self.factory.cleanup_all_pools()

        # All pools should have shutdown called
        mock_pool1.shutdown.assert_called_once()
        mock_pool2.shutdown.assert_called_once()
        mock_pool3.shutdown.assert_called_once()

        # Pool list should be cleared
        assert self.factory._created_pools == []

    def test_cleanup_all_pools_with_exception(self):
        """Test cleanup handles exceptions gracefully."""
        # Create mock pools, one that raises exception on shutdown
        mock_pool1 = Mock()
        mock_pool2 = Mock()
        mock_pool2.shutdown.side_effect = Exception("Shutdown failed")
        mock_pool3 = Mock()

        self.factory._created_pools = [mock_pool1, mock_pool2, mock_pool3]

        # Should not raise exception
        self.factory.cleanup_all_pools()

        # All pools should still be processed
        mock_pool1.shutdown.assert_called_once()
        mock_pool2.shutdown.assert_called_once()
        mock_pool3.shutdown.assert_called_once()

        # Pool list should be cleared even with exception
        assert self.factory._created_pools == []

        # Should log error
        self.mock_logger.error.assert_called()

    def test_cleanup_pools_without_shutdown_method(self):
        """Test cleanup with pools that don't have shutdown method."""
        # Create mock pool without shutdown method
        mock_pool = Mock()
        del mock_pool.shutdown  # Remove shutdown method

        self.factory._created_pools = [mock_pool]

        # Should not raise exception
        self.factory.cleanup_all_pools()

        # Pool list should be cleared
        assert self.factory._created_pools == []


class TestFactoryUtilityFunctions:
    """Test utility functions for creating factories."""

    def test_create_port_pool_factory(self):
        """Test creating standard port pool factory."""
        mock_logger_factory = Mock()

        factory = create_port_pool_factory(logger_factory=mock_logger_factory)

        assert isinstance(factory, StandardPortPoolFactory)
        assert factory._logger_factory == mock_logger_factory

    def test_create_port_pool_factory_without_logger(self):
        """Test creating standard factory without logger factory."""
        factory = create_port_pool_factory()

        assert isinstance(factory, StandardPortPoolFactory)
        assert factory._logger_factory is None

    def test_create_test_port_pool_factory(self):
        """Test creating test port pool factory."""
        mock_logger_factory = Mock()

        factory = create_test_port_pool_factory(
            test_name="my_test",
            logger_factory=mock_logger_factory
        )

        assert isinstance(factory, PortPoolTestFactory)
        assert factory._test_name == "my_test"
        assert factory._logger_factory == mock_logger_factory

    def test_create_test_port_pool_factory_minimal(self):
        """Test creating test factory with minimal parameters."""
        factory = create_test_port_pool_factory()

        assert isinstance(factory, PortPoolTestFactory)
        assert factory._test_name == ""
        assert factory._logger_factory is None


class TestPortPoolFactoryProtocolCompliance:
    """Test that factories implement the PortPoolFactory protocol correctly."""

    def setup_method(self):
        """Set up test environment."""
        self.factory = StandardPortPoolFactory()

    def test_protocol_methods_exist(self):
        """Test that all protocol methods exist."""
        assert hasattr(self.factory, 'create_port_pool')
        assert hasattr(self.factory, 'create_isolated_pool')
        assert hasattr(self.factory, 'create_ephemeral_pool')

        assert callable(self.factory.create_port_pool)
        assert callable(self.factory.create_isolated_pool)
        assert callable(self.factory.create_ephemeral_pool)

    def test_method_signatures_match_protocol(self):
        """Test that method signatures match the protocol."""
        import inspect

        # Check create_port_pool signature
        sig = inspect.signature(self.factory.create_port_pool)
        expected_params = ['name', 'base_port', 'max_ports', 'work_dir', 'enable_persistence']
        assert all(param in sig.parameters for param in expected_params)

        # Check create_isolated_pool signature
        sig = inspect.signature(self.factory.create_isolated_pool)
        expected_params = ['name', 'base_port', 'max_ports', 'work_dir']
        assert all(param in sig.parameters for param in expected_params)

        # Check create_ephemeral_pool signature
        sig = inspect.signature(self.factory.create_ephemeral_pool)
        expected_params = ['name', 'base_port', 'max_ports']
        assert all(param in sig.parameters for param in expected_params)


class TestPortPoolFactoryIntegration:
    """Integration tests with real port pools."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.factory = StandardPortPoolFactory()

    def teardown_method(self):
        """Clean up after test."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_create_real_managed_pool(self):
        """Test creating a real managed port pool."""
        pool = self.factory.create_port_pool(
            name="integration_test",
            base_port=59000,  # Use high port to avoid conflicts
            max_ports=50,
            work_dir=self.temp_dir,
            enable_persistence=True
        )

        try:
            # Should be able to allocate and release ports
            port = pool.acquire()
            assert port >= 59000
            assert port < 59050

            pool.release(port)
        finally:
            pool.shutdown()

    def test_test_factory_integration(self):
        """Test integration with test factory."""
        test_factory = PortPoolTestFactory(test_name="integration_test")

        try:
            pool = test_factory.create_port_pool(
                name="test_pool",
                base_port=59100,
                max_ports=50
            )

            # Should be able to use the pool
            port = pool.acquire()
            assert port >= 59100
            pool.release(port)

        finally:
            test_factory.cleanup_all_pools()
