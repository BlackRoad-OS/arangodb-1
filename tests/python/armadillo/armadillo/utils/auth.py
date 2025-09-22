"""Authentication utilities for secure communication with ArangoDB."""
import time
import jwt
import base64
from typing import Dict, Optional, Any, List
from ..core.errors import JWTError
from ..core.log import get_logger
from .crypto import generate_secret
logger = get_logger(__name__)

class AuthProvider:
    """Enhanced JWT-based authentication provider for secure ArangoDB communication."""

    def __init__(self, secret: Optional[str]=None, algorithm: str='HS256', default_username: str='root', default_password: str='') -> None:
        """Initialize authentication provider.

        Args:
            secret: Secret key for JWT signing (generated if not provided)
            algorithm: JWT signing algorithm
            default_username: Default username for basic auth fallback
            default_password: Default password for basic auth fallback
        """
        self.algorithm = algorithm
        self.secret = secret or generate_secret()
        self.default_username = default_username
        self.default_password = default_password
        self._active_tokens: Dict[str, Dict[str, Any]] = {}
        self._token_counter = 0
        logger.debug('AuthProvider initialized with algorithm %s', algorithm)

    def issue_jwt(self, ttl: float=3600.0, claims: Optional[Dict[str, Any]]=None) -> str:
        """Issue a JWT token with specified TTL and claims."""
        now = time.time()
        payload = {'iat': int(now), 'exp': int(now + ttl), 'iss': 'armadillo'}
        if claims:
            payload.update(claims)
        try:
            token = jwt.encode(payload, self.secret, algorithm=self.algorithm)
            logger.debug('Issued JWT token with TTL %ss', ttl)
            return token
        except Exception as e:
            raise JWTError(f'Failed to issue JWT token: {e}') from e

    def verify_jwt(self, token: str) -> Dict[str, Any]:
        """Verify and decode a JWT token."""
        try:
            payload = jwt.decode(token, self.secret, algorithms=[self.algorithm])
            logger.debug('Successfully verified JWT token')
            return payload
        except jwt.ExpiredSignatureError as e:
            raise JWTError('JWT token has expired') from e
        except jwt.InvalidTokenError as e:
            raise JWTError(f'Invalid JWT token: {e}') from e
        except Exception as e:
            raise JWTError(f'Failed to verify JWT token: {e}') from e

    def authorization_header(self, ttl: float=3600.0, claims: Optional[Dict[str, Any]]=None) -> Dict[str, str]:
        """Generate authorization header with Bearer token."""
        token = self.issue_jwt(ttl=ttl, claims=claims)
        return {'Authorization': f'Bearer {token}'}

    def get_auth_headers(self, ttl: float=3600.0) -> Dict[str, str]:
        """Get authentication headers for HTTP requests."""
        return self.authorization_header(ttl)

    def is_token_expired(self, token: str) -> bool:
        """Check if token is expired without raising exception."""
        try:
            payload = jwt.decode(token, self.secret, algorithms=[self.algorithm])
            exp = payload.get('exp', 0)
            return time.time() >= exp
        except Exception:
            return True

    def get_token_claims(self, token: str) -> Optional[Dict[str, Any]]:
        """Get token claims without verification (for debugging)."""
        try:
            payload = jwt.decode(token, options={'verify_signature': False})
            return payload
        except Exception as e:
            logger.debug('Failed to decode token claims: %s', e)
            return None

    def refresh_token(self, token: str, new_ttl: float=3600.0) -> str:
        """Refresh an existing token with new TTL."""
        try:
            old_payload = self.verify_jwt(token)
            new_claims = old_payload.copy()
            for key in ['iat', 'exp']:
                new_claims.pop(key, None)
            return self.issue_jwt(ttl=new_ttl, claims=new_claims)
        except JWTError:
            raise
        except Exception as e:
            raise JWTError(f'Failed to refresh token: {e}') from e

    def create_user_token(self, username: str, permissions: List[str], ttl: float=3600.0, additional_claims: Optional[Dict[str, Any]]=None) -> str:
        """Create a user-specific JWT token with permissions.

        Args:
            username: Username
            permissions: List of permissions
            ttl: Token time-to-live in seconds
            additional_claims: Additional claims to include

        Returns:
            JWT token for the user
        """
        claims = {'username': username, 'permissions': permissions, 'token_type': 'user'}
        if additional_claims:
            claims.update(additional_claims)
        token = self.issue_jwt(ttl=ttl, claims=claims)
        self._token_counter += 1
        token_id = f'user_{self._token_counter}_{username}'
        self._active_tokens[token_id] = {'token': token, 'username': username, 'permissions': permissions, 'created': time.time(), 'expires': time.time() + ttl}
        logger.debug('Created user token for %s with %s permissions', username, len(permissions))
        return token

    def create_service_token(self, service_name: str, permissions: List[str], ttl: float=86400.0) -> str:
        """Create a service-specific JWT token.

        Args:
            service_name: Service identifier
            permissions: List of service permissions
            ttl: Token time-to-live in seconds (default: 24 hours)

        Returns:
            JWT token for the service
        """
        claims = {'service': service_name, 'permissions': permissions, 'token_type': 'service'}
        token = self.issue_jwt(ttl=ttl, claims=claims)
        self._token_counter += 1
        token_id = f'service_{self._token_counter}_{service_name}'
        self._active_tokens[token_id] = {'token': token, 'service': service_name, 'permissions': permissions, 'created': time.time(), 'expires': time.time() + ttl}
        logger.debug('Created service token for %s', service_name)
        return token

    def get_basic_auth_header(self, username: Optional[str]=None, password: Optional[str]=None) -> Dict[str, str]:
        """Generate HTTP basic authentication header.

        Args:
            username: Username (default: provider default)
            password: Password (default: provider default)

        Returns:
            Dictionary with Authorization header
        """
        user = username or self.default_username
        pwd = password or self.default_password
        credentials = f'{user}:{pwd}'
        encoded = base64.b64encode(credentials.encode()).decode()
        return {'Authorization': f'Basic {encoded}'}

    def create_cluster_auth_headers(self, cluster_id: str, role: str='test_cluster', ttl: float=7200.0) -> Dict[str, str]:
        """Create authentication headers for cluster communication.

        Args:
            cluster_id: Unique cluster identifier
            role: Cluster role (e.g., coordinator, dbserver)
            ttl: Token validity duration

        Returns:
            Dictionary with authentication headers
        """
        claims = {'cluster_id': cluster_id, 'cluster_role': role, 'token_type': 'cluster'}
        return self.authorization_header(ttl=ttl, claims=claims)

    def validate_token_permissions(self, token: str, required_permissions: List[str]) -> bool:
        """Validate that a token has required permissions.

        Args:
            token: JWT token to validate
            required_permissions: List of required permissions

        Returns:
            True if token has all required permissions
        """
        try:
            payload = self.verify_jwt(token)
            token_permissions = payload.get('permissions', [])
            return all((perm in token_permissions for perm in required_permissions))
        except JWTError:
            return False

    def get_active_tokens(self) -> Dict[str, Dict[str, Any]]:
        """Get information about active tokens.

        Returns:
            Dictionary of active token information
        """
        current_time = time.time()
        expired_tokens = [token_id for token_id, info in self._active_tokens.items() if info['expires'] <= current_time]
        for token_id in expired_tokens:
            del self._active_tokens[token_id]
        return self._active_tokens.copy()

    def revoke_token(self, token_id: str) -> bool:
        """Revoke an active token.

        Args:
            token_id: Token identifier to revoke

        Returns:
            True if token was revoked
        """
        if token_id in self._active_tokens:
            del self._active_tokens[token_id]
            logger.info('Revoked token %s', token_id)
            return True
        return False

    def cleanup_expired_tokens(self) -> int:
        """Clean up expired tokens.

        Returns:
            Number of tokens cleaned up
        """
        current_time = time.time()
        expired_tokens = [token_id for token_id, info in self._active_tokens.items() if info['expires'] <= current_time]
        for token_id in expired_tokens:
            del self._active_tokens[token_id]
        if expired_tokens:
            logger.debug('Cleaned up %s expired tokens', len(expired_tokens))
        return len(expired_tokens)

class BasicAuthProvider:
    """Provides basic authentication for fallback scenarios."""

    def __init__(self, username: str='root', password: str=''):
        self.username = username
        self.password = password

    def get_auth_headers(self) -> Dict[str, str]:
        """Get basic auth headers."""
        auth_string = f'{self.username}:{self.password}'
        encoded = base64.b64encode(auth_string.encode()).decode()
        return {'Authorization': f'Basic {encoded}'}
_auth_provider: Optional[AuthProvider] = None
_basic_auth_provider: Optional[BasicAuthProvider] = None

def get_auth_provider(secret: Optional[str]=None, algorithm: str='HS256') -> AuthProvider:
    """Get or create global JWT auth provider."""
    global _auth_provider
    if _auth_provider is None:
        _auth_provider = AuthProvider(secret, algorithm)
    return _auth_provider

def get_basic_auth_provider(username: str='root', password: str='') -> BasicAuthProvider:
    """Get or create global basic auth provider."""
    global _basic_auth_provider
    if _basic_auth_provider is None:
        _basic_auth_provider = BasicAuthProvider(username, password)
    return _basic_auth_provider

def issue_jwt(ttl: float=3600.0, claims: Optional[Dict[str, Any]]=None) -> str:
    """Issue JWT token using global provider."""
    return get_auth_provider().issue_jwt(ttl, claims)

def verify_jwt(token: str) -> Dict[str, Any]:
    """Verify JWT token using global provider."""
    return get_auth_provider().verify_jwt(token)

def authorization_header(ttl: float=3600.0) -> Dict[str, str]:
    """Get authorization header using global provider."""
    return get_auth_provider().authorization_header(ttl)