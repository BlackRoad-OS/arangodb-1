"""Server instance factory for creating ArangoDB servers from deployment plans."""

from typing import Dict, Optional, Protocol
from dataclasses import dataclass
from pathlib import Path
from ..core.types import ServerRole, ServerConfig
from ..core.config import ConfigProvider
from ..core.context import ApplicationContext
from ..core.log import Logger
from ..core.errors import ServerError
from ..utils.ports import PortAllocator
from ..utils.auth import get_auth_provider
from .server import ArangoServer, ServerPaths
from .command_builder import ServerCommandBuilder
from .health_checker import ServerHealthChecker


class ServerFactory(Protocol):
    """Protocol for server factories to enable dependency injection."""

    def create_server_instances(
        self, servers_config: list[ServerConfig]
    ) -> Dict[str, ArangoServer]:
        """Create ArangoServer instances from ServerConfig objects."""


class StandardServerFactory:
    """Factory for creating ArangoDB server instances using ApplicationContext.

    This factory creates servers using the new ApplicationContext pattern,
    providing clean dependency injection and improved testability.
    """

    def __init__(self, app_context: ApplicationContext) -> None:
        """Initialize factory with application context.

        Args:
            app_context: Application context containing all dependencies
        """
        self._app_context = app_context

    def create_server_instances(
        self, servers_config: list[ServerConfig]
    ) -> Dict[str, ArangoServer]:
        """Create ArangoServer instances from ServerConfig objects.

        Args:
            servers_config: List of server configurations from deployment plan

        Returns:
            Dictionary mapping server_id to ArangoServer instances

        Raises:
            ServerError: If server creation fails
        """
        servers = {}
        for i, server_config in enumerate(servers_config):
            server_id = self._generate_server_id(server_config.role, i)
            server = self._create_single_server(server_id, server_config)
            servers[server_id] = server
            self._app_context.logger.debug(
                "Created server instance %s with role %s on port %s",
                server_id,
                server_config.role.value,
                server_config.port,
            )
        return servers

    def _generate_server_id(self, role: ServerRole, index: int) -> str:
        """Generate server ID based on role and index."""
        if role == ServerRole.AGENT:
            return f"agent_{index}"
        elif role == ServerRole.DBSERVER:
            return f"dbserver_{index}"
        elif role == ServerRole.COORDINATOR:
            return f"coordinator_{index}"
        else:
            return f"server_{index}"

    def _create_single_server(
        self, server_id: str, server_config: ServerConfig
    ) -> ArangoServer:
        """Create a single ArangoServer instance using the new factory method.

        Args:
            server_id: Unique server identifier
            server_config: Server configuration from deployment plan

        Returns:
            Configured ArangoServer instance

        Raises:
            ServerError: If port is invalid or server creation fails
        """
        port_value = server_config.port
        if not isinstance(port_value, int):
            raise ServerError(
                f"Invalid port type for {server_id}: {type(port_value)} (expected int)"
            )

        # Use the new factory method for clean creation
        server = ArangoServer.create_cluster_server(
            server_id=server_id,
            role=server_config.role,
            port=port_value,
            app_context=self._app_context,
            config=server_config,
        )

        return server
