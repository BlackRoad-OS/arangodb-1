"""Simple utilities for random ID generation and secret generation."""

import secrets
import string


def random_id(length: int = 16) -> str:
    """Generate a cryptographically secure random ID."""
    if length <= 0:
        raise ValueError("Length must be positive")
    alphabet = string.ascii_letters + string.digits + "-_"
    return "".join((secrets.choice(alphabet) for _ in range(length)))


def generate_secret(length: int = 32) -> str:
    """Generate a secret suitable for HMAC operations."""
    return secrets.token_hex(length)
