"""Tests for enhanced authentication utilities (Phase 2)."""

import pytest
import time
from unittest.mock import Mock, patch

from armadillo.utils.auth import AuthProvider
from armadillo.core.errors import JWTError


class TestAuthProviderEnhanced:
    """Test enhanced AuthProvider functionality from Phase 2."""

    def test_auth_provider_enhanced_initialization(self):
        """Test enhanced initialization with additional parameters."""
        provider = AuthProvider(
            secret="test_secret",
            algorithm="HS512",
            default_username="admin",
            default_password="secret"
        )

        assert provider.secret == "test_secret"
        assert provider.algorithm == "HS512"
        assert provider.default_username == "admin"
        assert provider.default_password == "secret"
        assert len(provider._active_tokens) == 0
        assert provider._token_counter == 0

    def test_create_user_token(self):
        """Test creating user-specific tokens with permissions."""
        provider = AuthProvider("test_secret")

        token = provider.create_user_token(
            username="test_user",
            permissions=["read", "write", "admin"],
            ttl=600.0,
            additional_claims={"department": "engineering"}
        )

        assert isinstance(token, str)
        assert len(token) > 0

        # Verify token contents
        payload = provider.verify_jwt(token)
        assert payload["username"] == "test_user"
        assert payload["permissions"] == ["read", "write", "admin"]
        assert payload["token_type"] == "user"
        assert payload["department"] == "engineering"

        # Verify token tracking
        active_tokens = provider.get_active_tokens()
        assert len(active_tokens) == 1

        token_info = list(active_tokens.values())[0]
        assert token_info["username"] == "test_user"
        assert token_info["permissions"] == ["read", "write", "admin"]

    def test_create_service_token(self):
        """Test creating service-specific tokens."""
        provider = AuthProvider("test_secret")

        token = provider.create_service_token(
            service_name="backup_service",
            permissions=["backup", "restore"],
            ttl=86400.0  # 24 hours
        )

        assert isinstance(token, str)

        # Verify token contents
        payload = provider.verify_jwt(token)
        assert payload["service"] == "backup_service"
        assert payload["permissions"] == ["backup", "restore"]
        assert payload["token_type"] == "service"

        # Verify longer TTL
        exp_time = payload["exp"]
        iat_time = payload["iat"]
        ttl = exp_time - iat_time
        assert 86390 <= ttl <= 86410  # Allow for small timing differences

    def test_get_basic_auth_header(self):
        """Test generating basic auth headers."""
        provider = AuthProvider(
            default_username="root",
            default_password="password123"
        )

        # Test with defaults
        headers = provider.get_basic_auth_header()
        assert "Authorization" in headers
        assert headers["Authorization"].startswith("Basic ")

        # Decode and verify
        import base64
        encoded = headers["Authorization"][6:]  # Remove "Basic "
        decoded = base64.b64decode(encoded).decode()
        assert decoded == "root:password123"

        # Test with custom credentials
        headers = provider.get_basic_auth_header("admin", "secret")
        encoded = headers["Authorization"][6:]
        decoded = base64.b64decode(encoded).decode()
        assert decoded == "admin:secret"

    def test_create_cluster_auth_headers(self):
        """Test creating cluster authentication headers."""
        provider = AuthProvider("cluster_secret")

        headers = provider.create_cluster_auth_headers(
            cluster_id="prod_cluster_01",
            role="coordinator",
            ttl=7200.0
        )

        assert "Authorization" in headers
        assert headers["Authorization"].startswith("Bearer ")

        # Extract and verify token
        token = headers["Authorization"][7:]  # Remove "Bearer "
        payload = provider.verify_jwt(token)

        assert payload["cluster_id"] == "prod_cluster_01"
        assert payload["cluster_role"] == "coordinator"
        assert payload["token_type"] == "cluster"

        # Verify TTL
        exp_time = payload["exp"]
        iat_time = payload["iat"]
        ttl = exp_time - iat_time
        assert 7190 <= ttl <= 7210  # Allow for timing differences

    def test_validate_token_permissions(self):
        """Test token permission validation."""
        provider = AuthProvider("test_secret")

        # Create token with specific permissions
        token = provider.create_user_token(
            username="test_user",
            permissions=["read", "write", "delete"]
        )

        # Test successful validation
        assert provider.validate_token_permissions(token, ["read"])
        assert provider.validate_token_permissions(token, ["read", "write"])
        assert provider.validate_token_permissions(token, ["read", "write", "delete"])

        # Test failed validation
        assert not provider.validate_token_permissions(token, ["admin"])
        assert not provider.validate_token_permissions(token, ["read", "admin"])

        # Test with invalid token
        assert not provider.validate_token_permissions("invalid.token", ["read"])

    def test_get_active_tokens(self):
        """Test getting active token information."""
        provider = AuthProvider("test_secret")

        # Initially empty
        active = provider.get_active_tokens()
        assert len(active) == 0

        # Create some tokens
        user_token = provider.create_user_token("user1", ["read"])
        service_token = provider.create_service_token("service1", ["backup"])

        active = provider.get_active_tokens()
        assert len(active) == 2

        # Verify token info
        token_infos = list(active.values())
        usernames = [info.get("username") for info in token_infos if "username" in info]
        services = [info.get("service") for info in token_infos if "service" in info]

        assert "user1" in usernames
        assert "service1" in services

    def test_revoke_token(self):
        """Test token revocation."""
        provider = AuthProvider("test_secret")

        # Create and track a token
        token = provider.create_user_token("user1", ["read"])
        active = provider.get_active_tokens()
        assert len(active) == 1

        token_id = list(active.keys())[0]

        # Revoke token
        assert provider.revoke_token(token_id)

        # Verify revocation
        active = provider.get_active_tokens()
        assert len(active) == 0

        # Try to revoke non-existent token
        assert not provider.revoke_token("nonexistent")

    def test_cleanup_expired_tokens(self):
        """Test cleaning up expired tokens."""
        provider = AuthProvider("test_secret")

        # Create tokens with different expiration times
        with patch('time.time', return_value=1000.0):
            # Short-lived token (will be expired)
            short_token = provider.create_user_token("user1", ["read"], ttl=1.0)

            # Long-lived token (will not be expired)
            long_token = provider.create_user_token("user2", ["read"], ttl=3600.0)

        # Simulate time passing
        with patch('time.time', return_value=1002.0):  # 2 seconds later
            cleaned = provider.cleanup_expired_tokens()

            assert cleaned == 1  # One token cleaned up

            active = provider.get_active_tokens()
            assert len(active) == 1  # Only long-lived token remains

            remaining_info = list(active.values())[0]
            assert remaining_info["username"] == "user2"

    def test_automatic_expired_token_cleanup_in_get_active(self):
        """Test that get_active_tokens automatically cleans up expired tokens."""
        provider = AuthProvider("test_secret")

        # Create tokens at time 1000
        with patch('time.time', return_value=1000.0):
            provider.create_user_token("user1", ["read"], ttl=1.0)  # Expires at 1001
            provider.create_user_token("user2", ["read"], ttl=10.0)  # Expires at 1010

        # Check at time 1005 (first token expired, second still valid)
        with patch('time.time', return_value=1005.0):
            active = provider.get_active_tokens()

            assert len(active) == 1
            remaining_info = list(active.values())[0]
            assert remaining_info["username"] == "user2"

    def test_token_counter_increment(self):
        """Test that token counter increments correctly."""
        provider = AuthProvider("test_secret")

        assert provider._token_counter == 0

        provider.create_user_token("user1", ["read"])
        assert provider._token_counter == 1

        provider.create_service_token("service1", ["backup"])
        assert provider._token_counter == 2

        # Verify unique token IDs
        active = provider.get_active_tokens()
        token_ids = list(active.keys())

        assert len(set(token_ids)) == 2  # All unique
        assert any("user_1_user1" in tid for tid in token_ids)
        assert any("service_2_service1" in tid for tid in token_ids)

    def test_enhanced_authorization_header_with_claims(self):
        """Test enhanced authorization_header with custom claims."""
        provider = AuthProvider("test_secret")

        headers = provider.authorization_header(
            ttl=1800.0,
            claims={"custom_claim": "custom_value", "role": "admin"}
        )

        assert "Authorization" in headers
        token = headers["Authorization"][7:]  # Remove "Bearer "

        payload = provider.verify_jwt(token)
        assert payload["custom_claim"] == "custom_value"
        assert payload["role"] == "admin"

        # Verify TTL
        exp_time = payload["exp"]
        iat_time = payload["iat"]
        ttl = exp_time - iat_time
        assert 1790 <= ttl <= 1810

    def test_concurrent_token_operations(self):
        """Test thread safety of token operations."""
        import threading

        provider = AuthProvider("test_secret")
        results = []

        def create_tokens(user_id):
            try:
                token = provider.create_user_token(f"user_{user_id}", ["read"])
                results.append(("success", user_id, token))
            except Exception as e:
                results.append(("error", user_id, str(e)))

        # Create tokens concurrently
        threads = []
        for i in range(20):
            thread = threading.Thread(target=create_tokens, args=(i,))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # All operations should succeed
        successful = [r for r in results if r[0] == "success"]
        assert len(successful) == 20

        # Verify all tokens are tracked
        active = provider.get_active_tokens()
        assert len(active) == 20

        # Verify unique token IDs
        token_ids = list(active.keys())
        assert len(set(token_ids)) == 20

    def test_permission_edge_cases(self):
        """Test edge cases in permission validation."""
        provider = AuthProvider("test_secret")

        # Token with empty permissions
        token_empty = provider.create_user_token("user1", [])
        assert not provider.validate_token_permissions(token_empty, ["read"])
        assert provider.validate_token_permissions(token_empty, [])  # Empty requirements should pass

        # Token with many permissions
        many_perms = [f"perm_{i}" for i in range(100)]
        token_many = provider.create_user_token("user2", many_perms)
        assert provider.validate_token_permissions(token_many, many_perms)
        assert provider.validate_token_permissions(token_many, ["perm_50"])
        assert not provider.validate_token_permissions(token_many, ["nonexistent_perm"])

    def test_service_vs_user_token_distinction(self):
        """Test distinction between service and user tokens."""
        provider = AuthProvider("test_secret")

        user_token = provider.create_user_token("test_user", ["read"])
        service_token = provider.create_service_token("test_service", ["read"])

        user_payload = provider.verify_jwt(user_token)
        service_payload = provider.verify_jwt(service_token)

        assert user_payload["token_type"] == "user"
        assert "username" in user_payload
        assert "service" not in user_payload

        assert service_payload["token_type"] == "service"
        assert "service" in service_payload
        assert "username" not in service_payload

        # Verify in active tokens tracking
        active = provider.get_active_tokens()
        assert len(active) == 2

        token_infos = list(active.values())
        user_info = next(info for info in token_infos if "username" in info)
        service_info = next(info for info in token_infos if "service" in info)

        assert user_info["username"] == "test_user"
        assert service_info["service"] == "test_service"
