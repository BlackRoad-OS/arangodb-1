#!/usr/bin/env python3
"""
Framework Test Runner

This script runs the unit tests for the Armadillo framework itself.
These tests are separate from integration tests that use the framework.

Usage:
    python run_framework_tests.py [pytest_args...]

Examples:
    python run_framework_tests.py                    # Run all framework tests
    python run_framework_tests.py -v                 # Verbose output
    python run_framework_tests.py -k test_crypto     # Run only crypto tests
    python run_framework_tests.py --cov=armadillo    # With coverage
"""

import sys
import subprocess
from pathlib import Path

def main():
    """Run framework tests using pytest."""

    # Change to the armadillo directory
    script_dir = Path(__file__).parent
    armadillo_dir = script_dir

    # Build pytest command
    pytest_args = [
        sys.executable, "-m", "pytest",
        "-c", str(armadillo_dir / "framework_tests" / "pytest.ini"),
        str(armadillo_dir / "framework_tests" / "unit"),
    ]

    # Add any additional arguments passed to this script
    if len(sys.argv) > 1:
        pytest_args.extend(sys.argv[1:])

    print(f"Running framework tests...")
    print(f"Command: {' '.join(pytest_args)}")
    print("-" * 60)

    # Run pytest
    try:
        result = subprocess.run(pytest_args, cwd=armadillo_dir)
        sys.exit(result.returncode)
    except KeyboardInterrupt:
        print("\nTest run interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"Error running tests: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
