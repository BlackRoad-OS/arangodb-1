"""Server registry for storage and discovery of ArangoDB server instances."""

from typing import Dict, List, Optional
import threading
from ..core.types import ServerRole
from .server import ArangoServer


class ServerRegistry:
    """Thread-safe registry for storing and querying ArangoDB server instances.

    This is a pure data structure with no business logic - just storage and retrieval.
    """

    def __init__(self) -> None:
        """Initialize empty server registry."""
        self._servers: Dict[str, ArangoServer] = {}
        self._lock = threading.RLock()

    def register_server(self, server_id: str, server: ArangoServer) -> None:
        """Register a server instance.

        Args:
            server_id: Unique server identifier
            server: ArangoServer instance to register

        Raises:
            ValueError: If server_id is already registered
        """
        with self._lock:
            if server_id in self._servers:
                raise ValueError(f"Server {server_id} is already registered")
            self._servers[server_id] = server

    def unregister_server(self, server_id: str) -> Optional[ArangoServer]:
        """Unregister and return a server instance.

        Args:
            server_id: Unique server identifier

        Returns:
            The removed server instance, or None if not found
        """
        with self._lock:
            return self._servers.pop(server_id, None)

    def get_server(self, server_id: str) -> Optional[ArangoServer]:
        """Get a server instance by ID.

        Args:
            server_id: Unique server identifier

        Returns:
            ArangoServer instance or None if not found
        """
        with self._lock:
            return self._servers.get(server_id)

    def get_all_servers(self) -> Dict[str, ArangoServer]:
        """Get all registered servers.

        Returns:
            Dictionary mapping server IDs to ArangoServer instances
        """
        with self._lock:
            return dict(self._servers)

    def get_servers_by_role(self, role: ServerRole) -> List[ArangoServer]:
        """Get all servers with a specific role.

        Args:
            role: ServerRole to filter by

        Returns:
            List of ArangoServer instances with the specified role
        """
        with self._lock:
            return [server for server in self._servers.values() if server.role == role]

    def get_server_ids_by_role(self, role: ServerRole) -> List[str]:
        """Get all server IDs with a specific role.

        Args:
            role: ServerRole to filter by

        Returns:
            List of server IDs with the specified role
        """
        with self._lock:
            return [
                server_id
                for server_id, server in self._servers.items()
                if server.role == role
            ]

    def get_endpoints_by_role(self, role: ServerRole) -> List[str]:
        """Get HTTP endpoints for all servers with a specific role.

        Args:
            role: ServerRole to filter by

        Returns:
            List of HTTP endpoint URLs
        """
        servers = self.get_servers_by_role(role)
        return [server.get_endpoint() for server in servers]

    def has_server(self, server_id: str) -> bool:
        """Check if a server is registered.

        Args:
            server_id: Unique server identifier

        Returns:
            True if server is registered, False otherwise
        """
        with self._lock:
            return server_id in self._servers

    def count(self) -> int:
        """Get the total number of registered servers.

        Returns:
            Number of servers in registry
        """
        with self._lock:
            return len(self._servers)

    def count_by_role(self, role: ServerRole) -> int:
        """Count servers with a specific role.

        Args:
            role: ServerRole to count

        Returns:
            Number of servers with the specified role
        """
        with self._lock:
            return sum(1 for server in self._servers.values() if server.role == role)

    def clear(self) -> None:
        """Remove all servers from the registry."""
        with self._lock:
            self._servers.clear()

    def get_server_ids(self) -> List[str]:
        """Get all registered server IDs.

        Returns:
            List of server IDs
        """
        with self._lock:
            return list(self._servers.keys())
