"""Cryptographic utilities including hashing, random ID generation, and nonce management."""
import hashlib
import secrets
import string
from typing import Set, Union
import threading
from ..core.errors import NonceReplayError
from ..core.log import get_logger
logger = get_logger(__name__)

class CryptoService:
    """Provides cryptographic utilities for the framework."""

    def __init__(self) -> None:
        self._nonce_registry: Set[str] = set()
        self._nonce_lock = threading.Lock()

    def sha256(self, data: Union[str, bytes]) -> str:
        """Generate SHA256 hash of data."""
        if isinstance(data, str):
            data = data.encode('utf-8')
        return hashlib.sha256(data).hexdigest()

    def md5(self, data: Union[str, bytes]) -> str:
        """Generate MD5 hash of data."""
        if isinstance(data, str):
            data = data.encode('utf-8')
        return hashlib.md5(data).hexdigest()

    def random_id(self, length: int=16) -> str:
        """Generate a cryptographically secure random ID."""
        if length <= 0:
            raise ValueError('Length must be positive')
        alphabet = string.ascii_letters + string.digits + '-_'
        return ''.join((secrets.choice(alphabet) for _ in range(length)))

    def random_bytes(self, length: int) -> bytes:
        """Generate cryptographically secure random bytes."""
        return secrets.token_bytes(length)

    def random_hex(self, length: int) -> str:
        """Generate cryptographically secure random hex string."""
        return secrets.token_hex(length)

    def register_nonce(self, nonce: str) -> None:
        """Register a nonce to prevent replay attacks."""
        with self._nonce_lock:
            if nonce in self._nonce_registry:
                raise NonceReplayError(f'Nonce replay detected: {nonce}')
            self._nonce_registry.add(nonce)
            logger.debug('Registered nonce: %s', nonce)

    def is_nonce_used(self, nonce: str) -> bool:
        """Check if nonce has been used."""
        with self._nonce_lock:
            return nonce in self._nonce_registry

    def clear_nonces(self) -> None:
        """Clear all registered nonces."""
        with self._nonce_lock:
            count = len(self._nonce_registry)
            self._nonce_registry.clear()
            logger.debug('Cleared %s nonces', count)

    def generate_secret(self, length: int=32) -> str:
        """Generate a secret suitable for HMAC operations."""
        return self.random_hex(length)
_crypto_service = CryptoService()

def sha256(data: Union[str, bytes]) -> str:
    """Generate SHA256 hash."""
    return _crypto_service.sha256(data)

def md5(data: Union[str, bytes]) -> str:
    """Generate MD5 hash."""
    return _crypto_service.md5(data)

def random_id(length: int=16) -> str:
    """Generate random ID."""
    return _crypto_service.random_id(length)

def random_bytes(length: int) -> bytes:
    """Generate random bytes."""
    return _crypto_service.random_bytes(length)

def random_hex(length: int) -> str:
    """Generate random hex string."""
    return _crypto_service.random_hex(length)

def register_nonce(nonce: str) -> None:
    """Register nonce."""
    _crypto_service.register_nonce(nonce)

def is_nonce_used(nonce: str) -> bool:
    """Check if nonce is used."""
    return _crypto_service.is_nonce_used(nonce)

def generate_secret(length: int=32) -> str:
    """Generate secret."""
    return _crypto_service.generate_secret(length)