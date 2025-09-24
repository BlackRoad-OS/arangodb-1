"""Pytest configuration for Armadillo integration tests.

This module provides common fixtures that depend on the Armadillo pytest plugin.
The plugin fixtures (arango_single_server, arango_cluster, etc.) are provided directly
by the plugin and don't need to be imported here.
"""

import pytest
from arango import ArangoClient

# Note: Plugin fixtures like arango_single_server, arango_cluster, etc. are automatically
# available when the plugin is loaded via pytest.ini or command line (-p armadillo.pytest_plugin.plugin)


# Common fixtures for all test suites
@pytest.fixture(scope="session")
def adb(arango_deployment):
    """ArangoDB _system database client (short alias)."""
    server = arango_deployment  # Works with both single server and cluster coordinator
    client = ArangoClient(hosts=server.endpoint)
    return client.db("_system")


@pytest.fixture(scope="session")
def base_url(arango_deployment):
    """Get base URL for HTTP requests to any deployment.

    Args:
        arango_deployment: The ArangoDB deployment (single server or cluster coordinator)

    Returns:
        str: Base URL for HTTP requests (e.g., "http://127.0.0.1:8529")
    """
    server = arango_deployment  # Works with both single server and cluster coordinator
    return server.endpoint


# Pytest markers for test organization
def pytest_configure(config):
    """Configure pytest markers for Armadillo tests."""
    # These markers should integrate with our TestSelector
    config.addinivalue_line("markers", "shell_api: Tests for shell API functionality")
    config.addinivalue_line("markers", "statistics: Tests for statistics API endpoints")
    config.addinivalue_line(
        "markers", "admin_endpoints: Tests for administrative endpoints"
    )
    config.addinivalue_line(
        "markers", "converted_from_js: Tests converted from JavaScript framework"
    )
