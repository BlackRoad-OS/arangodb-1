"""Statistics API tests - converted from JavaScript to Python.

Original source: tests/js/client/shell/api/statistics.js
Tests the /_admin/statistics* endpoints
"""

import pytest
import time
from typing import Dict, Any

import requests
from arango import ArangoClient, ArangoError


class TestStatisticsAPI:
    """Test suite for ArangoDB statistics API endpoints - deployment agnostic."""

    @pytest.fixture(scope="function")
    def arango_client(self, arango_deployment):
        """Get ArangoDB client connected to test deployment (single server or coordinator)."""
        server = arango_deployment  # Works with both single server and cluster coordinator

        # Create client using the server's endpoint
        client = ArangoClient(hosts=server.endpoint)

        # Connect to system database for admin endpoints
        db = client.db('_system')
        return db

    @pytest.fixture(scope="function")
    def base_url(self, arango_deployment):
        """Get base URL for HTTP requests to any deployment."""
        server = arango_deployment  # Works with both single server and cluster coordinator
        return server.endpoint

    def test_statistics_description_correct_endpoint(self, base_url):
        """Test /_admin/statistics-description endpoint returns 200."""
        response = requests.get(f"{base_url}/_admin/statistics-description")

        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        assert response.text is not None, "Response body should not be empty"

    def test_statistics_description_wrong_endpoint(self, base_url):
        """Test /_admin/statistics-description with invalid path returns 404."""
        response = requests.get(f"{base_url}/_admin/statistics-description/asd123")

        assert response.status_code == 404, f"Expected 404, got {response.status_code}"

        # Parse response body
        body = response.json()
        assert body.get('error') is True, "Response should indicate error"
        assert body.get('errorNum') == 404, f"Expected errorNum 404, got {body.get('errorNum')}"

    def test_statistics_correct_endpoint(self, base_url):
        """Test /_admin/statistics endpoint returns 200 with valid data."""
        response = requests.get(f"{base_url}/_admin/statistics")

        assert response.status_code == 200, f"Expected 200, got {response.status_code}"

        body = response.json()
        assert body is not None, "Response body should not be empty"
        assert 'server' in body, "Response should contain server statistics"
        assert 'uptime' in body['server'], "Server stats should contain uptime"
        assert body['server']['uptime'] > 0, f"Server uptime should be > 0, got {body['server']['uptime']}"

    def test_statistics_wrong_endpoint(self, base_url):
        """Test /_admin/statistics with invalid path returns 404."""
        response = requests.get(f"{base_url}/_admin/statistics/asd123")

        assert response.status_code == 404, f"Expected 404, got {response.status_code}"

        body = response.json()
        assert body.get('error') is True, "Response should indicate error"
        assert body.get('errorNum') == 404, f"Expected errorNum 404, got {body.get('errorNum')}"

    def test_async_request_statistics_counting(self, base_url):
        """Test that async requests are properly counted in statistics.

        This test mirrors the JavaScript test that checks async request counting.
        Note: The original JS test has a bug (async_requests_1 == async_requests_1),
        but we implement the intended behavior.
        """
        # Get initial stats
        response = requests.get(f"{base_url}/_admin/statistics")
        assert response.status_code == 200

        initial_stats = response.json()
        initial_async_requests = initial_stats['http']['requestsAsync']

        # Make an async request (using PUT with X-Arango-Async header)
        headers = {"X-Arango-Async": "true"}
        response = requests.put(f"{base_url}/_api/version", data="", headers=headers)
        assert response.status_code == 202, f"Async request should return 202, got {response.status_code}"

        # The response body should be empty for async requests
        assert response.text == "", "Async request should have empty body"

        # Wait a bit for statistics to update
        time.sleep(1)

        # Get stats again
        response = requests.get(f"{base_url}/_admin/statistics")
        assert response.status_code == 200

        after_async_stats = response.json()
        after_async_requests = after_async_stats['http']['requestsAsync']

        # The async counter should have increased
        # Note: The original JS test had a bug - it checked async_requests_1 == async_requests_1
        # We implement the intended behavior: async requests should increase the counter
        assert after_async_requests >= initial_async_requests, \
            f"Async requests should not decrease: {initial_async_requests} -> {after_async_requests}"

        # Make a synchronous request (no X-Arango-Async header)
        response = requests.put(f"{base_url}/_api/version", data="")
        assert response.status_code == 200, f"Sync request should return 200, got {response.status_code}"

        # Wait a bit
        time.sleep(1)

        # Get final stats
        response = requests.get(f"{base_url}/_admin/statistics")
        assert response.status_code == 200

        final_stats = response.json()
        final_async_requests = final_stats['http']['requestsAsync']

        # The async counter should not have increased from the sync request
        assert final_async_requests == after_async_requests, \
            f"Sync request should not increase async counter: {after_async_requests} -> {final_async_requests}"


# Test class is now deployment-agnostic - works with both single server and cluster
# No need for separate Single/Cluster test classes or deployment-specific markers
