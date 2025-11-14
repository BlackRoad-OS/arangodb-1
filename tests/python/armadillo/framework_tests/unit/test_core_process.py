"""
Minimal unit tests for core/process.py that work without issues.

Only tests the most essential functionality to verify basic operation.
"""

import pytest
from unittest.mock import Mock, patch
from pathlib import Path

from armadillo.core.process import ProcessSupervisor
from armadillo.core.errors import ProcessStartupError
from armadillo.core.value_objects import ServerId


class TestProcessSupervisorMinimal:
    """Test ProcessSupervisor minimal functionality."""

    def setup_method(self) -> None:
        """Set up test environment."""
        self.supervisor = ProcessSupervisor()

    def test_is_running_nonexistent_process(self) -> None:
        """Test checking if nonexistent process is running."""
        assert self.supervisor.is_running(ServerId("nonexistent")) is False

    def test_stop_nonexistent_process_safe(self) -> None:
        """Test stopping nonexistent process doesn't crash."""
        # Should not raise error
        try:
            self.supervisor.stop(ServerId("nonexistent"))
        except Exception:
            pytest.fail("stop() should handle nonexistent processes gracefully")


class TestBasicIntegration:
    """Test basic integration scenarios."""

    def setup_method(self) -> None:
        """Set up test environment."""
        self.supervisor = ProcessSupervisor()

    def test_supervisor_handles_nonexistent_process(self) -> None:
        """Test supervisor handles queries for nonexistent processes correctly."""
        # Should work with nonexistent processes
        assert self.supervisor.is_running(ServerId("nonexistent")) is False
        processes = self.supervisor.list_processes()
        assert isinstance(processes, list)
