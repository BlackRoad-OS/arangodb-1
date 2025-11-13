"""Protocol definitions for framework interfaces.

Protocols define the "what" (interfaces) without depending on "how" (implementations).
This module contains all shared protocols that multiple modules need to reference.

Design Principle:
    Protocols are black box boundaries - they define what a component does,
    not how it does it. Implementations can be swapped without changing protocols.
"""

from typing import Protocol, Dict, TypeVar, Any
from .types import ServerConfig
from .value_objects import ServerId

# Type variable for server instances - allows Protocol to work with any server type
# without creating circular dependencies
Server = TypeVar("Server")


class ServerFactory(Protocol):
    """Protocol for server factories to enable dependency injection.

    A server factory creates server instances from configuration.
    The factory pattern allows different server creation strategies
    without coupling to specific implementations.
    """

    def create_server_instances(
        self, servers_config: list[ServerConfig]
    ) -> Dict[ServerId, Any]:
        """Create server instances from ServerConfig objects.

        Args:
            servers_config: List of server configurations from deployment plan

        Returns:
            Dictionary mapping server_id to server instances
        """
