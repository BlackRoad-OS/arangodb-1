"""Pytest configuration and fixtures for Armadillo integration tests.

This module provides pytest fixtures that integrate with the Armadillo framework
to provide ArangoDB server instances for testing.
"""

import pytest
from typing import NamedTuple
from dataclasses import dataclass

# Import Armadillo framework components would go here when available
# from armadillo.pytest_plugin import armadillo_pytest_plugin


class ServerInfo(NamedTuple):
    """Information about a running ArangoDB server instance."""
    host: str
    port: int
    endpoint: str
    database: str = "_system"


@dataclass
class ClusterInfo:
    """Information about a running ArangoDB cluster."""
    coordinators: list[ServerInfo]
    dbservers: list[ServerInfo]
    agents: list[ServerInfo]

    @property
    def coordinator_endpoints(self) -> list[str]:
        """Get list of coordinator endpoints."""
        return [coord.endpoint for coord in self.coordinators]

    @property
    def primary_coordinator(self) -> ServerInfo:
        """Get the primary coordinator for client connections."""
        return self.coordinators[0]


@pytest.fixture(scope="session")
def armadillo_single_server():
    """Provide a single ArangoDB server instance for the entire test session.

    This fixture integrates with the Armadillo framework to start and manage
    an ArangoDB server instance.

    Returns:
        ServerInfo: Information about the running server
    """
    # This would typically be handled by the Armadillo pytest plugin
    # For now, we'll create a mock implementation that expects a running server

    # In production, this would:
    # 1. Use Armadillo framework to start a server
    # 2. Wait for it to be ready
    # 3. Return connection info
    # 4. Clean up on teardown

    # For now, assume server is running on default port
    server_info = ServerInfo(
        host="127.0.0.1",
        port=8529,
        endpoint="http://127.0.0.1:8529",
        database="_system"
    )

    yield server_info

    # Cleanup would happen here


@pytest.fixture(scope="function")
def arango_single_server(armadillo_single_server):
    """Provide a single ArangoDB server instance for individual test functions.

    This fixture provides the same server as armadillo_single_server but with
    function scope, allowing for per-test setup/teardown if needed.

    Returns:
        ServerInfo: Information about the running server
    """
    return armadillo_single_server


@pytest.fixture(scope="session")
def armadillo_cluster():
    """Provide an ArangoDB cluster for the entire test session.

    This fixture integrates with the Armadillo framework to start and manage
    an ArangoDB cluster with coordinators, DB servers, and agents.

    Returns:
        ClusterInfo: Information about the running cluster
    """
    # This would be handled by the Armadillo framework
    # For now, create a mock implementation

    coordinators = [
        ServerInfo("127.0.0.1", 8529, "http://127.0.0.1:8529"),
        ServerInfo("127.0.0.1", 8539, "http://127.0.0.1:8539"),
        ServerInfo("127.0.0.1", 8549, "http://127.0.0.1:8549"),
    ]

    dbservers = [
        ServerInfo("127.0.0.1", 8530, "http://127.0.0.1:8530"),
        ServerInfo("127.0.0.1", 8540, "http://127.0.0.1:8540"),
    ]

    agents = [
        ServerInfo("127.0.0.1", 8531, "http://127.0.0.1:8531"),
        ServerInfo("127.0.0.1", 8541, "http://127.0.0.1:8541"),
        ServerInfo("127.0.0.1", 8551, "http://127.0.0.1:8551"),
    ]

    cluster_info = ClusterInfo(
        coordinators=coordinators,
        dbservers=dbservers,
        agents=agents
    )

    yield cluster_info

    # Cleanup would happen here


@pytest.fixture(scope="function")
def arango_cluster(armadillo_cluster):
    """Provide an ArangoDB cluster for individual test functions.

    This fixture provides the same cluster as armadillo_cluster but with
    function scope.

    Returns:
        ClusterInfo: Information about the running cluster
    """
    return armadillo_cluster


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
