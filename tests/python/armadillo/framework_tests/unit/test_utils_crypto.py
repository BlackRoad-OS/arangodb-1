"""Tests for cryptographic utilities."""

import pytest

from armadillo.utils.crypto import random_id, generate_secret


class TestCryptoUtils:
    """Test crypto utility functions."""

    def test_random_id_default_length(self) -> None:
        """Test random_id with default length."""
        result = random_id()
        assert len(result) == 16
        assert all(c.isalnum() or c in "-_" for c in result)

    def test_random_id_custom_length(self) -> None:
        """Test random_id with custom length."""
        result = random_id(8)
        assert len(result) == 8
        assert all(c.isalnum() or c in "-_" for c in result)

    def test_random_id_uniqueness(self) -> None:
        """Test that random_id generates unique values."""
        ids = [random_id() for _ in range(100)]
        assert len(set(ids)) == 100  # All should be unique

    def test_random_id_invalid_length(self) -> None:
        """Test random_id with invalid length."""
        with pytest.raises(ValueError, match="Length must be positive"):
            random_id(0)

        with pytest.raises(ValueError, match="Length must be positive"):
            random_id(-1)

    def test_generate_secret_default_length(self) -> None:
        """Test generate_secret with default length."""
        result = generate_secret()
        assert len(result) == 64  # 32 bytes = 64 hex chars
        assert all(c in "0123456789abcdef" for c in result)

    def test_generate_secret_custom_length(self) -> None:
        """Test generate_secret with custom length."""
        result = generate_secret(16)
        assert len(result) == 32  # 16 bytes = 32 hex chars
        assert all(c in "0123456789abcdef" for c in result)

    def test_generate_secret_uniqueness(self) -> None:
        """Test that generate_secret generates unique values."""
        secrets = [generate_secret() for _ in range(10)]
        assert len(set(secrets)) == 10  # All should be unique
