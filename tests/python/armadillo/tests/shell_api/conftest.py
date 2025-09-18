"""Pytest configuration for shell_api test suite.

This module provides common fixtures for all shell_api tests,
including ArangoDB client setup and endpoint configuration.
"""

import pytest
from arango import ArangoClient


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
