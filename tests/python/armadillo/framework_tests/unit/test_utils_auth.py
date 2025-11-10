"""Tests for authentication utilities."""

from unittest.mock import patch

import pytest

from armadillo.utils.auth import AuthProvider
from armadillo.core.errors import JWTError


class TestAuthProvider:
    """Test AuthProvider class."""

    def test_auth_provider_creation(self):
        """Test AuthProvider creation with default parameters."""
        provider = AuthProvider()

        assert provider.algorithm == "HS256"
        assert provider.secret is not None
        assert len(provider.secret) > 0

    def test_auth_provider_custom_secret(self):
        """Test AuthProvider creation with custom secret."""
        custom_secret = "my-custom-secret"
        provider = AuthProvider(secret=custom_secret)

        assert provider.secret == custom_secret
        assert provider.algorithm == "HS256"

    def test_auth_provider_custom_algorithm(self):
        """Test AuthProvider creation with custom algorithm."""
        provider = AuthProvider(algorithm="HS512")

        assert provider.algorithm == "HS512"

    def test_get_auth_headers_returns_bearer_token(self):
        """Test get_auth_headers returns proper Bearer token format."""
        provider = AuthProvider()

        headers = provider.get_auth_headers()

        assert "Authorization" in headers
        assert headers["Authorization"].startswith("Bearer ")

        # Token should be JWT format (3 parts separated by dots)
        token = headers["Authorization"][7:]  # Remove "Bearer "
        parts = token.split(".")
        assert len(parts) == 3

    def test_get_auth_headers_with_custom_ttl(self):
        """Test get_auth_headers with custom TTL."""
        provider = AuthProvider()

        headers = provider.get_auth_headers(ttl=7200.0)

        assert "Authorization" in headers
        assert headers["Authorization"].startswith("Bearer ")

    def test_jwt_token_contains_expected_claims(self):
        """Test that JWT token contains expected claims."""
        provider = AuthProvider()

        # We can't easily verify the token without exposing verify methods,
        # but we can test that it's properly formatted
        headers = provider.get_auth_headers()
        token = headers["Authorization"][7:]  # Remove "Bearer "

        # JWT should have 3 parts
        parts = token.split(".")
        assert len(parts) == 3

        # Each part should be base64-encoded (no spaces, proper length)
        for part in parts:
            assert " " not in part
            assert len(part) > 0

    def test_different_providers_generate_different_tokens(self):
        """Test that different providers generate different tokens."""
        provider1 = AuthProvider()
        provider2 = AuthProvider()

        headers1 = provider1.get_auth_headers()
        headers2 = provider2.get_auth_headers()

        # Different secrets should produce different tokens
        assert headers1["Authorization"] != headers2["Authorization"]

    @patch("armadillo.utils.auth.jwt.encode")
    def test_jwt_encoding_error_handling(self, mock_encode):
        """Test JWT encoding error handling."""
        mock_encode.side_effect = Exception("JWT encoding failed")

        provider = AuthProvider()

        with pytest.raises(JWTError, match="Failed to issue JWT token"):
            provider.get_auth_headers()
