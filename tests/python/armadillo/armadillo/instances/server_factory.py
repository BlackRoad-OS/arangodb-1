"""Server instance factory for creating ArangoDB servers from deployment plans."""

from typing import Dict, Optional, Protocol
from dataclasses import dataclass
from pathlib import Path

from ..core.types import ServerRole, ServerConfig
from ..core.config import ConfigProvider
from ..core.log import Logger
from ..core.errors import ServerError
from ..utils.ports import PortAllocator
from ..utils.auth import get_auth_provider
from .server import ArangoServer
from .command_builder import ServerCommandBuilder
from .health_checker import ServerHealthChecker


class ServerFactory(Protocol):
    """Protocol for server factories to enable dependency injection."""

    def create_server_instances(self, servers_config: list[ServerConfig]) -> Dict[str, ArangoServer]:
        """Create ArangoServer instances from ServerConfig objects."""
        ...


@dataclass
class MinimalConfig:
    """Minimal configuration to pass to ArangoServer."""
    args: dict
    memory_limit_mb: Optional[int] = None
    startup_timeout: float = 30.0
    data_dir: Optional[Path] = None
    log_file: Optional[Path] = None


class StandardServerFactory:
    """Factory for creating ArangoDB server instances with proper dependency injection."""

    def __init__(self,
                 config_provider: ConfigProvider,
                 logger: Logger,
                 port_allocator: PortAllocator) -> None:
        self._config_provider = config_provider
        self._logger = logger
        self._port_allocator = port_allocator
        self._auth_provider = get_auth_provider()

    def create_server_instances(self, servers_config: list[ServerConfig]) -> Dict[str, ArangoServer]:
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

            self._logger.debug(f"Created server instance {server_id} with role {server_config.role.value} on port {server_config.port}")

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

    def _create_single_server(self, server_id: str, server_config: ServerConfig) -> ArangoServer:
        """Create a single ArangoServer instance with all dependencies."""
        # Validate port type
        port_value = server_config.port
        if not isinstance(port_value, int):
            raise ServerError(f"Invalid port type for {server_id}: {type(port_value)} (expected int)")

        # Create minimal config object to avoid port overrides
        minimal_config = MinimalConfig(
            args=server_config.args.copy(),
            memory_limit_mb=server_config.memory_limit_mb,
            startup_timeout=server_config.startup_timeout,
            data_dir=server_config.data_dir,
            log_file=server_config.log_file
        )

        # Create dependencies for this server
        command_builder = self._create_command_builder()
        health_checker = self._create_health_checker()

        # Create ArangoServer instance with all dependencies
        server = ArangoServer(
            server_id=server_id,
            role=server_config.role,
            port=port_value,
            config=minimal_config,
            config_provider=self._config_provider,
            logger=self._logger,
            port_allocator=self._port_allocator,
            command_builder=command_builder,
            health_checker=health_checker
        )

        # Configure server with deployment-specific settings
        self._configure_server_post_creation(server, server_config)

        return server

    def _create_command_builder(self) -> ServerCommandBuilder:
        """Create command builder with injected dependencies."""
        return ServerCommandBuilder(
            config_provider=self._config_provider,
            logger=self._logger
        )

    def _create_health_checker(self) -> ServerHealthChecker:
        """Create health checker with injected dependencies."""
        return ServerHealthChecker(
            logger=self._logger,
            auth_provider=self._auth_provider
        )

    def _configure_server_post_creation(self, server: ArangoServer, server_config: ServerConfig) -> None:
        """Configure server after creation with deployment-specific settings."""
        # Set directories from ServerConfig
        server.data_dir = server_config.data_dir
        server.log_file = server_config.log_file

        # Store the full ServerConfig for reference
        server._server_config = server_config
