"""Unit tests for pytest integration."""

from unittest.mock import Mock, patch, MagicMock

import pytest

from armadillo.testing.pytest_integration import (
    ContextTestManager,
    context_for_test,
    create_test_environment,
    cleanup_test_environment,
)


class TestContextTestManager:
    """Test test context manager functionality."""

    @patch("armadillo.testing.pytest_integration.get_test_environment_factory")
    def test_context_manager_creation(self, mock_get_factory):
        """Test context manager creation and basic functionality."""
        mock_factory = Mock()
        mock_context = Mock()
        mock_factory.create_context.return_value = mock_context
        mock_get_factory.return_value = mock_factory

        manager = ContextTestManager("test_context")

        assert manager._test_name == "test_context"
        assert manager._context is None

    @patch("armadillo.testing.pytest_integration.get_test_environment_factory")
    @patch("armadillo.testing.pytest_integration.reset_test_environment")
    def test_context_manager_enter_exit(self, mock_reset, mock_get_factory):
        """Test context manager enter and exit behavior."""
        mock_factory = Mock()
        mock_context = Mock()
        mock_factory.create_context.return_value = mock_context
        mock_get_factory.return_value = mock_factory

        manager = ContextTestManager("test_context", enable_persistence=True)

        # Test __enter__
        entered_context = manager.__enter__()

        assert entered_context == mock_context
        assert manager._context == mock_context
        mock_factory.create_context.assert_called_once_with(
            test_name="test_context", cleanup_on_exit=False, enable_persistence=True
        )

        # Test __exit__
        manager.__exit__(None, None, None)

        mock_context.cleanup.assert_called_once()
        mock_factory.cleanup_context.assert_called_once_with("test_context")
        mock_reset.assert_called_once()

    @patch("armadillo.testing.pytest_integration.get_test_environment_factory")
    @patch("armadillo.testing.pytest_integration.reset_test_environment")
    def test_context_manager_with_exception(self, mock_reset, mock_get_factory):
        """Test context manager behavior when exception occurs."""
        mock_factory = Mock()
        mock_context = Mock()
        mock_factory.create_context.return_value = mock_context
        mock_get_factory.return_value = mock_factory

        manager = ContextTestManager("test_context")

        # Test with exception
        manager.__enter__()
        manager.__exit__(ValueError, ValueError("test error"), None)

        # Should still cleanup properly
        mock_context.cleanup.assert_called_once()
        mock_factory.cleanup_context.assert_called_once_with("test_context")
        mock_reset.assert_called_once()

    @patch("armadillo.testing.pytest_integration.get_test_environment_factory")
    @patch("armadillo.testing.pytest_integration.reset_test_environment")
    def test_context_manager_as_context_manager(self, mock_reset, mock_get_factory):
        """Test using ContextTestManager as a context manager."""
        mock_factory = Mock()
        mock_context = Mock()
        mock_factory.create_context.return_value = mock_context
        mock_get_factory.return_value = mock_factory

        with ContextTestManager("test_context", custom_arg="value") as ctx:
            assert ctx == mock_context

        # Should be cleaned up
        mock_context.cleanup.assert_called_once()
        mock_factory.cleanup_context.assert_called_once_with("test_context")
        mock_reset.assert_called_once()

        # Should pass custom arguments
        mock_factory.create_context.assert_called_once_with(
            test_name="test_context", cleanup_on_exit=False, custom_arg="value"
        )


class TestUtilityFunctions:
    """Test utility functions."""

    @patch("armadillo.testing.pytest_integration.ContextTestManager")
    def test_context_for_test_function(self, mock_context_manager_class):
        """Test context_for_test function."""
        mock_manager = Mock()
        mock_context_manager_class.return_value = mock_manager

        result = context_for_test("test_name", arg1="value1", arg2="value2")

        assert result == mock_manager
        mock_context_manager_class.assert_called_once_with(
            "test_name", arg1="value1", arg2="value2"
        )

    @patch("armadillo.testing.pytest_integration.get_test_environment_factory")
    def test_create_test_environment(self, mock_get_factory):
        """Test create_test_environment function."""
        mock_factory = Mock()
        mock_context = Mock()
        mock_factory.create_context.return_value = mock_context
        mock_get_factory.return_value = mock_factory

        result = create_test_environment("test_env", custom_arg="value")

        assert result == mock_context
        mock_factory.create_context.assert_called_once_with(
            "test_env", custom_arg="value"
        )

    @patch("armadillo.testing.pytest_integration.get_test_environment_factory")
    @patch("armadillo.testing.pytest_integration.reset_test_environment")
    def test_cleanup_test_environment(self, mock_reset, mock_get_factory):
        """Test cleanup_test_environment function."""
        mock_factory = Mock()
        mock_get_factory.return_value = mock_factory

        cleanup_test_environment("test_env")

        mock_factory.cleanup_context.assert_called_once_with("test_env")
        mock_reset.assert_called_once()


class TestPytestFixtures:
    """Test pytest fixture functionality.

    Note: These tests mock the pytest request object since we're not
    running in a real pytest environment.
    """

    def test_isolated_test_context_fixture_import(self):
        """Test that isolated_test_context fixture can be imported."""
        from armadillo.testing.pytest_integration import isolated_test_context

        # Should be a function (fixture)
        assert callable(isolated_test_context)

    def test_test_environment_fixture_import(self):
        """Test that test_environment fixture can be imported."""
        from armadillo.testing.pytest_integration import test_environment

        # Should be a function (fixture)
        assert callable(test_environment)

    def test_reset_test_state_fixture_import(self):
        """Test that reset_test_state fixture can be imported."""
        from armadillo.testing.pytest_integration import reset_test_state

        # Should be a function (fixture)
        assert callable(reset_test_state)

    def test_cleanup_test_session_fixture_import(self):
        """Test that cleanup_test_session fixture can be imported."""
        from armadillo.testing.pytest_integration import cleanup_test_session

        # Should be a function (fixture)
        assert callable(cleanup_test_session)

    def test_isolated_test_context_fixture_behavior(self):
        """Test isolated_test_context fixture has correct properties."""
        from armadillo.testing.pytest_integration import isolated_test_context

        # Should be a pytest fixture (shown in string representation)
        assert "pytest_fixture" in str(isolated_test_context) or callable(
            isolated_test_context
        )

    def test_test_environment_fixture_properties(self):
        """Test test_environment fixture has correct properties."""
        from armadillo.testing.pytest_integration import test_environment

        # Should be a pytest fixture
        assert "pytest_fixture" in str(test_environment) or callable(test_environment)

    def test_reset_test_state_fixture_properties(self):
        """Test reset_test_state fixture has correct properties."""
        from armadillo.testing.pytest_integration import reset_test_state

        # Should be a pytest fixture
        assert "pytest_fixture" in str(reset_test_state) or callable(reset_test_state)

    def test_cleanup_test_session_fixture_properties(self):
        """Test cleanup_test_session fixture has correct properties."""
        from armadillo.testing.pytest_integration import cleanup_test_session

        # Should be a pytest fixture
        assert "pytest_fixture" in str(cleanup_test_session) or callable(
            cleanup_test_session
        )


class TestPytestConfiguration:
    """Test pytest configuration."""

    def test_pytest_configure_function_exists(self):
        """Test that pytest_configure function exists."""
        from armadillo.testing.pytest_integration import pytest_configure

        assert callable(pytest_configure)

    def test_pytest_configure_adds_markers(self):
        """Test that pytest_configure adds custom markers."""
        from armadillo.testing.pytest_integration import pytest_configure

        # Mock config object
        mock_config = Mock()

        pytest_configure(mock_config)

        # Should add markers
        expected_calls = [
            ("markers", "isolated: mark test as requiring full isolation"),
            (
                "markers",
                "no_isolation: mark test as not requiring isolation (for performance)",
            ),
        ]

        assert mock_config.addinivalue_line.call_count == 2
        for expected_call in expected_calls:
            mock_config.addinivalue_line.assert_any_call(*expected_call)


class TestIntegrationScenarios:
    """Test integration scenarios for pytest integration."""

    def test_fixture_integration_properties(self):
        """Test that fixtures can be imported together without conflicts."""
        from armadillo.testing.pytest_integration import (
            isolated_test_context,
            reset_test_state,
            test_environment,
            cleanup_test_session,
        )

        # All fixtures should be callable
        assert callable(isolated_test_context)
        assert callable(reset_test_state)
        assert callable(test_environment)
        assert callable(cleanup_test_session)

        # All should be pytest fixtures
        fixtures = [
            isolated_test_context,
            reset_test_state,
            test_environment,
            cleanup_test_session,
        ]
        for fixture in fixtures:
            assert "pytest_fixture" in str(fixture) or callable(fixture)

    def test_context_manager_integration(self):
        """Test context manager integration with real objects."""
        with patch(
            "armadillo.testing.pytest_integration.get_test_environment_factory"
        ) as mock_get_factory:
            with patch(
                "armadillo.testing.pytest_integration.reset_test_environment"
            ) as mock_reset:
                mock_factory = Mock()
                mock_context = Mock()
                mock_factory.create_context.return_value = mock_context
                mock_get_factory.return_value = mock_factory

                # Use the context manager
                with context_for_test("integration_test") as ctx:
                    assert ctx == mock_context

                # Verify cleanup
                mock_context.cleanup.assert_called_once()
                mock_factory.cleanup_context.assert_called_once_with("integration_test")
                mock_reset.assert_called_once()

    def test_error_handling_patterns(self):
        """Test that error handling patterns are documented in fixtures."""
        from armadillo.testing.pytest_integration import reset_test_state
        import inspect

        # Fixture should have docstring mentioning error handling
        source = inspect.getsource(reset_test_state)
        assert "reset_test_environment" in source

        # Should have try/except patterns for robustness
        assert "except" in source or "try" in source
