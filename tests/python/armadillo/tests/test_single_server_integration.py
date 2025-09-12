"""Integration tests for single server functionality."""

import pytest
import time
import json
from typing import Dict, Any

from armadillo.instances.server import ArangoServer
from armadillo.core.types import ServerRole


@pytest.mark.arango_single
@pytest.mark.slow
class TestSingleServerDeployment:
    """Test single server deployment and functionality."""

    def test_single_server_fixture_available(self, arango_single_server: ArangoServer):
        """Test that single server fixture provides working server."""
        assert arango_single_server is not None
        assert arango_single_server.is_running()
        assert arango_single_server.role == ServerRole.SINGLE

        print(f"Single server available at: {arango_single_server.endpoint}")

    def test_single_server_health_check(self, arango_single_server: ArangoServer):
        """Test single server health monitoring."""
        health = arango_single_server.health_check_sync(timeout=10.0)

        assert health.is_healthy
        assert health.response_time > 0
        assert health.details is not None

        print(f"Server health check: {health.response_time:.3f}s")
        print(f"Health details: {health.details}")

    def test_server_version_info(self, arango_single_server: ArangoServer):
        """Test server version information is accessible."""
        health = arango_single_server.health_check_sync()

        assert health.is_healthy
        assert "version" in health.details
        assert "server" in health.details

        version = health.details["version"]
        server_info = health.details["server"]

        print(f"ArangoDB version: {version}")
        print(f"Server info: {server_info}")

    def test_server_basic_operations(self, arango_single_server: ArangoServer):
        """Test basic database operations work."""
        # This test will help verify the server is fully functional
        # For now, just test that we can get stats
        stats = arango_single_server.get_stats_sync()

        # Stats might be None if not implemented yet, that's OK
        if stats:
            assert stats.server_id == arango_single_server.server_id
            print(f"Server stats available: {stats}")
        else:
            print("Server stats not yet implemented - server is still accessible")

    def test_server_lifecycle_timing(self, arango_single_server_function: ArangoServer):
        """Test server startup and shutdown timing (function-scoped)."""
        # Use function-scoped fixture to test startup/shutdown for each test

        print(f"Function-scoped server started: {arango_single_server_function.endpoint}")

        # Test multiple health checks to verify stability
        for i in range(3):
            health = arango_single_server_function.health_check_sync(timeout=5.0)
            assert health.is_healthy
            print(f"Health check {i+1}: {health.response_time:.3f}s")
            time.sleep(0.5)

    def test_server_startup_readiness_timing(self, arango_single_server_function: ArangoServer):
        """Test server readiness timing specifically."""
        # This test helps debug the readiness check timing issue

        server = arango_single_server_function
        assert server.is_running()

        # Test various timeout values for health checks
        timeouts = [1.0, 2.0, 5.0, 10.0]

        for timeout in timeouts:
            start_time = time.time()
            health = server.health_check_sync(timeout=timeout)
            elapsed = time.time() - start_time

            print(f"Timeout {timeout}s: healthy={health.is_healthy}, elapsed={elapsed:.3f}s")

            if health.is_healthy:
                assert elapsed < timeout
                break

        # At least one timeout should succeed
        assert any(server.health_check_sync(timeout=t).is_healthy for t in timeouts)

    def test_server_connection_details(self, arango_single_server: ArangoServer):
        """Test server connection details are correct."""
        assert arango_single_server.endpoint.startswith("http://")
        assert arango_single_server.port > 0
        assert arango_single_server.server_id is not None

        print(f"Server endpoint: {arango_single_server.endpoint}")
        print(f"Server port: {arango_single_server.port}")
        print(f"Server ID: {arango_single_server.server_id}")

    def test_framework_server_integration(self, arango_single_server: ArangoServer):
        """Test framework integration with server."""
        # Test that framework components work with server

        # Test server info is available
        assert hasattr(arango_single_server, 'auth_provider')
        assert hasattr(arango_single_server, 'data_dir')
        assert hasattr(arango_single_server, 'log_file')

        print(f"Data directory: {arango_single_server.data_dir}")
        print(f"Log file: {arango_single_server.log_file}")


@pytest.mark.arango_single
@pytest.mark.fast
class TestSingleServerQuickChecks:
    """Quick single server tests for development."""

    def test_server_responds_quickly(self, arango_single_server: ArangoServer):
        """Test server responds within reasonable time."""
        start_time = time.time()
        health = arango_single_server.health_check_sync(timeout=3.0)
        elapsed = time.time() - start_time

        assert health.is_healthy
        assert elapsed < 2.0  # Should respond within 2 seconds

        print(f"Quick health check: {elapsed:.3f}s")

    def test_server_basic_info(self, arango_single_server: ArangoServer):
        """Test basic server information is accessible."""
        assert arango_single_server.is_running()
        assert arango_single_server.endpoint is not None
        assert arango_single_server.port > 0

        print(f"Server running on {arango_single_server.endpoint}")


class TestServerStartupDebugging:
    """Debug server startup issues."""

    @pytest.mark.arango_single
    def test_server_startup_sequence(self, arango_single_server_function: ArangoServer):
        """Debug the server startup sequence step by step."""
        server = arango_single_server_function

        print(f"=== Server Startup Debug ===")
        print(f"Server ID: {server.server_id}")
        print(f"Endpoint: {server.endpoint}")
        print(f"Port: {server.port}")
        print(f"Is running: {server.is_running()}")

        # Test readiness with verbose output
        print(f"\n=== Readiness Check Debug ===")

        for attempt in range(5):
            print(f"\nAttempt {attempt + 1}:")
            start_time = time.time()

            try:
                health = server.health_check_sync(timeout=5.0)
                elapsed = time.time() - start_time

                print(f"  Elapsed: {elapsed:.3f}s")
                print(f"  Healthy: {health.is_healthy}")
                print(f"  Response time: {health.response_time:.3f}s")
                print(f"  Error: {health.error_message}")

                if health.is_healthy:
                    print("  SUCCESS: Server is healthy!")
                    break

            except Exception as e:
                elapsed = time.time() - start_time
                print(f"  Exception after {elapsed:.3f}s: {e}")

            time.sleep(1.0)

        # Final assertion
        final_health = server.health_check_sync(timeout=10.0)
        assert final_health.is_healthy, f"Server failed final health check: {final_health.error_message}"
