"""Pytest configuration for Armadillo integration tests.

This module configures pytest to use the real Armadillo framework fixtures
for starting and managing ArangoDB servers.

The actual fixtures are provided by the Armadillo pytest plugin.
"""

import pytest

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
