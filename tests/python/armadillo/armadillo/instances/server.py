"""ArangoDB server instance wrapper with lifecycle management and health monitoring."""

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List

import aiohttp

from ..core.types import (
    ServerRole,
    ServerConfig,
    HealthStatus,
    ServerStats,
    ArmadilloConfig,
)
from ..core.errors import ServerStartupError, ServerShutdownError
from ..core.context import ApplicationContext
from ..core.value_objects import ServerId, ServerContext
from ..core.process import ProcessInfo
from ..core.log import get_logger, log_server_event, Logger
from ..core.time import clamp_timeout, timeout_scope
from ..utils.filesystem import FilesystemService
from ..utils.auth import AuthProvider
from .command_builder import CommandBuilder, ServerCommandBuilder
from .health_checker import HealthChecker, ServerHealthChecker
from .command_builder import ServerCommandParams

logger = get_logger(__name__)


@dataclass
class ServerPaths:
    """File system paths for an ArangoDB server."""

    base_dir: Path
    data_dir: Path
    app_dir: Path
    log_file: Path
    config: Optional[ServerConfig] = None  # Store config for command building

    @classmethod
    def from_config(
        cls,
        server_id: ServerId,
        config: Optional[ServerConfig],
        filesystem: FilesystemService,
    ) -> "ServerPaths":
        """Create server paths from configuration.

        Args:
            server_id: Unique server identifier
            config: Optional server configuration
            filesystem: Filesystem service for path derivation
        """
        if config and config.data_dir:
            data_dir = Path(config.data_dir)
            base_dir = data_dir.parent
            return cls(
                base_dir=base_dir,
                data_dir=data_dir,
                app_dir=base_dir / "apps",
                log_file=(
                    Path(config.log_file)
                    if config.log_file
                    else data_dir / "arangodb.log"
                ),
                config=config,
            )

        # Default directory structure
        base_dir = filesystem.server_dir(str(server_id))
        return cls(
            base_dir=base_dir,
            data_dir=base_dir / "data",
            app_dir=base_dir / "apps",
            log_file=base_dir / "arangodb.log",
            config=config,
        )


@dataclass
class ServerRuntimeState:
    """Runtime state for an ArangoDB server."""

    is_running: bool = False
    process_info: Optional[ProcessInfo] = None

    def start(self, process_info: ProcessInfo) -> None:
        """Mark server as running with process info."""
        self.is_running = True
        self.process_info = process_info

    def stop(self) -> None:
        """Mark server as stopped."""
        self.is_running = False
        self.process_info = None


@dataclass
class ArangoServerInfo:
    """Information about an ArangoDB server instance."""

    server_id: ServerId
    role: ServerRole
    port: int
    endpoint: str
    data_dir: Path
    log_file: Path
    process_info: Optional[ProcessInfo] = None


class ArangoServer:
    """Wrapper for individual ArangoDB server process with lifecycle management.

    This class uses dependency injection via ApplicationContext for clean, testable code.
    Use factory methods (create_single_server, create_cluster_server) for construction.
    """

    def __init__(
        self,
        server_id: ServerId,
        *,
        role: ServerRole,
        port: int,
        paths: ServerPaths,
        app_context: ApplicationContext,
    ) -> None:
        """Initialize ArangoDB server with explicit dependencies.

        Args:
            server_id: Unique server identifier
            role: Server role
            port: Port number
            paths: Server file system paths
            app_context: Application context with all dependencies
        """
        if not isinstance(port, int):
            raise TypeError(f"Port must be an integer, got {type(port)}: {port}")

        self.server_id = server_id
        self.role = role
        self.port = port
        self.paths = paths
        self._app_context = app_context
        self.endpoint = f"http://127.0.0.1:{self.port}"
        self._runtime = ServerRuntimeState()

        log_server_event(
            self._app_context.logger,
            "created",
            server_id=server_id,
            role=role.value,
            port=self.port,
        )

    @classmethod
    def create_single_server(
        cls,
        server_id: ServerId,
        app_context: ApplicationContext,
        port: Optional[int] = None,
        config: Optional[ServerConfig] = None,
    ) -> "ArangoServer":
        """Create a single server instance with sensible defaults.

        This is the recommended factory method for single server deployments.

        Args:
            server_id: Unique server identifier
            app_context: Application context with all dependencies
            port: Optional port number (auto-allocated if None)
            config: Optional server configuration with custom args

        Returns:
            Configured ArangoServer instance ready to start

        Example:
            >>> ctx = ApplicationContext.create(config)
            >>> server = ArangoServer.create_single_server(ServerId("srv1"), ctx)
            >>> server.start()
        """
        actual_port = port or app_context.port_allocator.allocate_port()
        paths = ServerPaths.from_config(server_id, config, app_context.filesystem)
        return cls(
            server_id,
            role=ServerRole.SINGLE,
            port=actual_port,
            paths=paths,
            app_context=app_context,
        )

    @classmethod
    def create_cluster_server(
        cls,
        server_id: ServerId,
        role: ServerRole,
        port: int,
        app_context: ApplicationContext,
        config: Optional[ServerConfig] = None,
    ) -> "ArangoServer":
        """Create a cluster server instance (agent, dbserver, coordinator).

        This is the recommended factory method for cluster deployments.

        Args:
            server_id: Unique server identifier
            role: Server role (AGENT, DBSERVER, COORDINATOR)
            port: Port number (must be pre-allocated for cluster coordination)
            app_context: Application context with all dependencies
            config: Optional server-specific configuration

        Returns:
            Configured ArangoServer instance ready to start

        Example:
            >>> ctx = ApplicationContext.create(config)
            >>> agent = ArangoServer.create_cluster_server(ServerId("agent1"), ServerRole.AGENT, 8529, ctx)
            >>> agent.start()
        """
        paths = ServerPaths.from_config(server_id, config, app_context.filesystem)
        return cls(
            server_id, role=role, port=port, paths=paths, app_context=app_context
        )

    def get_context(self) -> ServerContext:
        """Create diagnostic snapshot with server identity and runtime state."""
        process_info = self._runtime.process_info
        return ServerContext(
            server_id=self.server_id,
            role=self.role,
            pid=process_info.pid if process_info else None,
            port=self.port,
        )

    # Internal properties for dependency access
    @property
    def _logger(self) -> Logger:
        """Get logger instance from application context."""
        return self._app_context.logger

    @property
    def _config(self) -> "ArmadilloConfig":
        """Get configuration from application context."""
        return self._app_context.config

    @property
    def _auth(self) -> AuthProvider:
        """Get authentication provider from application context."""
        return self._app_context.auth_provider

    def _get_command_builder(self) -> CommandBuilder:
        """Get command builder - creates on demand from application context."""
        return ServerCommandBuilder(
            config_provider=self._config,
            logger=self._logger,
        )

    def _get_health_checker(self) -> HealthChecker:
        """Get health checker - creates on demand from application context."""
        return ServerHealthChecker(
            logger=self._logger,
            auth_provider=self._auth,
            process_supervisor=self._app_context.process_supervisor,
            timeout_config=self._config.timeouts,
        )

    def _release_port(self, port: int) -> None:
        """Release a port using the port allocator from application context."""
        self._app_context.port_allocator.release_port(port)

    def start(self, timeout: Optional[float] = None) -> None:
        """Start the ArangoDB server."""
        if self._runtime.is_running:
            raise ServerStartupError(f"Server {self.server_id} is already running")

        effective_timeout = clamp_timeout(
            timeout or 30.0, f"server_start_{self.server_id}"
        )

        log_server_event(self._logger, "starting", server_id=self.server_id)

        try:
            with timeout_scope(effective_timeout, f"start_server_{self.server_id}"):
                # Ensure directories exist before starting server
                self.paths.data_dir.mkdir(parents=True, exist_ok=True)
                self.paths.app_dir.mkdir(parents=True, exist_ok=True)

                # Build command line
                command = self._build_command()

                # Start supervised process from repository root (like old framework)
                repository_root = self._get_command_builder().get_repository_root()
                process_info = self._app_context.process_supervisor.start(
                    self.server_id,
                    command,
                    cwd=repository_root,
                    startup_timeout=effective_timeout,
                    readiness_check=self._check_readiness,
                    # ArangoDB writes directly to console - no buffering delays
                    inherit_console=True,
                )

                self._runtime.start(process_info)
                log_server_event(
                    self._logger,
                    "started",
                    server_id=self.server_id,
                    pid=process_info.pid,
                )
                self._logger.debug(
                    "Server %s started: pid=%d, port=%d, endpoint=%s",
                    self.server_id,
                    process_info.pid,
                    self.port,
                    self.endpoint,
                )

        except (OSError, TimeoutError, ProcessLookupError) as e:
            log_server_event(
                self._logger,
                "start_failed",
                server_id=self.server_id,
                error=str(e),
            )
            # Clean up on failure
            self._cleanup_on_failure()
            raise ServerStartupError(
                f"Failed to start server {self.server_id}: {e}"
            ) from e

    def stop(self, graceful: bool = True, timeout: Optional[float] = None) -> None:
        """Stop the ArangoDB server."""
        if not self._runtime.is_running:
            self._logger.warning(f"Server {self.server_id} is not running")
            return

        # Use configured timeout based on server role and graceful mode
        if timeout is None:
            if self.role == ServerRole.AGENT:
                timeout = self._config.timeouts.server_shutdown_agent
            else:
                timeout = self._config.timeouts.server_shutdown

        log_server_event(
            self._logger, "stopping", server_id=self.server_id, graceful=graceful
        )
        self._logger.debug(
            "Stopping server %s: pid=%d, graceful=%s, timeout=%.1fs",
            self.server_id,
            self._runtime.process_info.pid if self._runtime.process_info else 0,
            graceful,
            timeout,
        )

        try:
            self._app_context.process_supervisor.stop(
                self.server_id, graceful=graceful, timeout=timeout
            )
            log_server_event(self._logger, "stopped", server_id=self.server_id)
            self._logger.debug("Server %s stopped successfully", self.server_id)
        except (OSError, ProcessLookupError, TimeoutError) as e:
            log_server_event(
                self._logger, "stop_failed", server_id=self.server_id, error=str(e)
            )
            raise ServerShutdownError(
                f"Failed to stop server {self.server_id}: {e}"
            ) from e
        finally:
            self._runtime.stop()
            # Release allocated port
            self._release_port(self.port)

    def restart(self, timeout: float = 30.0) -> None:
        """Restart the ArangoDB server."""
        log_server_event(self._logger, "restarting", server_id=self.server_id)

        if self._runtime.is_running:
            self.stop(timeout=timeout / 2)

        self.start(timeout=timeout / 2)

        log_server_event(self._logger, "restarted", server_id=self.server_id)

    def is_running(self) -> bool:
        """Check if server process is running."""
        if not self._runtime.is_running:
            self._logger.debug("is_running(%s): _is_running=False", self.server_id)
            return False

        supervisor_result = self._app_context.process_supervisor.is_running(
            self.server_id
        )
        self._logger.debug(
            "is_running(%s): _is_running=True, supervisor=%s",
            self.server_id,
            supervisor_result,
        )
        return supervisor_result

    def health_check_sync(self, timeout: float = 5.0) -> HealthStatus:
        """Perform health check on the server.

        Delegates to the injected health_checker for actual health checking logic.
        """
        if not self.is_running():
            return HealthStatus(
                is_healthy=False,
                response_time=0.0,
                error_message="Server is not running",
            )

        return self._get_health_checker().check_health(self.endpoint, timeout=timeout)

    def get_stats_sync(self) -> Optional[ServerStats]:
        """Synchronous stats wrapper."""
        try:
            return asyncio.run(self.get_stats())
        except (asyncio.TimeoutError, RuntimeError, OSError) as e:
            logger.debug("Stats error for %s: %s", self.server_id, e)
            return None

    async def get_stats(self) -> Optional[ServerStats]:
        """Get server statistics."""
        if not self.is_running():
            return None

        try:
            async with aiohttp.ClientSession() as session:
                headers = self._auth.get_auth_headers()

                # Get basic server statistics
                stats_url = f"{self.endpoint}/_api/engine/stats"
                async with session.get(stats_url, headers=headers) as response:
                    if response.status == 200:
                        stats_data = await response.json()

                        # Get process info for additional metrics
                        process_stats = self._app_context.process_supervisor.get_stats(
                            self.server_id
                        )

                        return ServerStats(
                            pid=process_stats.pid if process_stats else 0,
                            memory_usage=(
                                process_stats.memory_rss if process_stats else 0
                            ),
                            cpu_percent=(
                                process_stats.cpu_percent if process_stats else 0.0
                            ),
                            connection_count=stats_data.get("client_connections", 0),
                            uptime=time.time()
                            - (
                                self._runtime.process_info.start_time
                                if self._runtime.process_info
                                else 0
                            ),
                            additional_metrics=stats_data,
                        )
                    return None
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
            logger.debug("Failed to get server stats: %s", e)
            return None

    def get_endpoint(self) -> str:
        """Get server endpoint URL.

        Returns:
            Server endpoint URL (e.g., "http://127.0.0.1:8529")
        """
        return self.endpoint

    def get_port(self) -> int:
        """Get server port number.

        Returns:
            Port number
        """
        return self.port

    def get_role(self) -> ServerRole:
        """Get server role.

        Returns:
            ServerRole enum value
        """
        return self.role

    def get_info(self) -> ArangoServerInfo:
        """Get server information."""
        return ArangoServerInfo(
            server_id=self.server_id,
            role=self.role,
            port=self.port,
            endpoint=self.endpoint,
            data_dir=self.paths.data_dir,
            log_file=self.paths.log_file,
            process_info=self._runtime.process_info,
        )

    def _build_command(self) -> List[str]:
        """Build ArangoDB command line using injected command builder."""
        params = ServerCommandParams(
            server_id=self.server_id,
            role=self.role,
            port=self.port,
            data_dir=self.paths.data_dir,
            app_dir=self.paths.app_dir,
            config=self.paths.config,
        )
        return self._get_command_builder().build_command(params)

    def _check_readiness(self) -> bool:
        """Check if server is ready to accept connections using injected health checker."""
        return self._get_health_checker().check_readiness(self.server_id, self.endpoint)

    def _cleanup_on_failure(self) -> None:
        """Clean up resources on startup failure."""
        try:
            if self.server_id and self._app_context.process_supervisor.is_running(
                self.server_id
            ):
                timeout = self._config.timeouts.process_force_kill
                self._app_context.process_supervisor.stop(
                    self.server_id, graceful=False, timeout=timeout
                )
        except (ProcessLookupError, OSError, TimeoutError) as e:
            logger.debug("Cleanup error for %s: %s", self.server_id, e)

        self._runtime.stop()
