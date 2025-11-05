"""Pytest configuration for shell_api test package."""

from tests.conftest_helpers import create_package_fixtures

# Create package-scoped fixtures: _package_deployment, adb, base_url
_package_deployment, adb, base_url = create_package_fixtures(__file__)
