"""ArangoDB server instance wrapper with lifecycle management and health monitoring."""

import asyncio
import aiohttp
import time
from pathlib import Path
from typing import Optional, Dict, List, Any
from dataclasses import dataclass

from ..core.types import ServerRole, ServerConfig, HealthStatus, ServerStats
from ..core.errors import (
    ServerError, ServerStartupError, ServerShutdownError,
    HealthCheckError, NetworkError, ConnectionError
)
from ..core.config import get_config, ConfigProvider
from ..core.process import start_supervised_process, stop_supervised_process, is_process_running, ProcessInfo
from ..core.log import get_logger, log_server_event, Logger
from ..core.time import clamp_timeout, timeout_scope
from ..utils.filesystem import server_dir, atomic_write
from ..utils.ports import allocate_port, release_port
from ..utils.auth import get_auth_provider

logger = get_logger(__name__)


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
                 role: ServerRole = ServerRole.SINGLE,
                 port: Optional[int] = None,
                 config: Optional[ServerConfig] = None,
                 config_provider: Optional[ConfigProvider] = None,
                 logger: Optional[Logger] = None) -> None:
        self.server_id = server_id
        self.role = role

        # Strict validation to prevent ServerConfig objects being assigned to port
        if port is not None and not isinstance(port, int):
            raise TypeError(f"Port must be an integer, got {type(port)}: {port}")

        self.port = port or allocate_port()
        self.endpoint = f"http://127.0.0.1:{self.port}"

        # Set up directories
        self.base_dir = server_dir(server_id)
        self.data_dir = self.base_dir / "data"
        self.app_dir = self.base_dir / "apps"
        self.log_file = self.base_dir / "arangodb.log"

        # Ensure directories exist
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.app_dir.mkdir(parents=True, exist_ok=True)

        # Server configuration
        self.config = config
        self._config_provider = config_provider or get_config()
        self._logger = logger or get_logger(__name__)
        self._is_running = False
        self._process_info: Optional[ProcessInfo] = None

        # Authentication
        self.auth_provider = get_auth_provider()

        log_server_event(self._logger, "created", server_id=server_id, role=role.value, port=self.port)

    def start(self, timeout: Optional[float] = None) -> None:
        """Start the ArangoDB server."""
        if self._is_running:
            raise ServerStartupError(f"Server {self.server_id} is already running")

        effective_timeout = clamp_timeout(timeout or 30.0, f"server_start_{self.server_id}")

        log_server_event(self._logger, "starting", server_id=self.server_id)

        try:
            with timeout_scope(effective_timeout, f"start_server_{self.server_id}"):
                # Build command line
                command = self._build_command()

                # Start supervised process from repository root (like old framework)
                repository_root = self._get_repository_root()
                self._process_info = start_supervised_process(
                    self.server_id,
                    command,
                    cwd=repository_root,
                    startup_timeout=effective_timeout,
                    readiness_check=lambda: self._check_readiness(),
                    inherit_console=True  # ArangoDB writes directly to console - no buffering delays
                )

                self._is_running = True
                log_server_event(self._logger, "started", server_id=self.server_id,
                               pid=self._process_info.pid)

        except Exception as e:
            log_server_event(self._logger, "start_failed", server_id=self.server_id, error=str(e))
            # Clean up on failure
            self._cleanup_on_failure()
            raise ServerStartupError(f"Failed to start server {self.server_id}: {e}") from e

    def stop(self, graceful: bool = True, timeout: float = 30.0) -> None:
        """Stop the ArangoDB server."""
        if not self._is_running:
            self._logger.warning(f"Server {self.server_id} is not running")
            return

        log_server_event(self._logger, "stopping", server_id=self.server_id, graceful=graceful)

        try:
            stop_supervised_process(self.server_id, graceful=graceful, timeout=timeout)
            log_server_event(self._logger, "stopped", server_id=self.server_id)
        except Exception as e:
            log_server_event(self._logger, "stop_failed", server_id=self.server_id, error=str(e))
            raise ServerShutdownError(f"Failed to stop server {self.server_id}: {e}") from e
        finally:
            self._is_running = False
            self._process_info = None
            # Release allocated port
            release_port(self.port)

    def restart(self, wait_ready: bool = True, timeout: float = 30.0) -> None:
        """Restart the ArangoDB server."""
        log_server_event(self._logger, "restarting", server_id=self.server_id)

        if self._is_running:
            self.stop(timeout=timeout / 2)

        self.start(timeout=timeout / 2)

        log_server_event(self._logger, "restarted", server_id=self.server_id)

    def is_running(self) -> bool:
        """Check if server process is running."""
        if not self._is_running:
            self._logger.debug(f"is_running({self.server_id}): _is_running=False")
            return False

        supervisor_result = is_process_running(self.server_id)
        self._logger.debug(f"is_running({self.server_id}): _is_running=True, supervisor={supervisor_result}")
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
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
                headers = self.auth_provider.get_auth_headers()

                async with session.get(f"{self.endpoint}/_api/version", headers=headers) as response:
                    response_time = time.time() - start_time

                    if response.status == 200:
                        details = await response.json()
                        return HealthStatus(
                            is_healthy=True,
                            response_time=response_time,
                            details=details
                        )
                    else:
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
        except Exception as e:
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
        except Exception as e:
            return HealthStatus(
                is_healthy=False,
                response_time=timeout,
                error_message=f"Health check error: {e}"
            )

    def get_stats_sync(self) -> Optional[ServerStats]:
        """Synchronous stats wrapper."""
        try:
            return asyncio.run(self.get_stats())
        except Exception as e:
            logger.debug(f"Stats error for {self.server_id}: {e}")
            return None

    async def get_stats(self) -> Optional[ServerStats]:
        """Get server statistics."""
        if not self.is_running():
            return None

        try:
            async with aiohttp.ClientSession() as session:
                headers = self.auth_provider.get_auth_headers()

                # Get basic server statistics
                async with session.get(f"{self.endpoint}/_api/engine/stats", headers=headers) as response:
                    if response.status == 200:
                        stats_data = await response.json()

                        # Get process info for additional metrics
                        from ..core.process import get_process_stats
                        process_stats = get_process_stats(self.server_id)

                        return ServerStats(
                            process_id=process_stats.pid if process_stats else 0,
                            memory_usage=process_stats.memory_rss if process_stats else 0,
                            cpu_percent=process_stats.cpu_percent if process_stats else 0.0,
                            connection_count=stats_data.get('client_connections', 0),
                            uptime=time.time() - (self._process_info.start_time if self._process_info else 0),
                            additional_metrics=stats_data
                        )
        except Exception as e:
            logger.debug(f"Failed to get server stats: {e}")
            return None

    def get_info(self) -> ArangoServerInfo:
        """Get server information."""
        return ArangoServerInfo(
            server_id=self.server_id,
            role=self.role,
            port=self.port,
            endpoint=self.endpoint,
            data_dir=self.data_dir,
            log_file=self.log_file,
            process_info=self._process_info
        )

    def _get_repository_root(self) -> Path:
        """Get the ArangoDB repository root directory."""
        if self._config_provider.bin_dir:
            # Derive repository root from build directory
            # Examples: build-clang/bin -> repository root is ../..
            #           build/bin -> repository root is ../..
            #           bin -> repository root is ..
            bin_path = Path(self._config_provider.bin_dir)
            if bin_path.name == "bin" and bin_path.parent.exists():
                # build-clang/bin -> build-clang -> repository_root
                repository_root = bin_path.parent.parent
            else:
                # build-clang -> repository_root
                repository_root = bin_path.parent

            # Validate by checking for expected directories
            if (repository_root / "js").exists() and (repository_root / "etc").exists():
                return repository_root

        # Fallback: assume current working directory is repository root
        cwd = Path.cwd()
        if (cwd / "js").exists() and (cwd / "etc").exists():
            return cwd

        # Last resort: go up directory tree looking for repository root
        search_path = Path.cwd()
        for _ in range(5):  # Don't search too far up
            if (search_path / "js").exists() and (search_path / "etc").exists():
                return search_path
            search_path = search_path.parent

        # If all else fails, use current directory
        logger.warning("Could not determine repository root, using current working directory")
        return Path.cwd()

    def _get_config_file_for_role(self) -> str:
        """Get the appropriate config file for the server role."""
        if self.role == ServerRole.SINGLE:
            return "etc/testing/arangod-single.conf"
        elif self.role == ServerRole.AGENT:
            return "etc/testing/arangod-agent.conf"
        elif self.role == ServerRole.COORDINATOR:
            return "etc/testing/arangod-coordinator.conf"
        elif self.role == ServerRole.DBSERVER:
            return "etc/testing/arangod-dbserver.conf"
        else:
            # Default fallback
            return "etc/testing/arangod.conf"

    def _build_command(self) -> List[str]:
        """Build ArangoDB command line."""
        repository_root = self._get_repository_root()

        # Get arangod binary path
        if self._config_provider.bin_dir:
            arangod_path = str(self._config_provider.bin_dir / "arangod")
        else:
            # Fallback to arangod in PATH (likely to fail, but maintains compatibility)
            arangod_path = "arangod"

        # Build command following old framework approach
        command = [
            arangod_path,
            # Use config file and define TOP_DIR (like old framework)
            "--configuration", self._get_config_file_for_role(),
            "--define", f"TOP_DIR={repository_root}",
            # Server-specific parameters
            "--server.endpoint", f"tcp://0.0.0.0:{self.port}",
            "--database.directory", str(self.data_dir),
            "--javascript.app-path", str(self.app_dir)
        ]

        # Add role-specific arguments
        if self.role == ServerRole.SINGLE:
            command.extend([
                "--server.storage-engine", "rocksdb"
            ])
        elif self.role == ServerRole.AGENT:
            command.extend([
                "--agency.activate", "true",
                "--agency.size", "3",
                "--agency.supervision", "true"
            ])
        elif self.role in [ServerRole.COORDINATOR, ServerRole.DBSERVER]:
            command.extend([
                "--cluster.create-waits-for-sync-replication", "false",
                "--cluster.write-concern", "1"
            ])

        # Add custom arguments from config
        if self.config and self.config.args:
            for key, value in self.config.args.items():
                command.extend([f"--{key}", str(value)])

        # Log the complete command for debugging
        logger.info(f">>> ARANGOD COMMAND FOR {self.server_id} <<<")
        logger.info(f"Command: {' '.join(command)}")
        logger.info(f">>> END ARANGOD COMMAND <<<")
        return command

    def _check_readiness(self) -> bool:
        """Check if server is ready to accept connections."""
        try:
            # During startup, don't use self.is_running() as it creates circular dependency
            # Just check if the process is running via supervisor and test HTTP connection
            if not is_process_running(self.server_id):
                logger.debug(f"Readiness check failed for {self.server_id}: Process not running")
                return False

            # Make direct HTTP health check without using self.is_running()
            health = self._direct_health_check(timeout=2.0)
            if not health.is_healthy:
                logger.debug(f"Readiness check failed for {self.server_id}: {health.error_message}")
            return health.is_healthy
        except Exception as e:
            logger.debug(f"Readiness check exception for {self.server_id}: {e}")
            return False

    def _direct_health_check(self, timeout: float = 5.0) -> HealthStatus:
        """Direct health check without using self.is_running() to avoid circular dependency."""
        start_time = time.time()

        try:
            # Use asyncio.run to make direct HTTP request
            return asyncio.run(self._async_direct_health_check(timeout))
        except Exception as e:
            response_time = time.time() - start_time
            return HealthStatus(
                is_healthy=False,
                response_time=response_time,
                error_message=f"Direct health check error: {e}"
            )

    async def _async_direct_health_check(self, timeout: float) -> HealthStatus:
        """Async direct health check implementation."""
        start_time = time.time()

        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
                headers = self.auth_provider.get_auth_headers()

                async with session.get(f"{self.endpoint}/_api/version", headers=headers) as response:
                    response_time = time.time() - start_time

                    if response.status == 200:
                        details = await response.json()
                        return HealthStatus(
                            is_healthy=True,
                            response_time=response_time,
                            details=details
                        )
                    else:
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
                error_message="Connection timeout"
            )
        except Exception as e:
            response_time = time.time() - start_time
            return HealthStatus(
                is_healthy=False,
                response_time=response_time,
                error_message=f"Connection error: {e}"
            )

    def _cleanup_on_failure(self) -> None:
        """Clean up resources on startup failure."""
        try:
            if self.server_id and is_process_running(self.server_id):
                stop_supervised_process(self.server_id, graceful=False, timeout=5.0)
        except Exception as e:
            logger.debug(f"Cleanup error for {self.server_id}: {e}")

        self._is_running = False
        self._process_info = None

