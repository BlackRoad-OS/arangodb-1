"""Tests for cryptographic utilities."""

import pytest
import hashlib
from unittest.mock import patch

from armadillo.utils.crypto import (
    CryptoService,
    sha256,
    md5,
    random_id,
    random_bytes,
    random_hex,
    register_nonce,
    is_nonce_used,
    generate_secret,
)
from armadillo.core.errors import NonceReplayError


class TestCryptoService:
    """Test CryptoService class."""

    def test_crypto_service_creation(self):
        """Test CryptoService creation."""
        service = CryptoService()

        assert len(service._nonce_registry) == 0
        assert service._nonce_lock is not None

    def test_sha256_string_input(self):
        """Test SHA256 hashing with string input."""
        service = CryptoService()

        result = service.sha256("hello world")
        expected = hashlib.sha256("hello world".encode("utf-8")).hexdigest()

        assert result == expected
        assert len(result) == 64  # SHA256 hex length

    def test_sha256_bytes_input(self):
        """Test SHA256 hashing with bytes input."""
        service = CryptoService()

        data = b"hello world"
        result = service.sha256(data)
        expected = hashlib.sha256(data).hexdigest()

        assert result == expected

    def test_sha256_deterministic(self):
        """Test SHA256 produces consistent results."""
        service = CryptoService()

        data = "test data"
        result1 = service.sha256(data)
        result2 = service.sha256(data)

        assert result1 == result2

    def test_md5_string_input(self):
        """Test MD5 hashing with string input."""
        service = CryptoService()

        result = service.md5("hello world")
        expected = hashlib.md5("hello world".encode("utf-8")).hexdigest()

        assert result == expected
        assert len(result) == 32  # MD5 hex length

    def test_md5_bytes_input(self):
        """Test MD5 hashing with bytes input."""
        service = CryptoService()

        data = b"hello world"
        result = service.md5(data)
        expected = hashlib.md5(data).hexdigest()

        assert result == expected

    def test_random_id_default_length(self):
        """Test random ID generation with default length."""
        service = CryptoService()

        result = service.random_id()

        assert len(result) == 16
        assert all(c.isalnum() or c in "-_" for c in result)

    def test_random_id_custom_length(self):
        """Test random ID generation with custom length."""
        service = CryptoService()

        result = service.random_id(32)

        assert len(result) == 32
        assert all(c.isalnum() or c in "-_" for c in result)

    def test_random_id_uniqueness(self):
        """Test random ID uniqueness over multiple generations."""
        service = CryptoService()

        ids = {service.random_id() for _ in range(1000)}

        # Should have 1000 unique IDs (very high probability)
        assert len(ids) == 1000

    def test_random_id_invalid_length(self):
        """Test random ID with invalid length."""
        service = CryptoService()

        with pytest.raises(ValueError, match="Length must be positive"):
            service.random_id(0)

        with pytest.raises(ValueError, match="Length must be positive"):
            service.random_id(-1)

    def test_random_bytes(self):
        """Test random bytes generation."""
        service = CryptoService()

        result = service.random_bytes(16)

        assert isinstance(result, bytes)
        assert len(result) == 16

        # Different calls should produce different results
        result2 = service.random_bytes(16)
        assert result != result2

    def test_random_hex(self):
        """Test random hex string generation."""
        service = CryptoService()

        result = service.random_hex(8)

        assert isinstance(result, str)
        assert len(result) == 16  # 8 bytes = 16 hex characters
        assert all(c in "0123456789abcdef" for c in result)

    def test_nonce_registration(self):
        """Test nonce registration and tracking."""
        service = CryptoService()

        nonce = "test_nonce_123"

        # Should register successfully first time
        service.register_nonce(nonce)
        assert nonce in service._nonce_registry

    def test_nonce_replay_detection(self):
        """Test nonce replay attack detection."""
        service = CryptoService()

        nonce = "test_nonce_456"

        # Register nonce first time
        service.register_nonce(nonce)

        # Second registration should raise error
        with pytest.raises(NonceReplayError, match="Nonce replay detected"):
            service.register_nonce(nonce)

    def test_is_nonce_used(self):
        """Test nonce usage checking."""
        service = CryptoService()

        nonce = "test_nonce_789"

        # Initially not used
        assert not service.is_nonce_used(nonce)

        # After registration, should be used
        service.register_nonce(nonce)
        assert service.is_nonce_used(nonce)

    def test_clear_nonces(self):
        """Test clearing all nonces."""
        service = CryptoService()

        # Register several nonces
        nonces = ["nonce1", "nonce2", "nonce3"]
        for nonce in nonces:
            service.register_nonce(nonce)

        assert len(service._nonce_registry) == 3

        # Clear all nonces
        service.clear_nonces()

        assert len(service._nonce_registry) == 0
        for nonce in nonces:
            assert not service.is_nonce_used(nonce)

    def test_generate_secret(self):
        """Test secret generation."""
        service = CryptoService()

        secret = service.generate_secret()

        assert isinstance(secret, str)
        assert len(secret) == 64  # 32 bytes = 64 hex characters
        assert all(c in "0123456789abcdef" for c in secret)

        # Custom length
        secret2 = service.generate_secret(16)
        assert len(secret2) == 32  # 16 bytes = 32 hex characters

    def test_thread_safety(self):
        """Test thread safety of nonce operations."""
        # Skip this test since it requires real threading which conflicts with global mocking
        pytest.skip("Threading is globally mocked - test requires real threads")

        import threading

        service = CryptoService()
        nonces = [f"nonce_{i}" for i in range(100)]
        results = []

        def register_nonce_worker(nonce):
            try:
                service.register_nonce(nonce)
                results.append(("success", nonce))
            except NonceReplayError:
                results.append(("replay", nonce))

        # Register nonces concurrently
        threads = []
        for nonce in nonces:
            thread = threading.Thread(target=register_nonce_worker, args=(nonce,))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # All should have been successful (no duplicates)
        successful = [r for r in results if r[0] == "success"]
        assert len(successful) == 100


class TestGlobalCryptoFunctions:
    """Test global crypto utility functions."""

    def test_sha256_function(self):
        """Test global sha256 function."""
        result = sha256("test data")

        expected = hashlib.sha256("test data".encode("utf-8")).hexdigest()
        assert result == expected

    def test_md5_function(self):
        """Test global md5 function."""
        result = md5("test data")

        expected = hashlib.md5("test data".encode("utf-8")).hexdigest()
        assert result == expected

    def test_random_id_function(self):
        """Test global random_id function."""
        result = random_id(24)

        assert len(result) == 24
        assert all(c.isalnum() or c in "-_" for c in result)

    def test_random_bytes_function(self):
        """Test global random_bytes function."""
        result = random_bytes(12)

        assert isinstance(result, bytes)
        assert len(result) == 12

    def test_random_hex_function(self):
        """Test global random_hex function."""
        result = random_hex(6)

        assert isinstance(result, str)
        assert len(result) == 12  # 6 bytes = 12 hex chars
        assert all(c in "0123456789abcdef" for c in result)

    def test_nonce_functions(self):
        """Test global nonce management functions."""
        nonce = "global_test_nonce"

        # Initially not used
        assert not is_nonce_used(nonce)

        # Register nonce
        register_nonce(nonce)

        # Now should be used
        assert is_nonce_used(nonce)

        # Replay should raise error
        with pytest.raises(NonceReplayError):
            register_nonce(nonce)

    def test_generate_secret_function(self):
        """Test global generate_secret function."""
        secret = generate_secret()

        assert isinstance(secret, str)
        assert len(secret) == 64

        # Custom length
        secret2 = generate_secret(20)
        assert len(secret2) == 40  # 20 bytes = 40 hex chars


class TestCryptoEdgeCases:
    """Test crypto utility edge cases."""

    def test_empty_input_hashing(self):
        """Test hashing empty input."""
        service = CryptoService()

        # Empty string
        sha_result = service.sha256("")
        md5_result = service.md5("")

        assert len(sha_result) == 64
        assert len(md5_result) == 32

        # Empty bytes
        sha_result2 = service.sha256(b"")
        md5_result2 = service.md5(b"")

        assert sha_result == sha_result2
        assert md5_result == md5_result2

    def test_large_input_hashing(self):
        """Test hashing large input."""
        service = CryptoService()

        # 1MB of data
        large_data = "x" * (1024 * 1024)

        result = service.sha256(large_data)
        assert len(result) == 64

    def test_unicode_input_hashing(self):
        """Test hashing Unicode input."""
        service = CryptoService()

        unicode_data = "Hello 世界! 🌍"

        result = service.sha256(unicode_data)
        assert len(result) == 64

        # Should be consistent
        result2 = service.sha256(unicode_data)
        assert result == result2

    def test_nonce_empty_string(self):
        """Test nonce operations with empty string."""
        service = CryptoService()

        # Empty nonce should work
        service.register_nonce("")
        assert service.is_nonce_used("")

        # Replay should be detected
        with pytest.raises(NonceReplayError):
            service.register_nonce("")
