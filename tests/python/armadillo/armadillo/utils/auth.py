"""JWT authentication provider with HMAC signing."""

import time
import jwt
from typing import Dict, Optional, Any
from datetime import datetime, timezone

from ..core.errors import JWTError, AuthenticationError
from ..core.log import get_logger
from .crypto import generate_secret

logger = get_logger(__name__)


class AuthProvider:
    """Provides JWT token generation and authentication services."""

    def __init__(self, secret: Optional[str] = None, algorithm: str = "HS256") -> None:
        self.algorithm = algorithm
        self.secret = secret or generate_secret()
        logger.debug(f"AuthProvider initialized with algorithm {algorithm}")

    def issue_jwt(self,
                 ttl: float = 3600.0,
                 claims: Optional[Dict[str, Any]] = None) -> str:
        """Issue a JWT token with specified TTL and claims."""
        now = time.time()

        payload = {
            'iat': int(now),  # Issued at
            'exp': int(now + ttl),  # Expiration time
            'iss': 'armadillo',  # Issuer
        }

        # Add custom claims
        if claims:
            payload.update(claims)

        try:
            token = jwt.encode(payload, self.secret, algorithm=self.algorithm)
            logger.debug(f"Issued JWT token with TTL {ttl}s")
            return token
        except Exception as e:
            raise JWTError(f"Failed to issue JWT token: {e}") from e

    def verify_jwt(self, token: str) -> Dict[str, Any]:
        """Verify and decode a JWT token."""
        try:
            payload = jwt.decode(token, self.secret, algorithms=[self.algorithm])
            logger.debug("Successfully verified JWT token")
            return payload
        except jwt.ExpiredSignatureError:
            raise JWTError("JWT token has expired")
        except jwt.InvalidTokenError as e:
            raise JWTError(f"Invalid JWT token: {e}") from e
        except Exception as e:
            raise JWTError(f"Failed to verify JWT token: {e}") from e

    def authorization_header(self, ttl: float = 3600.0) -> Dict[str, str]:
        """Generate authorization header with Bearer token."""
        token = self.issue_jwt(ttl=ttl)
        return {"Authorization": f"Bearer {token}"}

    def get_auth_headers(self, ttl: float = 3600.0) -> Dict[str, str]:
        """Get authentication headers for HTTP requests."""
        return self.authorization_header(ttl)

    def is_token_expired(self, token: str) -> bool:
        """Check if token is expired without raising exception."""
        try:
            payload = jwt.decode(token, self.secret, algorithms=[self.algorithm])
            exp = payload.get('exp', 0)
            return time.time() >= exp
        except Exception:
            return True  # Consider invalid tokens as expired

    def get_token_claims(self, token: str) -> Optional[Dict[str, Any]]:
        """Get token claims without verification (for debugging)."""
        try:
            # Decode without verification to inspect claims
            payload = jwt.decode(token, options={"verify_signature": False})
            return payload
        except Exception as e:
            logger.debug(f"Failed to decode token claims: {e}")
            return None

    def refresh_token(self, token: str, new_ttl: float = 3600.0) -> str:
        """Refresh an existing token with new TTL."""
        try:
            # First verify the old token
            old_payload = self.verify_jwt(token)

            # Create new token with same claims but new expiration
            new_claims = old_payload.copy()

            # Remove timing claims as they will be regenerated
            for key in ['iat', 'exp']:
                new_claims.pop(key, None)

            return self.issue_jwt(ttl=new_ttl, claims=new_claims)

        except JWTError:
            raise
        except Exception as e:
            raise JWTError(f"Failed to refresh token: {e}") from e


class BasicAuthProvider:
    """Provides basic authentication for fallback scenarios."""

    def __init__(self, username: str = "root", password: str = ""):
        self.username = username
        self.password = password

    def get_auth_headers(self) -> Dict[str, str]:
        """Get basic auth headers."""
        import base64

        auth_string = f"{self.username}:{self.password}"
        encoded = base64.b64encode(auth_string.encode()).decode()

        return {"Authorization": f"Basic {encoded}"}


# Global auth provider - will be initialized when needed
_auth_provider: Optional[AuthProvider] = None
_basic_auth_provider: Optional[BasicAuthProvider] = None


def get_auth_provider(secret: Optional[str] = None, algorithm: str = "HS256") -> AuthProvider:
    """Get or create global JWT auth provider."""
    global _auth_provider
    if _auth_provider is None:
        _auth_provider = AuthProvider(secret, algorithm)
    return _auth_provider


def get_basic_auth_provider(username: str = "root", password: str = "") -> BasicAuthProvider:
    """Get or create global basic auth provider."""
    global _basic_auth_provider
    if _basic_auth_provider is None:
        _basic_auth_provider = BasicAuthProvider(username, password)
    return _basic_auth_provider


def issue_jwt(ttl: float = 3600.0, claims: Optional[Dict[str, Any]] = None) -> str:
    """Issue JWT token using global provider."""
    return get_auth_provider().issue_jwt(ttl, claims)


def verify_jwt(token: str) -> Dict[str, Any]:
    """Verify JWT token using global provider."""
    return get_auth_provider().verify_jwt(token)


def authorization_header(ttl: float = 3600.0) -> Dict[str, str]:
    """Get authorization header using global provider."""
    return get_auth_provider().authorization_header(ttl)

