"""Simple authentication utilities for ArangoDB communication."""

import time
from typing import Dict, Optional, Any
import jwt
from ..core.errors import JWTError
from ..core.log import get_logger
from .crypto import generate_secret

logger = get_logger(__name__)


class AuthProvider:
    """Simple JWT-based authentication provider for ArangoDB communication."""

    def __init__(
        self,
        secret: Optional[str] = None,
        algorithm: str = "HS256",
    ) -> None:
        """Initialize authentication provider.

        Args:
            secret: Secret key for JWT signing (generated if not provided)
            algorithm: JWT signing algorithm
        """
        self.algorithm = algorithm
        self.secret = secret or generate_secret()
        logger.debug("AuthProvider initialized with algorithm %s", algorithm)

    def get_auth_headers(self, ttl: float = 3600.0) -> Dict[str, str]:
        """Get authentication headers for HTTP requests."""
        token = self._issue_jwt(ttl=ttl)
        return {"Authorization": f"Bearer {token}"}

    def _issue_jwt(
        self, ttl: float = 3600.0, claims: Optional[Dict[str, Any]] = None
    ) -> str:
        """Issue a JWT token with specified TTL and claims."""
        now = time.time()
        payload = {"iat": int(now), "exp": int(now + ttl), "iss": "armadillo"}
        if claims:
            payload.update(claims)
        try:
            token = jwt.encode(payload, self.secret, algorithm=self.algorithm)
            logger.debug("Issued JWT token with TTL %ss", ttl)
            return token
        except Exception as e:
            # Defensive: JWT library could fail in various ways, wrap all errors
            raise JWTError(f"Failed to issue JWT token: {e}") from e
