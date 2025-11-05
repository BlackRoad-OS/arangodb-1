"""Helper utilities for creating package-scoped fixtures in test packages.

Each test package should have its own conftest.py that calls these helpers
to create package-scoped fixtures. This avoids code duplication while ensuring
proper fixture scoping (plugin fixtures don't scope per-package correctly).

Example usage in tests/mypackage/conftest.py:
    from tests.conftest_helpers import create_package_fixtures

    _package_deployment, adb, base_url = create_package_fixtures(__file__)
"""

import pytest
from pathlib import Path
from arango import ArangoClient


def create_package_fixtures(conftest_file: str):
    """Create all standard package-scoped fixtures for a test package.

    This function returns fixture functions that should be assigned in the
    package's conftest.py file. This pattern allows us to reuse fixture
    implementation while ensuring proper pytest scoping.

    Args:
        conftest_file: The __file__ variable from the calling conftest.py

    Returns:
        tuple: (_package_deployment, adb, base_url) fixture functions

    Example:
        # In tests/mypackage/conftest.py:
        from tests.conftest_helpers import create_package_fixtures

        _package_deployment, adb, base_url = create_package_fixtures(__file__)
    """
    package_name = Path(conftest_file).parent.name

    @pytest.fixture(scope="package")
    def _package_deployment():
        """Create a deployment for this package only."""
        from armadillo.pytest_plugin.plugin import create_package_deployment

        yield from create_package_deployment(package_name)

    @pytest.fixture(scope="package")
    def adb(_package_deployment):
        """ArangoDB _system database client for this package."""
        client = ArangoClient(hosts=_package_deployment.endpoint)
        return client.db("_system")

    @pytest.fixture(scope="package")
    def base_url(_package_deployment):
        """Base URL for HTTP requests for this package."""
        return _package_deployment.endpoint

    return _package_deployment, adb, base_url
