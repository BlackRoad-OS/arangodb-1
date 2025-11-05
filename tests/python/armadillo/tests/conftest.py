"""Pytest configuration for Armadillo integration tests.

This module provides common configuration for all test packages.

IMPORTANT: Do NOT define package-scoped fixtures here!
Package-scoped fixtures are scoped to where they're DEFINED, not where they're USED.
Defining them here would cause all subpackages to share the same instance.
Instead, use tests/conftest_helpers.py to create fixtures in each subpackage's conftest.py.
"""

import pytest


# Pytest markers for test organization
def pytest_configure(config):
    """Configure pytest markers for Armadillo tests."""
    config.addinivalue_line("markers", "shell_api: Tests for shell API functionality")
    config.addinivalue_line("markers", "statistics: Tests for statistics API endpoints")
    config.addinivalue_line(
        "markers", "admin_endpoints: Tests for administrative endpoints"
    )
    config.addinivalue_line(
        "markers", "converted_from_js: Tests converted from JavaScript framework"
    )
