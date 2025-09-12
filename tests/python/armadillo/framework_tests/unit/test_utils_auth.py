"""Tests for authentication utilities."""

import pytest
import time
import jwt
from unittest.mock import patch, Mock

from armadillo.utils.auth import (
    AuthProvider, BasicAuthProvider,
    get_auth_provider, get_basic_auth_provider,
    issue_jwt, verify_jwt, authorization_header
)
from armadillo.core.errors import JWTError, AuthenticationError


class TestAuthProvider:
    """Test AuthProvider class for JWT authentication."""

    def test_auth_provider_creation_default(self):
        """Test AuthProvider creation with default parameters."""
        provider = AuthProvider()

        assert provider.algorithm == "HS256"
        assert provider.secret is not None
        assert len(provider.secret) > 0

    def test_auth_provider_creation_custom(self):
        """Test AuthProvider creation with custom parameters."""
        secret = "test_secret_key"
        provider = AuthProvider(secret, "HS512")

        assert provider.algorithm == "HS512"
        assert provider.secret == secret

    def test_issue_jwt_default(self):
        """Test JWT token issuance with default parameters."""
        provider = AuthProvider("test_secret")

        token = provider.issue_jwt()

        assert isinstance(token, str)
        assert len(token) > 0

        # Should be valid JWT format (3 parts separated by dots)
        parts = token.split('.')
        assert len(parts) == 3

    def test_issue_jwt_custom_ttl(self):
        """Test JWT token issuance with custom TTL."""
        provider = AuthProvider("test_secret")

        token = provider.issue_jwt(ttl=3600.0)

        # Decode without verification to check claims
        payload = jwt.decode(token, options={"verify_signature": False})

        assert 'exp' in payload
        assert 'iat' in payload
        assert payload['iss'] == 'armadillo'

        # Check TTL is approximately correct
        exp_time = payload['exp']
        iat_time = payload['iat']
        ttl = exp_time - iat_time
        assert 3590 <= ttl <= 3610  # Allow for small timing differences

    def test_issue_jwt_with_custom_claims(self):
        """Test JWT token issuance with custom claims."""
        provider = AuthProvider("test_secret")

        custom_claims = {
            'user_id': 'test_user',
            'role': 'admin',
            'permissions': ['read', 'write']
        }

        token = provider.issue_jwt(claims=custom_claims)

        # Decode without verification to check claims
        payload = jwt.decode(token, options={"verify_signature": False})

        assert payload['user_id'] == 'test_user'
        assert payload['role'] == 'admin'
        assert payload['permissions'] == ['read', 'write']
        assert payload['iss'] == 'armadillo'  # Should still have issuer

    def test_verify_jwt_valid_token(self):
        """Test JWT token verification with valid token."""
        provider = AuthProvider("test_secret")

        token = provider.issue_jwt(ttl=60.0, claims={'test': 'value'})

        payload = provider.verify_jwt(token)

        assert payload['test'] == 'value'
        assert payload['iss'] == 'armadillo'
        assert 'exp' in payload
        assert 'iat' in payload

    def test_verify_jwt_expired_token(self):
        """Test JWT token verification with expired token."""
        provider = AuthProvider("test_secret")

        # Create token that expires immediately
        token = provider.issue_jwt(ttl=0.01)

        # Wait for token to expire
        time.sleep(0.02)

        with pytest.raises(JWTError, match="JWT token has expired"):
            provider.verify_jwt(token)

    def test_verify_jwt_invalid_signature(self):
        """Test JWT token verification with invalid signature."""
        provider1 = AuthProvider("secret1")
        provider2 = AuthProvider("secret2")

        token = provider1.issue_jwt()

        # Try to verify with different secret
        with pytest.raises(JWTError, match="Invalid JWT token"):
            provider2.verify_jwt(token)

    def test_verify_jwt_malformed_token(self):
        """Test JWT token verification with malformed token."""
        provider = AuthProvider("test_secret")

        with pytest.raises(JWTError, match="Invalid JWT token"):
            provider.verify_jwt("not.a.valid.jwt.token")

    def test_authorization_header(self):
        """Test authorization header generation."""
        provider = AuthProvider("test_secret")

        headers = provider.authorization_header()

        assert 'Authorization' in headers
        auth_value = headers['Authorization']
        assert auth_value.startswith('Bearer ')

        # Extract token and verify it's valid
        token = auth_value[7:]  # Remove "Bearer " prefix
        payload = provider.verify_jwt(token)
        assert payload['iss'] == 'armadillo'

    def test_get_auth_headers(self):
        """Test get_auth_headers method (alias for authorization_header)."""
        provider = AuthProvider("test_secret")

        headers1 = provider.authorization_header()
        headers2 = provider.get_auth_headers()

        # Should be identical functionality
        assert 'Authorization' in headers1
        assert 'Authorization' in headers2

    def test_is_token_expired(self):
        """Test token expiration check without raising exceptions."""
        provider = AuthProvider("test_secret")

        # Valid token
        valid_token = provider.issue_jwt(ttl=60.0)
        assert not provider.is_token_expired(valid_token)

        # Expired token
        expired_token = provider.issue_jwt(ttl=0.01)
        time.sleep(0.02)
        assert provider.is_token_expired(expired_token)

        # Invalid token
        assert provider.is_token_expired("invalid.token")

    def test_get_token_claims_without_verification(self):
        """Test getting token claims without signature verification."""
        provider = AuthProvider("test_secret")

        claims = {'user': 'test', 'role': 'admin'}
        token = provider.issue_jwt(claims=claims)

        extracted_claims = provider.get_token_claims(token)

        assert extracted_claims is not None
        assert extracted_claims['user'] == 'test'
        assert extracted_claims['role'] == 'admin'

        # Should work even with wrong secret
        provider2 = AuthProvider("wrong_secret")
        extracted_claims2 = provider2.get_token_claims(token)
        assert extracted_claims2['user'] == 'test'

    def test_get_token_claims_invalid_token(self):
        """Test getting claims from invalid token."""
        provider = AuthProvider("test_secret")

        result = provider.get_token_claims("invalid.token")
        assert result is None

    def test_refresh_token(self):
        """Test token refresh functionality."""
        provider = AuthProvider("test_secret")

        original_claims = {'user': 'test', 'role': 'user'}
        original_token = provider.issue_jwt(ttl=60.0, claims=original_claims)

        # Refresh with new TTL
        new_token = provider.refresh_token(original_token, 120.0)

        # New token should have same claims but different timing
        new_payload = provider.verify_jwt(new_token)
        assert new_payload['user'] == 'test'
        assert new_payload['role'] == 'user'

        # Should have new expiration time
        original_payload = provider.verify_jwt(original_token)
        assert new_payload['exp'] != original_payload['exp']
        # iat times may be the same if refresh happens very quickly - that's acceptable
        assert new_payload['iat'] >= original_payload['iat']

    def test_refresh_token_expired(self):
        """Test refreshing an expired token."""
        provider = AuthProvider("test_secret")

        expired_token = provider.issue_jwt(ttl=0.01)
        time.sleep(0.02)

        with pytest.raises(JWTError):
            provider.refresh_token(expired_token)

    def test_refresh_token_invalid(self):
        """Test refreshing an invalid token."""
        provider = AuthProvider("test_secret")

        with pytest.raises(JWTError):
            provider.refresh_token("invalid.token")


class TestBasicAuthProvider:
    """Test BasicAuthProvider for basic authentication."""

    def test_basic_auth_provider_creation(self):
        """Test BasicAuthProvider creation."""
        provider = BasicAuthProvider("testuser", "testpass")

        assert provider.username == "testuser"
        assert provider.password == "testpass"

    def test_basic_auth_provider_defaults(self):
        """Test BasicAuthProvider with default values."""
        provider = BasicAuthProvider()

        assert provider.username == "root"
        assert provider.password == ""

    def test_get_auth_headers(self):
        """Test basic auth header generation."""
        provider = BasicAuthProvider("testuser", "testpass")

        headers = provider.get_auth_headers()

        assert 'Authorization' in headers
        auth_value = headers['Authorization']
        assert auth_value.startswith('Basic ')

        # Decode and verify
        import base64
        encoded = auth_value[6:]  # Remove "Basic " prefix
        decoded = base64.b64decode(encoded).decode()
        assert decoded == "testuser:testpass"

    def test_get_auth_headers_empty_password(self):
        """Test basic auth with empty password."""
        provider = BasicAuthProvider("root", "")

        headers = provider.get_auth_headers()

        import base64
        auth_value = headers['Authorization']
        encoded = auth_value[6:]
        decoded = base64.b64decode(encoded).decode()
        assert decoded == "root:"


class TestGlobalAuthFunctions:
    """Test global authentication functions."""

    def test_get_auth_provider_singleton(self):
        """Test get_auth_provider returns singleton."""
        provider1 = get_auth_provider()
        provider2 = get_auth_provider()

        assert provider1 is provider2

    def test_get_auth_provider_custom_params(self):
        """Test get_auth_provider with custom parameters."""
        # Reset global provider
        import armadillo.utils.auth
        armadillo.utils.auth._auth_provider = None

        provider = get_auth_provider("custom_secret", "HS512")

        assert provider.secret == "custom_secret"
        assert provider.algorithm == "HS512"

    def test_get_basic_auth_provider_singleton(self):
        """Test get_basic_auth_provider returns singleton."""
        provider1 = get_basic_auth_provider()
        provider2 = get_basic_auth_provider()

        assert provider1 is provider2

    def test_get_basic_auth_provider_custom_params(self):
        """Test get_basic_auth_provider with custom parameters."""
        # Reset global provider
        import armadillo.utils.auth
        armadillo.utils.auth._basic_auth_provider = None

        provider = get_basic_auth_provider("admin", "password")

        assert provider.username == "admin"
        assert provider.password == "password"

    def test_issue_jwt_function(self):
        """Test global issue_jwt function."""
        with patch('armadillo.utils.auth.get_auth_provider') as mock_get:
            mock_provider = Mock()
            mock_provider.issue_jwt.return_value = "test.jwt.token"
            mock_get.return_value = mock_provider

            result = issue_jwt(120.0, {'test': 'claim'})

            mock_provider.issue_jwt.assert_called_once_with(120.0, {'test': 'claim'})
            assert result == "test.jwt.token"

    def test_verify_jwt_function(self):
        """Test global verify_jwt function."""
        with patch('armadillo.utils.auth.get_auth_provider') as mock_get:
            mock_provider = Mock()
            mock_provider.verify_jwt.return_value = {'user': 'test'}
            mock_get.return_value = mock_provider

            result = verify_jwt("test.jwt.token")

            mock_provider.verify_jwt.assert_called_once_with("test.jwt.token")
            assert result == {'user': 'test'}

    def test_authorization_header_function(self):
        """Test global authorization_header function."""
        with patch('armadillo.utils.auth.get_auth_provider') as mock_get:
            mock_provider = Mock()
            mock_provider.authorization_header.return_value = {'Authorization': 'Bearer token'}
            mock_get.return_value = mock_provider

            result = authorization_header(60.0)

            mock_provider.authorization_header.assert_called_once_with(60.0)
            assert result == {'Authorization': 'Bearer token'}


class TestAuthEdgeCases:
    """Test authentication edge cases and error conditions."""

    def test_jwt_with_special_characters_in_claims(self):
        """Test JWT with special characters in claims."""
        provider = AuthProvider("test_secret")

        claims = {
            'unicode': 'Hello 世界!',
            'symbols': '!@#$%^&*()',
            'whitespace': '  spaced  ',
            'newlines': 'line1\nline2'
        }

        token = provider.issue_jwt(claims=claims)
        payload = provider.verify_jwt(token)

        assert payload['unicode'] == 'Hello 世界!'
        assert payload['symbols'] == '!@#$%^&*()'
        assert payload['whitespace'] == '  spaced  '
        assert payload['newlines'] == 'line1\nline2'

    def test_jwt_with_large_payload(self):
        """Test JWT with large payload."""
        provider = AuthProvider("test_secret")

        # Create large claims
        large_claim = "x" * 10000
        claims = {'large_data': large_claim}

        token = provider.issue_jwt(claims=claims)
        payload = provider.verify_jwt(token)

        assert payload['large_data'] == large_claim

    def test_auth_provider_with_empty_secret(self):
        """Test AuthProvider with empty secret."""
        provider = AuthProvider("")

        # Should still work but be insecure
        token = provider.issue_jwt()
        payload = provider.verify_jwt(token)

        assert 'iss' in payload

    def test_basic_auth_with_special_characters(self):
        """Test BasicAuthProvider with special characters in credentials."""
        provider = BasicAuthProvider("user:name", "pass@word!")

        headers = provider.get_auth_headers()

        # Should properly encode special characters
        import base64
        auth_value = headers['Authorization']
        encoded = auth_value[6:]
        decoded = base64.b64decode(encoded).decode()
        assert decoded == "user:name:pass@word!"
