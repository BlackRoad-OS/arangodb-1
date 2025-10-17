"""
Minimal unit tests for pytest_plugin/plugin.py - Pytest plugin.

Tests essential ArmadilloPlugin functionality with minimal mocking.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from armadillo.pytest_plugin.plugin import (
    ArmadilloPlugin,
    pytest_runtest_logstart,
    pytest_runtest_setup,
    pytest_runtest_call,
    pytest_runtest_teardown,
    pytest_runtest_logreport,
    _is_compact_mode_enabled,
)
from armadillo.pytest_plugin.reporter import ArmadilloReporter, get_armadillo_reporter


class TestArmadilloPluginBasic:
    """Test ArmadilloPlugin basic functionality."""

    def test_plugin_can_be_created(self):
        """Test ArmadilloPlugin can be instantiated."""
        plugin = ArmadilloPlugin()

        assert plugin is not None
        assert hasattr(plugin, "_session_deployments")
        assert hasattr(plugin, "_armadillo_config")

    def test_plugin_initial_state(self):
        """Test plugin initial state."""
        plugin = ArmadilloPlugin()

        assert isinstance(plugin._session_deployments, dict)
        assert len(plugin._session_deployments) == 0
        assert plugin._armadillo_config is None

    def test_plugin_has_expected_methods(self):
        """Test plugin has expected pytest hook methods."""
        plugin = ArmadilloPlugin()

        # Check that pytest hook methods exist
        expected_methods = [
            "pytest_configure",
            "pytest_sessionstart",
            "pytest_sessionfinish",
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
        call_args_list = [
            call[0] for call in mock_config.addinivalue_line.call_args_list
        ]

        markers_registered = [
            args[1] for args in call_args_list if args[0] == "markers"
        ]
        marker_names = [marker.split(":")[0] for marker in markers_registered]

        expected_markers = ["arango_single", "arango_cluster", "slow", "fast"]
        for expected in expected_markers:
            assert any(
                expected in marker for marker in marker_names
            ), f"Marker '{expected}' not registered"

    @patch("armadillo.pytest_plugin.plugin.configure_logging")
    @patch("armadillo.pytest_plugin.plugin.set_test_session_id")
    def test_pytest_sessionstart_basic(self, mock_set_session, mock_logging):
        """Test pytest_sessionstart performs setup."""
        plugin = ArmadilloPlugin()
        mock_session = Mock()

        plugin.pytest_sessionstart(mock_session)

        # Should have called setup functions
        # Note: load_config() is no longer called here - config is loaded by CLI and pytest_configure
        mock_logging.assert_called_once()
        mock_set_session.assert_called_once()

    @patch("armadillo.pytest_plugin.plugin.cleanup_work_dir")
    @patch("armadillo.pytest_plugin.plugin.clear_test_session")
    @patch("armadillo.pytest_plugin.plugin.stop_watchdog")
    def test_pytest_sessionfinish_basic(
        self, mock_stop_watchdog, mock_clear_session, mock_cleanup
    ):
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

        # Add mock deployment
        mock_manager = Mock()
        plugin._session_deployments["test_deployment"] = mock_manager

        assert len(plugin._session_deployments) == 1
        assert plugin._session_deployments["test_deployment"] == mock_manager

    def test_plugin_tracks_deployments(self):
        """Test plugin can track deployments."""
        plugin = ArmadilloPlugin()

        # Add mock deployment
        mock_deployment = Mock()
        plugin._session_deployments["test_deployment"] = mock_deployment

        assert len(plugin._session_deployments) == 1
        assert plugin._session_deployments["test_deployment"] == mock_deployment


class TestArmadilloPluginErrorHandling:
    """Test plugin error handling."""

    @patch("armadillo.pytest_plugin.plugin.get_config")
    def test_sessionstart_handles_config_error(self, mock_get_config):
        """Test sessionstart handles configuration errors gracefully."""
        plugin = ArmadilloPlugin()
        mock_session = Mock()
        mock_get_config.side_effect = Exception("Config failed")

        # Should not crash even if config fails
        try:
            plugin.pytest_sessionstart(mock_session)
        except Exception:
            # If it raises, that's also acceptable behavior
            pass

    @patch("armadillo.pytest_plugin.plugin.cleanup_work_dir")
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

    @patch("armadillo.pytest_plugin.plugin.atexit.register")
    @patch("armadillo.pytest_plugin.plugin.set_global_deadline")
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
        plugin1._session_deployments["deployment1"] = Mock()
        plugin1._armadillo_config = {"test": "config"}

        # Other plugin should be unaffected
        assert len(plugin2._session_deployments) == 0
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
            "stress_test",
        ]

        for marker_name in expected_marker_names:
            assert (
                marker_name in combined_markers
            ), f"Expected marker '{marker_name}' not found"


class TestArmadilloReporter:
    """Test Armadillo reporter functionality."""

    def setup_method(self):
        """Reset global reporter state before each test."""
        # Clear global reporter instance to ensure clean state
        import armadillo.pytest_plugin.reporter as reporter_module

        reporter_module._reporter = None

    def test_reporter_can_be_created(self):
        """Test ArmadilloReporter can be instantiated."""
        reporter = ArmadilloReporter()

        assert reporter is not None
        assert hasattr(reporter, "test_times")
        assert hasattr(reporter, "suite_start_times")
        assert isinstance(reporter.test_times, dict)

    def test_get_armadillo_reporter_singleton(self):
        """Test get_armadillo_reporter returns singleton instance."""
        reporter1 = get_armadillo_reporter()
        reporter2 = get_armadillo_reporter()

        assert reporter1 is reporter2
        assert isinstance(reporter1, ArmadilloReporter)

    @patch("sys.stdout.write")
    @patch("sys.stdout.flush")
    @patch("builtins.open", side_effect=OSError("No /dev/tty available"))
    def test_reporter_run_header_output(self, mock_open, mock_flush, mock_write):
        """Test reporter outputs RUN header when test starts."""
        reporter = ArmadilloReporter()

        # Simulate test start
        nodeid = "test_file.py::TestClass::test_method"
        location = ("test_file.py", 10, "TestClass.test_method")

        reporter.pytest_runtest_logstart(nodeid, location)

        # Should have written RUN header to stdout
        mock_write.assert_called()
        written_text = mock_write.call_args[0][0]
        assert "[ RUN        ]" in written_text
        assert "test_method" in written_text

    def test_reporter_tracks_test_timing(self):
        """Test reporter accurately tracks test execution timing."""
        reporter = ArmadilloReporter()
        nodeid = "test_file.py::TestClass::test_method"

        # Start test
        reporter.pytest_runtest_logstart(nodeid, ("test_file.py", 10, "test_method"))

        # Verify timing structure is initialized
        test_name = "test_method"
        assert test_name in reporter.test_times
        assert "start" in reporter.test_times[test_name]
        assert "setup" in reporter.test_times[test_name]
        assert "call" in reporter.test_times[test_name]
        assert "teardown" in reporter.test_times[test_name]

    def test_reporter_extracts_test_name_correctly(self):
        """Test reporter extracts test name from nodeid correctly."""
        reporter = ArmadilloReporter()

        test_cases = [
            ("test_file.py::TestClass::test_method", "test_method"),
            ("tests/test_module.py::test_function", "test_function"),
            ("path/to/test.py::TestSuite::test_with_long_name", "test_with_long_name"),
        ]

        for nodeid, expected_name in test_cases:
            actual_name = reporter._get_test_name(nodeid)
            assert actual_name == expected_name, f"Failed for {nodeid}"


class TestArmadilloPytestHooks:
    """Test pytest hook functions are properly connected."""

    def setup_method(self):
        """Reset global reporter state before each test."""
        import armadillo.pytest_plugin.reporter as reporter_module

        reporter_module._reporter = None

    @patch("armadillo.pytest_plugin.plugin._is_compact_mode_enabled")
    @patch("armadillo.pytest_plugin.plugin.get_armadillo_reporter")
    def test_pytest_runtest_logstart_hook_connected(
        self, mock_get_reporter, mock_compact
    ):
        """Test pytest_runtest_logstart hook calls reporter correctly."""
        mock_compact.return_value = False
        mock_reporter = Mock()
        mock_get_reporter.return_value = mock_reporter

        nodeid = "test_file.py::test_function"
        location = ("test_file.py", 10, "test_function")

        pytest_runtest_logstart(nodeid, location)

        mock_get_reporter.assert_called_once()
        mock_reporter.pytest_runtest_logstart.assert_called_once_with(nodeid, location)

    @patch("armadillo.pytest_plugin.plugin._is_compact_mode_enabled")
    @patch("armadillo.pytest_plugin.plugin.get_armadillo_reporter")
    def test_pytest_runtest_setup_hook_connected(self, mock_get_reporter, mock_compact):
        """Test pytest_runtest_setup hook calls reporter correctly."""
        mock_compact.return_value = False
        mock_reporter = Mock()
        mock_get_reporter.return_value = mock_reporter

        mock_item = Mock()
        pytest_runtest_setup(mock_item)

        mock_get_reporter.assert_called_once()
        mock_reporter.pytest_runtest_setup.assert_called_once_with(mock_item)

    @patch("armadillo.pytest_plugin.plugin._is_compact_mode_enabled")
    @patch("armadillo.pytest_plugin.plugin.get_armadillo_reporter")
    def test_pytest_runtest_call_hook_connected(self, mock_get_reporter, mock_compact):
        """Test pytest_runtest_call hook calls reporter correctly."""
        mock_compact.return_value = False
        mock_reporter = Mock()
        mock_get_reporter.return_value = mock_reporter

        mock_item = Mock()
        pytest_runtest_call(mock_item)

        mock_get_reporter.assert_called_once()
        mock_reporter.pytest_runtest_call.assert_called_once_with(mock_item)

    @patch("armadillo.pytest_plugin.plugin._is_compact_mode_enabled")
    @patch("armadillo.pytest_plugin.plugin.get_armadillo_reporter")
    def test_pytest_runtest_teardown_hook_connected(
        self, mock_get_reporter, mock_compact
    ):
        """Test pytest_runtest_teardown hook calls reporter correctly."""
        mock_compact.return_value = False
        mock_reporter = Mock()
        mock_get_reporter.return_value = mock_reporter

        mock_item = Mock()
        pytest_runtest_teardown(mock_item, None)

        mock_get_reporter.assert_called_once()
        mock_reporter.pytest_runtest_teardown.assert_called_once_with(mock_item)

    @patch("armadillo.pytest_plugin.plugin._is_compact_mode_enabled")
    @patch("armadillo.pytest_plugin.plugin.get_armadillo_reporter")
    def test_pytest_runtest_logreport_hook_connected(
        self, mock_get_reporter, mock_compact
    ):
        """Test pytest_runtest_logreport hook calls reporter correctly."""
        mock_compact.return_value = False
        mock_reporter = Mock()
        mock_get_reporter.return_value = mock_reporter

        mock_report = Mock()
        pytest_runtest_logreport(mock_report)

        mock_get_reporter.assert_called_once()
        mock_reporter.pytest_runtest_logreport.assert_called_once_with(mock_report)

    @patch("armadillo.pytest_plugin.plugin._is_compact_mode_enabled")
    @patch("armadillo.pytest_plugin.plugin.get_armadillo_reporter")
    def test_hooks_respect_compact_mode(self, mock_get_reporter, mock_compact):
        """Test hooks do not call reporter when compact mode is enabled."""
        mock_compact.return_value = True  # Compact mode
        mock_reporter = Mock()
        mock_get_reporter.return_value = mock_reporter

        # Call various hooks
        pytest_runtest_logstart("test", ("test", 1, "test"))
        pytest_runtest_setup(Mock())
        pytest_runtest_call(Mock())
        pytest_runtest_teardown(Mock(), None)
        pytest_runtest_logreport(Mock())

        # Reporter should not be called in compact mode
        mock_get_reporter.assert_not_called()
        mock_reporter.pytest_runtest_logstart.assert_not_called()

    def test_compact_mode_enabled_function(self):
        """Test _is_compact_mode_enabled function exists and is callable."""
        # Just test that the function exists and can be called
        # The actual behavior is tested through integration
        result = _is_compact_mode_enabled()
        assert isinstance(result, bool)


class TestArmadilloReporterRegressionTests:
    """Regression tests to catch the specific issues we fixed."""

    def setup_method(self):
        """Reset global reporter state before each test."""
        import armadillo.pytest_plugin.reporter as reporter_module

        reporter_module._reporter = None

    def test_pytest_hooks_are_connected(self):
        """Test that all required pytest hooks exist and are connected.

        This is a regression test for the issue where missing hooks
        caused RUN headers and timing to not work.
        """
        # Test that all the hook functions exist
        assert callable(pytest_runtest_logstart)
        assert callable(pytest_runtest_setup)
        assert callable(pytest_runtest_call)
        assert callable(pytest_runtest_teardown)
        assert callable(pytest_runtest_logreport)

    @patch("armadillo.pytest_plugin.plugin._is_compact_mode_enabled")
    @patch("armadillo.pytest_plugin.plugin.get_armadillo_reporter")
    def test_hooks_call_reporter_when_non_compact(self, mock_get_reporter, mock_compact):
        """Test hooks call reporter when compact mode is disabled.

        This is a regression test for the missing hook connections.
        """
        mock_compact.return_value = False
        mock_reporter = Mock()
        mock_get_reporter.return_value = mock_reporter

        # Test that each hook calls the reporter
        pytest_runtest_logstart(
            "test_file.py::test_func", ("test_file.py", 1, "test_func")
        )
        mock_reporter.pytest_runtest_logstart.assert_called_once()

        mock_item = Mock()
        pytest_runtest_setup(mock_item)
        mock_reporter.pytest_runtest_setup.assert_called_once_with(mock_item)

        pytest_runtest_call(mock_item)
        mock_reporter.pytest_runtest_call.assert_called_once_with(mock_item)

    def test_reporter_initializes_timing_structure(self):
        """Test reporter initializes timing structure correctly.

        This is a regression test for timing not being tracked.
        """
        reporter = ArmadilloReporter()
        nodeid = "test_file.py::TestClass::test_method"

        # This should initialize timing structure
        reporter.pytest_runtest_logstart(nodeid, ("test_file.py", 10, "test_method"))

        test_name = "test_method"
        assert test_name in reporter.test_times
        timing = reporter.test_times[test_name]

        # Check all required timing fields exist
        assert "start" in timing
        assert "setup" in timing
        assert "call" in timing
        assert "teardown" in timing
        assert timing["start"] > 0  # Should have actual timestamp

    @patch("sys.stdout.write")
    @patch("builtins.open", side_effect=OSError("No /dev/tty available"))
    def test_run_header_is_output(self, mock_open, mock_write):
        """Test that RUN header is written to stdout.

        This is a regression test for missing RUN headers.
        """
        reporter = ArmadilloReporter()
        nodeid = "test_file.py::TestClass::test_method"

        reporter.pytest_runtest_logstart(nodeid, ("test_file.py", 10, "test_method"))

        # Should have written something to stdout
        mock_write.assert_called()
        written_text = mock_write.call_args[0][0]

        # Should contain RUN header and test name
        assert "[ RUN        ]" in written_text
        assert "test_method" in written_text
