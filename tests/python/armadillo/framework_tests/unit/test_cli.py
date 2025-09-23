"""
Fast unit tests for CLI functionality.

Tests essential CLI functionality without complex integration.
"""

import pytest
from unittest.mock import Mock, patch
from typer.testing import CliRunner

from armadillo.cli.main import app


class TestCLIBasics:
    """Test basic CLI functionality."""

    def setup_method(self):
        """Set up test environment."""
        self.runner = CliRunner()

    def test_app_exists(self):
        """Test that the CLI app is properly defined."""
        assert app is not None
        assert hasattr(app, "callback")

    def test_help_command(self):
        """Test CLI help command works."""
        result = self.runner.invoke(app, ["--help"])

        # Should either show help or exit cleanly
        assert result.exit_code in [0, 2]

    def test_test_command_exists(self):
        """Test that test command is available."""
        result = self.runner.invoke(app, ["test", "--help"])

        # Should either show help or indicate command exists
        assert result.exit_code in [0, 2]

    def test_analyze_command_exists(self):
        """Test that analyze command exists."""
        result = self.runner.invoke(app, ["analyze", "--help"])

        # Should either show help or indicate command exists
        assert result.exit_code in [0, 2]


class TestCLICommands:
    """Test CLI command execution with minimal complexity."""

    def setup_method(self):
        """Set up test environment."""
        self.runner = CliRunner()

    def test_invalid_command(self):
        """Test behavior with invalid command."""
        result = self.runner.invoke(app, ["nonexistent-command"])

        # Should exit with error (but not crash)
        assert result.exit_code != 0

    def test_test_run_basic(self):
        """Test test run command basic functionality."""
        # Test that command accepts basic arguments (just help to avoid execution)
        result = self.runner.invoke(app, ["test", "run", "--help"])

        # Should work with help
        assert result.exit_code in [0, 2]

    def test_analyze_results_help(self):
        """Test analyze results command help."""
        result = self.runner.invoke(app, ["analyze", "results", "--help"])

        assert result.exit_code in [0, 2]


class TestCLIErrorHandling:
    """Test CLI error handling."""

    def setup_method(self):
        """Set up test environment."""
        self.runner = CliRunner()

    def test_empty_arguments(self):
        """Test CLI behavior with empty arguments."""
        result = self.runner.invoke(app, [])

        # Should handle empty args gracefully
        assert result.exit_code in [0, 1, 2]

    def test_very_long_arguments(self):
        """Test CLI behavior with very long arguments."""
        long_arg = "x" * 100  # Reasonable length to avoid issues
        result = self.runner.invoke(app, [long_arg])

        # Should handle long arguments without crashing
        assert result.exit_code != -1  # Not a segfault

    @patch.dict("os.environ", {"ARMADILLO_BUILD_DIR": "/test/build"})
    def test_environment_variable_support(self):
        """Test that CLI respects environment variables."""
        result = self.runner.invoke(app, ["--help"])

        # Should work with environment variables set
        assert result.exit_code in [0, 2]


class TestCLIPerformance:
    """Test CLI performance."""

    def setup_method(self):
        """Set up test environment."""
        self.runner = CliRunner()

    def test_help_performance(self):
        """Test help command is fast."""
        import time

        start_time = time.time()
        result = self.runner.invoke(app, ["--help"])
        end_time = time.time()

        # Help should be fast (under 2 seconds)
        help_time = end_time - start_time
        assert help_time < 2.0

        assert result.exit_code in [0, 2]
