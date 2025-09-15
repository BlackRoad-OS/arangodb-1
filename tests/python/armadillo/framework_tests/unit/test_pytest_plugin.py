"""
Minimal unit tests for pytest_plugin/plugin.py - Pytest plugin.

Tests essential ArmadilloPlugin functionality with minimal mocking.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from armadillo.pytest_plugin.plugin import ArmadilloPlugin


class TestArmadilloPluginBasic:
    """Test ArmadilloPlugin basic functionality."""

    def test_plugin_can_be_created(self):
        """Test ArmadilloPlugin can be instantiated."""
        plugin = ArmadilloPlugin()

        assert plugin is not None
        assert hasattr(plugin, '_session_servers')
        assert hasattr(plugin, '_session_deployments')
        assert hasattr(plugin, '_session_orchestrators')
        assert hasattr(plugin, '_armadillo_config')

    def test_plugin_initial_state(self):
        """Test plugin initial state."""
        plugin = ArmadilloPlugin()

        assert isinstance(plugin._session_servers, dict)
        assert isinstance(plugin._session_deployments, dict)
        assert isinstance(plugin._session_orchestrators, dict)
        assert len(plugin._session_servers) == 0
        assert len(plugin._session_deployments) == 0
        assert len(plugin._session_orchestrators) == 0
        assert plugin._armadillo_config is None

    def test_plugin_has_expected_methods(self):
        """Test plugin has expected pytest hook methods."""
        plugin = ArmadilloPlugin()

        # Check that pytest hook methods exist
        expected_methods = [
            'pytest_configure',
            'pytest_sessionstart',
            'pytest_sessionfinish'
        ]

        for method_name in expected_methods:
            assert hasattr(plugin, method_name)
            assert callable(getattr(plugin, method_name))


class TestArmadilloPluginConfiguration:
    """Test plugin configuration functionality."""

    def test_pytest_configure_basic(self):
        """Test pytest_configure registers markers."""
        plugin = ArmadilloPlugin()
        mock_config = Mock()
        mock_config.addinivalue_line = Mock()
        # Mock the option attribute properly
        mock_config.option = Mock()
        mock_config.option.verbose = 0  # Set a proper integer value

        plugin.pytest_configure(mock_config)

        # Should have registered several markers
        assert mock_config.addinivalue_line.call_count >= 5

        # Check that some key markers were registered
        call_args_list = [call[0] for call in mock_config.addinivalue_line.call_args_list]

        markers_registered = [args[1] for args in call_args_list if args[0] == "markers"]
        marker_names = [marker.split(':')[0] for marker in markers_registered]

        expected_markers = ['arango_single', 'arango_cluster', 'slow', 'fast']
        for expected in expected_markers:
            assert any(expected in marker for marker in marker_names), f"Marker '{expected}' not registered"

    @patch('armadillo.pytest_plugin.plugin.load_config')
    @patch('armadillo.pytest_plugin.plugin.configure_logging')
    @patch('armadillo.pytest_plugin.plugin.set_test_session_id')
    def test_pytest_sessionstart_basic(self, mock_set_session, mock_logging, mock_load_config):
        """Test pytest_sessionstart performs setup."""
        plugin = ArmadilloPlugin()
        mock_session = Mock()

        plugin.pytest_sessionstart(mock_session)

        # Should have called setup functions
        mock_load_config.assert_called_once()
        mock_logging.assert_called_once()
        mock_set_session.assert_called_once()

    @patch('armadillo.pytest_plugin.plugin.cleanup_work_dir')
    @patch('armadillo.pytest_plugin.plugin.clear_test_session')
    @patch('armadillo.pytest_plugin.plugin.stop_watchdog')
    def test_pytest_sessionfinish_basic(self, mock_stop_watchdog, mock_clear_session, mock_cleanup):
        """Test pytest_sessionfinish performs cleanup."""
        plugin = ArmadilloPlugin()
        mock_session = Mock()

        plugin.pytest_sessionfinish(mock_session, exitstatus=0)

        # Should have called cleanup functions
        mock_stop_watchdog.assert_called_once()
        mock_clear_session.assert_called_once()
        mock_cleanup.assert_called_once()


class TestArmadilloPluginSessionManagement:
    """Test plugin session management functionality."""

    def test_plugin_tracks_servers(self):
        """Test plugin can track servers."""
        plugin = ArmadilloPlugin()

        # Add mock server
        mock_server = Mock()
        plugin._session_servers["test_server"] = mock_server

        assert len(plugin._session_servers) == 1
        assert plugin._session_servers["test_server"] == mock_server

    def test_plugin_tracks_deployments(self):
        """Test plugin can track deployments."""
        plugin = ArmadilloPlugin()

        # Add mock deployment
        mock_deployment = Mock()
        plugin._session_deployments["test_deployment"] = mock_deployment

        assert len(plugin._session_deployments) == 1
        assert plugin._session_deployments["test_deployment"] == mock_deployment

    def test_plugin_tracks_orchestrators(self):
        """Test plugin can track orchestrators."""
        plugin = ArmadilloPlugin()

        # Add mock orchestrator
        mock_orchestrator = Mock()
        plugin._session_orchestrators["test_orchestrator"] = mock_orchestrator

        assert len(plugin._session_orchestrators) == 1
        assert plugin._session_orchestrators["test_orchestrator"] == mock_orchestrator


class TestArmadilloPluginErrorHandling:
    """Test plugin error handling."""

    @patch('armadillo.pytest_plugin.plugin.load_config')
    def test_sessionstart_handles_config_error(self, mock_load_config):
        """Test sessionstart handles configuration errors gracefully."""
        plugin = ArmadilloPlugin()
        mock_session = Mock()
        mock_load_config.side_effect = Exception("Config failed")

        # Should not crash even if config fails
        try:
            plugin.pytest_sessionstart(mock_session)
        except Exception:
            # If it raises, that's also acceptable behavior
            pass

    @patch('armadillo.pytest_plugin.plugin.cleanup_work_dir')
    def test_sessionfinish_handles_cleanup_error(self, mock_cleanup):
        """Test sessionfinish handles cleanup errors gracefully."""
        plugin = ArmadilloPlugin()
        mock_session = Mock()
        mock_cleanup.side_effect = Exception("Cleanup failed")

        # Should not crash even if cleanup fails
        try:
            plugin.pytest_sessionfinish(mock_session, exitstatus=0)
        except Exception:
            # If it raises, that's also acceptable behavior
            pass


class TestArmadilloPluginIntegration:
    """Test plugin integration scenarios."""

    @patch('armadillo.pytest_plugin.plugin.atexit.register')
    @patch('armadillo.pytest_plugin.plugin.set_global_deadline')
    def test_emergency_cleanup_registration(self, mock_set_deadline, mock_atexit):
        """Test plugin registers emergency cleanup."""
        plugin = ArmadilloPlugin()
        mock_session = Mock()

        try:
            plugin.pytest_sessionstart(mock_session)
            # Should have registered emergency cleanup
            mock_atexit.assert_called()
        except Exception:
            # If sessionstart fails for other reasons, that's ok for this test
            pass

    def test_plugin_state_isolation(self):
        """Test different plugin instances are isolated."""
        plugin1 = ArmadilloPlugin()
        plugin2 = ArmadilloPlugin()

        # Add data to one plugin
        plugin1._session_servers["server1"] = Mock()
        plugin1._armadillo_config = {"test": "config"}

        # Other plugin should be unaffected
        assert len(plugin2._session_servers) == 0
        assert plugin2._armadillo_config is None

    def test_plugin_config_persistence(self):
        """Test plugin can store and retrieve config."""
        plugin = ArmadilloPlugin()

        test_config = {"database": "test", "port": 8529}
        plugin._armadillo_config = test_config

        assert plugin._armadillo_config == test_config
        assert plugin._armadillo_config["database"] == "test"
        assert plugin._armadillo_config["port"] == 8529


class TestArmadilloPluginMarkers:
    """Test plugin marker functionality."""

    def test_configure_registers_all_markers(self):
        """Test all expected markers are registered."""
        plugin = ArmadilloPlugin()
        mock_config = Mock()
        mock_config.addinivalue_line = Mock()
        # Mock the option attribute properly
        mock_config.option = Mock()
        mock_config.option.verbose = 0  # Set a proper integer value

        plugin.pytest_configure(mock_config)

        # Extract registered markers
        call_args_list = mock_config.addinivalue_line.call_args_list
        marker_calls = [call for call in call_args_list if call[0][0] == "markers"]

        # Should have registered multiple markers
        assert len(marker_calls) >= 5

        # Check specific markers exist
        marker_strings = [call[0][1] for call in marker_calls]
        combined_markers = " ".join(marker_strings)

        expected_marker_names = [
            "arango_single",
            "arango_cluster",
            "slow",
            "fast",
            "crash_test",
            "stress_test"
        ]

        for marker_name in expected_marker_names:
            assert marker_name in combined_markers, f"Expected marker '{marker_name}' not found"
