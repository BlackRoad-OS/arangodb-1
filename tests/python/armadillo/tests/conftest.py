"""Pytest configuration for Armadillo integration tests.

This module configures pytest to use the real Armadillo framework fixtures
for starting and managing ArangoDB servers.

The actual fixtures are provided by the Armadillo pytest plugin.
"""

import pytest
from arango import ArangoClient

# Import the real Armadillo pytest plugin
from armadillo.pytest_plugin.plugin import (
    arango_single_server,
    arango_single_server_function,
    arango_cluster,
    arango_cluster_function,
    arango_coordinators,
    arango_dbservers,
    arango_agents,
    arango_orchestrator,
)


# Common fixtures for all test suites
@pytest.fixture(scope="function")
def arango_client(arango_deployment):
    """Get ArangoDB client connected to test deployment (single server or coordinator).

    Args:
        arango_deployment: The ArangoDB deployment (single server or cluster coordinator)

    Returns:
        ArangoDatabase: Connected to _system database for admin endpoints
    """
    server = arango_deployment  # Works with both single server and cluster coordinator

    # Create client using the server's endpoint
    client = ArangoClient(hosts=server.endpoint)

    # Connect to system database for admin endpoints
    db = client.db('_system')
    return db


@pytest.fixture(scope="function")
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
    config.addinivalue_line(
        "markers",
        "shell_api: Tests for shell API functionality"
    )
    config.addinivalue_line(
        "markers",
        "statistics: Tests for statistics API endpoints"
    )
    config.addinivalue_line(
        "markers",
        "admin_endpoints: Tests for administrative endpoints"
    )
    config.addinivalue_line(
        "markers",
        "converted_from_js: Tests converted from JavaScript framework"
    )
