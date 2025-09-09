"""Example tests demonstrating Armadillo framework usage."""

import pytest
import asyncio

# Example test using session-scoped server
@pytest.mark.arango_single
def test_server_health_session(arango_single_server):
    """Test server health with session-scoped server."""
    server = arango_single_server

    # Verify server is running
    assert server.is_running()

    # Check health synchronously
    health = server.health_check_sync(timeout=5.0)
    assert health.is_healthy, f"Health check failed: {health.error_message}"

    # Verify server info
    info = server.get_info()
    assert info.server_id == "test_single_server"
    assert info.port > 0
    assert info.endpoint.startswith("http://")


# Example test using function-scoped server
@pytest.mark.arango_single
def test_server_health_function(arango_single_server_function):
    """Test server health with function-scoped server."""
    server = arango_single_server_function

    # Verify server is running
    assert server.is_running()

    # Check health
    health = server.health_check_sync(timeout=5.0)
    assert health.is_healthy, f"Health check failed: {health.error_message}"


# Example async test
@pytest.mark.arango_single
@pytest.mark.asyncio
async def test_async_health_check(arango_single_server):
    """Test async health check."""
    server = arango_single_server

    # Perform async health check
    health = await server.health_check(timeout=5.0)
    assert health.is_healthy, f"Health check failed: {health.error_message}"

    # Check response time is reasonable
    assert health.response_time < 5.0


# Example test with custom marker
@pytest.mark.arango_single
@pytest.mark.slow
def test_long_running_operation(arango_single_server):
    """Example of a test marked as slow."""
    import time

    server = arango_single_server
    assert server.is_running()

    # Simulate a longer operation
    time.sleep(0.1)  # Keep it short for the example

    health = server.health_check_sync()
    assert health.is_healthy


# Example test that would be skipped without cluster support
@pytest.mark.arango_cluster
def test_cluster_operation():
    """This test would be skipped in Phase 1 since cluster support isn't implemented yet."""
    pytest.skip("Cluster support not implemented in Phase 1")


def test_basic_framework_functionality():
    """Test basic framework functionality without server."""
    from armadillo.core.types import DeploymentMode, ServerRole
    from armadillo.utils.crypto import random_id, sha256
    from armadillo.utils.codec import encode_json, decode_json

    # Test types
    assert DeploymentMode.SINGLE_SERVER.value == "single_server"
    assert ServerRole.SINGLE.value == "single"

    # Test crypto utilities
    rid = random_id(16)
    assert len(rid) == 16

    hash_val = sha256("test data")
    assert len(hash_val) == 64  # SHA256 hex length

    # Test codec
    test_data = {"key": "value", "number": 42}
    encoded = encode_json(test_data)
    decoded = decode_json(encoded)
    assert decoded == test_data

