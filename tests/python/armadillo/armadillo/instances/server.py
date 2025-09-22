"""ArangoDB server instance wrapper with lifecycle management and health monitoring."""

import asyncio
import builtins
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List

import aiohttp

from ..core.types import ServerRole, ServerConfig, HealthStatus, ServerStats
from ..core.errors import (
    ServerStartupError, ServerShutdownError
)
from ..core.config import get_config, ConfigProvider
from ..core.process import (
    start_supervised_process, stop_supervised_process, is_process_running,
    ProcessInfo, get_process_stats
)
from ..core.log import get_logger, log_server_event, Logger
from ..core.time import clamp_timeout, timeout_scope
from ..utils.filesystem import server_dir
from ..utils.ports import allocate_port, release_port, PortAllocator
from ..utils.auth import get_auth_provider
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
    def from_config(cls, server_id: str, config: Optional[ServerConfig]) -> 'ServerPaths':
        """Create server paths from configuration."""
        if config and config.data_dir:
            data_dir = Path(config.data_dir)
            base_dir = data_dir.parent
            return cls(
                base_dir=base_dir,
                data_dir=data_dir,
                app_dir=base_dir / "apps",
                log_file=Path(config.log_file) if config.log_file else data_dir / "arangodb.log",
                config=config
            )
        else:
            # Default directory structure
            base_dir = server_dir(server_id)
            return cls(
                base_dir=base_dir,
                data_dir=base_dir / "data",
                app_dir=base_dir / "apps",
                log_file=base_dir / "arangodb.log",
                config=config
            )

@dataclass
class ServerDependencies:
    """Injectable dependencies for ArangoServer."""
    config_provider: ConfigProvider
    logger: Logger
    port_allocator: Optional[PortAllocator]
    command_builder: CommandBuilder
    health_checker: HealthChecker
    auth_provider: 'AuthProvider'

    @classmethod
    def create_defaults(cls, custom_logger: Optional[Logger] = None,
                       port_allocator: Optional[PortAllocator] = None) -> 'ServerDependencies':
        """Create dependencies with sensible defaults."""
        config_provider = get_config()
        logger_instance = custom_logger or get_logger(__name__)
        auth_provider = get_auth_provider()
        
        return cls(
            config_provider=config_provider,
            logger=logger_instance,
            port_allocator=port_allocator,
            command_builder=ServerCommandBuilder(
                config_provider=config_provider,
                logger=logger_instance
            ),
            health_checker=ServerHealthChecker(
                logger=logger_instance,
                auth_provider=auth_provider
            ),
            auth_provider=auth_provider
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
    server_id: str
    role: ServerRole
    port: int
    endpoint: str
    data_dir: Path
    log_file: Path
    process_info: Optional[ProcessInfo] = None


class ArangoServer:
    """Wrapper for individual ArangoDB server process with lifecycle management."""

    def __init__(self,
                 server_id: str,
                 *,
                 role: ServerRole = ServerRole.SINGLE,
                 port: Optional[int] = None,
                 dependencies: Optional[ServerDependencies] = None,
                 **legacy_kwargs) -> None:
        """Initialize ArangoDB server with composition-based design.

        Args:
            server_id: Unique server identifier
            role: Server role (SINGLE, AGENT, DBSERVER, COORDINATOR)
            port: Port number (auto-allocated if None)
            dependencies: Injected dependencies (recommended approach)
            **legacy_kwargs: Backward compatibility support for:
                config_provider, logger, port_allocator, command_builder, health_checker, config
        """
        self.server_id = server_id
        self.role = role

        # Strict validation to prevent ServerConfig objects being assigned to port
        if port is not None and not isinstance(port, int):
            raise TypeError(f"Port must be an integer, got {type(port)}: {port}")

        # Initialize dependencies - handle both new and legacy parameter styles
        if dependencies is not None:
            self._deps = dependencies
        elif legacy_kwargs:
            # Legacy constructor - extract parameters from kwargs
            config_provider = legacy_kwargs.get('config_provider')
            logger_param = legacy_kwargs.get('logger')
            port_allocator = legacy_kwargs.get('port_allocator')
            command_builder = legacy_kwargs.get('command_builder')
            health_checker = legacy_kwargs.get('health_checker')
            config = legacy_kwargs.get('config')

            final_config_provider = config_provider or get_config()
            final_logger = logger_param or get_logger(__name__)
            final_auth_provider = get_auth_provider()

            self._deps = ServerDependencies(
                config_provider=final_config_provider,
                logger=final_logger,
                port_allocator=port_allocator,
                command_builder=command_builder or ServerCommandBuilder(
                    config_provider=final_config_provider,
                    logger=final_logger
                ),
                health_checker=health_checker or ServerHealthChecker(
                    logger=final_logger,
                    auth_provider=final_auth_provider
                ),
                auth_provider=final_auth_provider
            )
        else:
            # No dependencies provided, use defaults
            self._deps = ServerDependencies.create_defaults()

        # Port allocation
        self.port = port or self._allocate_port()
        self.endpoint = f"http://127.0.0.1:{self.port}"

        # Extract config from legacy_kwargs for path setup
        config = legacy_kwargs.get('config') if legacy_kwargs else None

        # Set up file system paths (which will store config if needed)
        self.paths = ServerPaths.from_config(server_id, config)

        # Consolidated runtime state
        self._runtime = ServerRuntimeState()

        log_server_event(
            self._deps.logger, "created", server_id=server_id, role=role.value, port=self.port
        )

    def _allocate_port(self, preferred: Optional[int] = None) -> int:
        """Allocate a port using injected allocator or fallback to global function."""
        if self._deps.port_allocator:
            return self._deps.port_allocator.allocate_port(preferred)
        return allocate_port(preferred)

    def _release_port(self, port: int) -> None:
        """Release a port using injected allocator or fallback to global function."""
        if self._deps.port_allocator:
            self._deps.port_allocator.release_port(port)
        else:
            release_port(port)

    def start(self, timeout: Optional[float] = None) -> None:
        """Start the ArangoDB server."""
        if self._runtime.is_running:
            raise ServerStartupError(f"Server {self.server_id} is already running")

        effective_timeout = clamp_timeout(timeout or 30.0, f"server_start_{self.server_id}")

        log_server_event(self._deps.logger, "starting", server_id=self.server_id)

        try:
            with timeout_scope(effective_timeout, f"start_server_{self.server_id}"):
                # Ensure directories exist before starting server
                self.paths.data_dir.mkdir(parents=True, exist_ok=True)
                self.paths.app_dir.mkdir(parents=True, exist_ok=True)

                # Build command line
                command = self._build_command()

                # Start supervised process from repository root (like old framework)
                repository_root = self._deps.command_builder.get_repository_root()
                process_info = start_supervised_process(
                    self.server_id,
                    command,
                    cwd=repository_root,
                    startup_timeout=effective_timeout,
                    readiness_check=self._check_readiness,
                    # ArangoDB writes directly to console - no buffering delays
                    inherit_console=True
                )

                self._runtime.start(process_info)
                log_server_event(self._deps.logger, "started", server_id=self.server_id,
                               pid=process_info.pid)

        except (OSError, TimeoutError, ProcessLookupError) as e:
            log_server_event(
                self._deps.logger, "start_failed", server_id=self.server_id, error=str(e)
            )
            # Clean up on failure
            self._cleanup_on_failure()
            raise ServerStartupError(f"Failed to start server {self.server_id}: {e}") from e

    def stop(self, graceful: bool = True, timeout: float = 30.0) -> None:
        """Stop the ArangoDB server."""
        if not self._runtime.is_running:
            self._deps.logger.warning(f"Server {self.server_id} is not running")
            return

        log_server_event(self._deps.logger, "stopping", server_id=self.server_id, graceful=graceful)

        try:
            stop_supervised_process(self.server_id, graceful=graceful, timeout=timeout)
            log_server_event(self._deps.logger, "stopped", server_id=self.server_id)
        except (OSError, ProcessLookupError, TimeoutError) as e:
            log_server_event(
                self._deps.logger, "stop_failed", server_id=self.server_id, error=str(e)
            )
            raise ServerShutdownError(f"Failed to stop server {self.server_id}: {e}") from e
        finally:
            self._runtime.stop()
            # Release allocated port
            self._release_port(self.port)

    def restart(self, timeout: float = 30.0) -> None:
        """Restart the ArangoDB server."""
        log_server_event(self._deps.logger, "restarting", server_id=self.server_id)

        if self._runtime.is_running:
            self.stop(timeout=timeout / 2)

        self.start(timeout=timeout / 2)

        log_server_event(self._deps.logger, "restarted", server_id=self.server_id)

    def is_running(self) -> bool:
        """Check if server process is running."""
        if not self._runtime.is_running:
            self._deps.logger.debug("is_running(%s): _is_running=False", self.server_id)
            return False

        supervisor_result = is_process_running(self.server_id)
        self._deps.logger.debug(
            "is_running(%s): _is_running=True, supervisor=%s",
            self.server_id, supervisor_result
        )
        return supervisor_result

    async def health_check(self, timeout: float = 5.0) -> HealthStatus:
        """Perform health check on the server."""
        if not self.is_running():
            return HealthStatus(
                is_healthy=False,
                response_time=0.0,
                error_message="Server is not running"
            )

        start_time = time.time()

        try:
            timeout_config = aiohttp.ClientTimeout(total=timeout)
            async with aiohttp.ClientSession(timeout=timeout_config) as session:
                headers = self._deps.auth_provider.get_auth_headers()

                url = f"{self.endpoint}/_api/version"
                async with session.get(url, headers=headers) as response:
                    response_time = time.time() - start_time

                    if response.status == 200:
                        details = await response.json()
                        return HealthStatus(
                            is_healthy=True,
                            response_time=response_time,
                            details=details
                        )

                    return HealthStatus(
                        is_healthy=False,
                        response_time=response_time,
                        error_message=f"HTTP {response.status}: {response.reason}"
                    )

        except asyncio.TimeoutError:
            response_time = time.time() - start_time
            return HealthStatus(
                is_healthy=False,
                response_time=response_time,
                error_message=f"Health check timed out after {timeout}s"
            )
        except (aiohttp.ClientError, OSError, builtins.ConnectionError) as e:
            response_time = time.time() - start_time
            return HealthStatus(
                is_healthy=False,
                response_time=response_time,
                error_message=f"Health check failed: {e}"
            )

    def health_check_sync(self, timeout: float = 5.0) -> HealthStatus:
        """Synchronous health check wrapper."""
        try:
            return asyncio.run(self.health_check(timeout))
        except (asyncio.TimeoutError, RuntimeError, OSError) as e:
            return HealthStatus(
                is_healthy=False,
                response_time=timeout,
                error_message=f"Health check error: {e}"
            )

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
                headers = self._deps.auth_provider.get_auth_headers()

                # Get basic server statistics
                stats_url = f"{self.endpoint}/_api/engine/stats"
                async with session.get(stats_url, headers=headers) as response:
                    if response.status == 200:
                        stats_data = await response.json()

                        # Get process info for additional metrics
                        process_stats = get_process_stats(self.server_id)

                        return ServerStats(
                            process_id=process_stats.pid if process_stats else 0,
                            memory_usage=process_stats.memory_rss if process_stats else 0,
                            cpu_percent=process_stats.cpu_percent if process_stats else 0.0,
                            connection_count=stats_data.get('client_connections', 0),
                            uptime=time.time() - (
                                self._runtime.process_info.start_time if self._runtime.process_info else 0
                            ),
                            additional_metrics=stats_data
                        )
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
            logger.debug("Failed to get server stats: %s", e)
            return None

    def get_info(self) -> ArangoServerInfo:
        """Get server information."""
        return ArangoServerInfo(
            server_id=self.server_id,
            role=self.role,
            port=self.port,
            endpoint=self.endpoint,
            data_dir=self.paths.data_dir,
            log_file=self.paths.log_file,
            process_info=self._runtime.process_info
        )


    def _build_command(self) -> List[str]:
        """Build ArangoDB command line using injected command builder."""
        params = ServerCommandParams(
            server_id=self.server_id,
            role=self.role,
            port=self.port,
            data_dir=self.paths.data_dir,
            app_dir=self.paths.app_dir,
            config=self.paths.config
        )
        return self._deps.command_builder.build_command(params)

    def _check_readiness(self) -> bool:
        """Check if server is ready to accept connections using injected health checker."""
        return self._deps.health_checker.check_readiness(self.server_id, self.endpoint)


    def _cleanup_on_failure(self) -> None:
        """Clean up resources on startup failure."""
        try:
            if self.server_id and is_process_running(self.server_id):
                stop_supervised_process(self.server_id, graceful=False, timeout=5.0)
        except (ProcessLookupError, OSError, TimeoutError) as e:
            logger.debug("Cleanup error for %s: %s", self.server_id, e)

        self._runtime.stop()

