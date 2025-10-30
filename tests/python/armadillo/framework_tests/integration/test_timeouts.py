"""Integration tests for timeout enforcement.

These tests verify that all three timeout modes work correctly:
1. Per-test timeout (via pytest-timeout)
2. Global timeout (via ArmadilloConfig.test_timeout)
3. Output-idle timeout (via output monitoring)
"""

import subprocess
import tempfile
import time
from pathlib import Path


def test_per_test_timeout_enforcement():
    """Verify per-test timeout kills individual slow tests."""
    # Create a temporary test file with a slow test
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "test_slow.py"
        test_file.write_text(
            """
import time

def test_sleeps_too_long():
    '''Test that sleeps longer than timeout.'''
    time.sleep(10)  # Sleep for 10 seconds
"""
        )

        # Run with 2 second per-test timeout
        result = subprocess.run(
            [
                "armadillo",
                "test",
                "run",
                str(tmpdir),
                "--timeout",
                "2",
                "--output-dir",
                f"{tmpdir}/results",
            ],
            capture_output=True,
            text=True,
            timeout=30,  # Overall timeout for this test
        )

        # Test should fail due to timeout
        assert result.returncode != 0, "Test should fail due to timeout"
        # pytest-timeout should indicate timeout in output
        assert "timeout" in result.stdout.lower() or "timeout" in result.stderr.lower()


def test_output_idle_timeout_enforcement():
    """Verify output-idle timeout kills tests that hang without output."""
    # Create a temporary test file with a hanging test
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "test_hang.py"
        test_file.write_text(
            """
import time
import sys

def test_hangs_silently():
    '''Test that hangs without producing output.'''
    sys.stdout.write("Starting test...\\n")
    sys.stdout.flush()
    # Now hang silently for a long time
    time.sleep(60)
"""
        )

        # Run with 3 second output-idle timeout
        result = subprocess.run(
            [
                "armadillo",
                "test",
                "run",
                str(tmpdir),
                "--output-idle-timeout",
                "3",
                "--output-dir",
                f"{tmpdir}/results",
            ],
            capture_output=True,
            text=True,
            timeout=30,  # Overall timeout for this test
        )

        # Test should fail/be killed due to idle timeout
        assert result.returncode != 0, "Test should fail due to output idle timeout"
        # Output should mention idle timeout
        output = result.stdout + result.stderr
        assert (
            "idle timeout" in output.lower() or "no output" in output.lower()
        ), f"Expected idle timeout message in output, got: {output}"


def test_no_false_positives_on_fast_tests():
    """Verify timeouts don't kill tests that finish quickly."""
    # Create a temporary test file with fast tests
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "test_fast.py"
        test_file.write_text(
            """
def test_fast_one():
    '''Quick test that finishes immediately.'''
    assert 1 + 1 == 2

def test_fast_two():
    '''Another quick test.'''
    assert "hello".upper() == "HELLO"
"""
        )

        # Run with reasonable timeouts
        result = subprocess.run(
            [
                "armadillo",
                "test",
                "run",
                str(tmpdir),
                "--timeout",
                "10",
                "--global-timeout",
                "30",
                "--output-idle-timeout",
                "10",
                "--output-dir",
                f"{tmpdir}/results",
            ],
            capture_output=True,
            text=True,
            timeout=60,  # Overall timeout for this test
        )

        # Tests should pass
        assert result.returncode == 0, f"Fast tests should pass, got: {result.stdout}"


def test_output_idle_timeout_resets_on_activity():
    """Verify output-idle timeout resets when test produces output."""
    # Create a test that produces output periodically
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "test_periodic_output.py"
        test_file.write_text(
            """
import time
import sys

def test_with_periodic_output():
    '''Test that produces output every 2 seconds.'''
    for i in range(3):
        sys.stdout.write(f"Progress {i}\\n")
        sys.stdout.flush()
        time.sleep(2)  # Sleep but keep outputting
"""
        )

        # Run with 5 second output-idle timeout (should be enough)
        result = subprocess.run(
            [
                "armadillo",
                "test",
                "run",
                str(tmpdir),
                "--output-idle-timeout",
                "5",
                "--output-dir",
                f"{tmpdir}/results",
            ],
            capture_output=True,
            text=True,
            timeout=30,  # Overall timeout for this test
        )

        # Test should pass because it produces output regularly
        assert (
            result.returncode == 0
        ), f"Test with periodic output should pass, got: {result.stdout}"


def test_global_timeout_enforcement():
    """Verify global timeout kills entire test session when exceeded."""
    # Create tests that collectively take too long
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "test_many_slow.py"
        test_file.write_text(
            """
import time

def test_slow_1():
    '''First slow test.'''
    time.sleep(3)

def test_slow_2():
    '''Second slow test.'''
    time.sleep(3)

def test_slow_3():
    '''Third slow test.'''
    time.sleep(3)
"""
        )

        # Run with 5 second global timeout (should kill before all tests finish)
        result = subprocess.run(
            [
                "armadillo",
                "test",
                "run",
                str(tmpdir),
                "--global-timeout",
                "5",
                "--output-dir",
                f"{tmpdir}/results",
            ],
            capture_output=True,
            text=True,
            timeout=30,  # Overall timeout for this test
        )

        # Should fail due to global timeout
        assert result.returncode != 0, "Test should fail due to global timeout"
        # Output should mention global timeout
        output = result.stdout + result.stderr
        assert (
            "global timeout" in output.lower() or "timeout" in output.lower()
        ), f"Expected global timeout message in output, got: {output}"

