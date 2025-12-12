"""Deployment Controller for orchestrating ArangoDB deployments.

This is the primary interface for managing ArangoDB deployments (single server or cluster).
It provides a simple, direct API without unnecessary layers:
- Factory methods for creating deployments
- Direct health checking (no HealthMonitor service)
- Direct crash callbacks (no CrashMonitor polling)
- Uniform server access via deployment.get_servers()
"""

from typing import Any, Callable, Dict, List, Optional, Type, Union
from types import TracebackType
from pathlib import Path
import time

from ..core.types import (
    ServerRole,
    ClusterConfig,
    HealthStatus,
    ServerHealthInfo,
    SanitizerError,
)
from ..core.context import ApplicationContext
from ..core.value_objects import ServerId, DeploymentId
from ..core.errors import (
    ServerStartupError,
    HealthCheckError,
)
from ..core.types import CrashInfo
from ..core.log import get_logger
from .server import ArangoServer
from .deployment import Deployment, SingleServerDeployment, ClusterDeployment
from .deployment_factory import DeploymentFactory

logger = get_logger(__name__)


class DeploymentController:
    """Controls lifecycle of a single ArangoDB deployment.

    This is the primary interface for test fixtures. It provides a simple,
    direct API without unnecessary layers.

    Factory methods create deployments:
        - create_single_server() for single server
        - create_cluster() for cluster

    Lifecycle methods:
        - start() starts all servers and registers crash monitoring
        - stop() stops servers in correct order
        - restart() restarts entire deployment

    Health checking:
        - check_health() directly iterates servers (no HealthMonitor service)
        - get_health_info() retrieves crash/exit info after shutdown

    Crash monitoring:
        - Registers callbacks with ProcessSupervisor for instant notification
        - No polling, no separate CrashMonitor service
    """

    def __init__(
        self,
        deployment: Deployment,
        app_context: ApplicationContext,
    ) -> None:
        """Initialize controller.

        Args:
            deployment: Deployment data object (passive, contains deployment_id)
            app_context: Application context with injected dependencies
        """
        self.deployment = deployment
        self._app_context = app_context
        self._crash_callbacks_registered = False

    @property
    def deployment_id(self) -> DeploymentId:
        """Get deployment ID from the deployment."""
        return self.deployment.deployment_id

    # Factory methods - Delegate to DeploymentFactory

    @classmethod
    def create_single_server(
        cls,
        deployment_id: DeploymentId,
        app_context: ApplicationContext,
        server_args: Optional[Dict[str, Any]] = None,
    ) -> "DeploymentController":
        """Create controller for single server deployment.

        Creates server, wraps in SingleServerDeployment, returns controller.

        Args:
            deployment_id: Unique identifier for this deployment
            app_context: Application context with dependencies
            server_args: Optional custom arguments to pass to ArangoDB server

        Returns:
            Controller ready to start

        Example:
            >>> ctx = ApplicationContext.create(config)
            >>> controller = DeploymentController.create_single_server(
            ...     DeploymentId("test-pkg"), ctx
            ... )
            >>> controller.start()
            >>>
            >>> # With custom server arguments
            >>> controller = DeploymentController.create_single_server(
            ...     DeploymentId("test-pkg"), ctx,
            ...     server_args={"log.level": "debug"}
            ... )
        """
        deployment = DeploymentFactory.create_single_server(
            deployment_id, app_context, server_args
        )
        return cls(deployment, app_context)

    @classmethod
    def create_cluster(
        cls,
        deployment_id: DeploymentId,
        app_context: ApplicationContext,
        cluster_config: ClusterConfig,
        server_args: Optional[Dict[str, Any]] = None,
    ) -> "DeploymentController":
        """Create controller for cluster deployment.

        Creates servers for all roles, wraps in ClusterDeployment, returns controller.

        Args:
            deployment_id: Unique identifier for this deployment
            app_context: Application context with dependencies
            cluster_config: Cluster topology (agents, dbservers, coordinators)
            server_args: Optional custom arguments to pass to all ArangoDB servers

        Returns:
            Controller ready to start

        Example:
            >>> config = ClusterConfig(agents=3, dbservers=2, coordinators=1)
            >>> controller = DeploymentController.create_cluster(
            ...     DeploymentId("test-pkg"), ctx, config
            ... )
            >>> controller.start()
        """
        deployment = DeploymentFactory.create_cluster(
            deployment_id, app_context, cluster_config, server_args
        )
        return cls(deployment, app_context)

    # Lifecycle methods

    def start(self, timeout: Optional[float] = None) -> None:
        """Start deployment: servers + crash monitoring.

        Steps:
        1. Register crash callbacks with ProcessSupervisor (before starting!)
        2. Start all servers (delegates to _start_servers)
        3. Verify all servers ready (direct health checks)
        4. Mark deployment as deployed

        Args:
            timeout: Maximum time for startup (uses config default if None)

        Raises:
            ServerStartupError: If any server fails to start
            TimeoutError: If startup exceeds timeout

        Example:
            >>> controller.start(timeout=60.0)
        """
        if timeout is None:
            if isinstance(self.deployment, SingleServerDeployment):
                timeout = self._app_context.config.timeouts.deployment_single
            else:
                timeout = self._app_context.config.timeouts.deployment_cluster

        logger.info("Starting deployment %s", self.deployment_id)

        # Register crash callbacks BEFORE starting servers to avoid race condition
        self._register_crash_callbacks()

        # Start servers (delegates based on type)
        self._start_servers(timeout)

        # Verify ready (direct health checks)
        self._verify_ready(timeout)

        # Mark deployed
        self.deployment.mark_deployed(time.time())

        logger.info("Deployment %s started successfully", self.deployment_id)

    def _start_servers(self, timeout: float) -> None:
        """Start all servers - delegates to cluster bootstrapper if cluster.

        Args:
            timeout: Maximum time for server startup
        """
        if isinstance(self.deployment, SingleServerDeployment):
            # Single server: just start it
            self.deployment.server.start(timeout)
        else:
            # Cluster: delegate to bootstrapper for ordering
            self._app_context.cluster_bootstrapper.bootstrap_cluster(
                self.deployment.get_servers(),
                timeout,
            )

    def _verify_ready(self, timeout: float) -> None:
        """Verify all servers ready - direct health checks, no HealthMonitor.

        Args:
            timeout: Maximum time for verification

        Raises:
            HealthCheckError: If servers not ready
        """
        start_time = time.time()
        not_ready = []

        for server_id, server in self.deployment.get_servers().items():
            elapsed = time.time() - start_time
            remaining = max(5.0, timeout - elapsed)

            # Direct call to server health check
            health = server.health_check_sync(timeout=remaining)
            if not health.is_healthy:
                not_ready.append(f"{server_id}: {health.error_message}")

        if not_ready:
            raise HealthCheckError(f"Servers not ready: {', '.join(not_ready)}")

    def _register_crash_callbacks(self) -> None:
        """Register crash callbacks with ProcessSupervisor - direct, no CrashMonitor."""
        for server_id in self.deployment.get_servers().keys():
            # Create callback with proper closure over server_id
            def make_callback(sid: ServerId) -> Callable[[CrashInfo], None]:
                return lambda info: self._handle_crash(sid, info)

            self._app_context.process_supervisor.register_crash_callback(
                server_id,
                make_callback(server_id),
            )
        self._crash_callbacks_registered = True

    def _handle_crash(self, server_id: ServerId, crash_info: CrashInfo) -> None:
        """Handle crash notification from ProcessSupervisor.

        Called directly by ProcessSupervisor when crash detected (instant notification).

        Args:
            server_id: ID of crashed server
            crash_info: Crash details
        """
        self._app_context.logger.error(
            "Server %s crashed: exit_code=%s, signal=%s",
            server_id,
            crash_info.exit_code,
            crash_info.signal,
        )
        self.deployment.mark_healthy(False)

    def stop(self, timeout: Optional[float] = None) -> None:
        """Stop deployment: servers in correct order.

        Steps:
        1. Stop all servers in correct order
           - Single: stop the server
           - Cluster: stop coordinators/dbservers, then agents
        2. Unregister crash callbacks
        3. Release resources (ports, etc.)
        4. Mark deployment as shutdown

        Args:
            timeout: Maximum time for shutdown (uses config default if None)

        Example:
            >>> controller.stop(timeout=30.0)
        """
        if timeout is None:
            num_servers = len(self.deployment.get_servers())
            timeout = (
                self._app_context.config.timeouts.server_shutdown
                * max(1, num_servers)
                * 1.2
            )

        logger.info("Stopping deployment %s", self.deployment_id)

        # Unregister crash callbacks
        if self._crash_callbacks_registered:
            for server_id in self.deployment.get_servers().keys():
                self._app_context.process_supervisor.unregister_crash_callback(
                    server_id
                )
            self._crash_callbacks_registered = False

        # Stop servers in correct order
        self._stop_servers(timeout)

        # Release ports
        self._release_ports()

        # Mark shutdown
        self.deployment.mark_shutdown(time.time())

        logger.info("Deployment %s stopped successfully", self.deployment_id)

    def _stop_servers(self, timeout: float) -> None:
        """Stop all servers in correct order.

        Args:
            timeout: Maximum time for server shutdown
        """
        if isinstance(self.deployment, SingleServerDeployment):
            # Single server: just stop it
            self.deployment.server.stop(timeout=timeout)
        else:
            # Cluster: stop coordinators/dbservers first, agents last
            servers = self.deployment.get_servers()

            # Stop non-agents
            for server in servers.values():
                if server.role != ServerRole.AGENT:
                    try:
                        server.stop(timeout=timeout)
                    except Exception as e:
                        logger.error("Error stopping %s: %s", server.server_id, e)

            # Stop agents last
            for server in servers.values():
                if server.role == ServerRole.AGENT:
                    try:
                        server.stop(timeout=timeout)
                    except Exception as e:
                        logger.error("Error stopping agent %s: %s", server.server_id, e)

    def _release_ports(self) -> None:
        """Release all allocated ports for this deployment."""
        for server in self.deployment.get_servers().values():
            port = server.get_port()
            try:
                self._app_context.port_allocator.release_port(port)
                logger.debug("Released port %s for server %s", port, server.server_id)
            except Exception as e:
                logger.warning("Error releasing port %s: %s", port, e)

    def restart(self, timeout: Optional[float] = None) -> None:
        """Restart entire deployment.

        Args:
            timeout: Maximum time for restart (split between stop and start)
        """
        if timeout is None:
            if isinstance(self.deployment, SingleServerDeployment):
                timeout = self._app_context.config.timeouts.deployment_single * 2
            else:
                timeout = self._app_context.config.timeouts.deployment_cluster * 2

        logger.info("Restarting deployment %s", self.deployment_id)

        # Stop and start
        self.stop(timeout=timeout / 2)
        self.start(timeout=timeout / 2)

        logger.info("Deployment %s restarted successfully", self.deployment_id)

    # Health checking - Direct, no HealthMonitor service

    def check_health(self, timeout: Optional[float] = None) -> HealthStatus:
        """Perform health check on all servers.

        Directly iterates servers calling server.health_check_sync(),
        aggregates results. No separate HealthMonitor service.

        Args:
            timeout: Maximum time for health check

        Returns:
            Aggregated health status for deployment

        Example:
            >>> health = controller.check_health()
            >>> if not health.is_healthy:
            ...     print(f"Unhealthy: {health.error_message}")
        """
        timeout = timeout or self._app_context.config.timeouts.health_check_default

        start_time = time.time()
        unhealthy_servers = []
        health_errors = []

        servers = self.deployment.get_servers()
        per_server_timeout = timeout / len(servers) if servers else timeout

        for server_id, server in servers.items():
            elapsed = time.time() - start_time
            remaining = max(1.0, timeout - elapsed)
            server_timeout = min(per_server_timeout, remaining)

            try:
                health = server.health_check_sync(timeout=server_timeout)
                if not health.is_healthy:
                    unhealthy_servers.append(server_id)
                    if health.error_message:
                        health_errors.append(f"{server_id}: {health.error_message}")
            except Exception as e:
                unhealthy_servers.append(server_id)
                health_errors.append(f"{server_id}: {e}")

        elapsed_time = time.time() - start_time
        is_healthy = len(unhealthy_servers) == 0

        # Update deployment health
        self.deployment.mark_healthy(is_healthy)

        if is_healthy:
            return HealthStatus(is_healthy=True, response_time=elapsed_time)

        error_msg = (
            f"{len(unhealthy_servers)}/{len(servers)} servers unhealthy: "
            f"{', '.join(str(sid) for sid in unhealthy_servers)}"
        )
        if health_errors:
            error_msg += f". Errors: {'; '.join(health_errors[:3])}"

        return HealthStatus(
            is_healthy=False,
            error_message=error_msg,
            response_time=elapsed_time,
        )

    def get_health_info(self) -> ServerHealthInfo:
        """Get health information after shutdown.

        Returns health data including:
        - Exit codes from shutdown (non-zero may indicate sanitizer issues)
        - Crash information if servers crashed
        - Sanitizer errors from log files (ASAN/LSAN/UBSAN/TSAN)

        Should be called after stop() to capture exit codes.

        Returns:
            ServerHealthInfo with crashes, exit codes, and sanitizer errors

        Example:
            >>> controller.stop()
            >>> health_info = controller.get_health_info()
            >>> if health_info.has_crashes():
            ...     pytest.fail(f"Server crashed: {health_info.crashes}")
        """
        all_exit_codes = self._app_context.process_supervisor.get_exit_codes()
        all_crashes = self._app_context.process_supervisor.get_crash_state()

        # Filter to this deployment's servers
        deployment_server_ids = set(self.deployment.get_servers().keys())

        filtered_exit_codes = {
            str(k): v for k, v in all_exit_codes.items() if k in deployment_server_ids
        }
        filtered_crashes = {
            str(k): v for k, v in all_crashes.items() if k in deployment_server_ids
        }

        sanitizer_errors = self._check_sanitizer_logs()

        return ServerHealthInfo(
            crashes=filtered_crashes,
            exit_codes=filtered_exit_codes,
            sanitizer_errors=sanitizer_errors,
        )

    def _check_sanitizer_logs(self) -> Dict[str, List[SanitizerError]]:
        """Check for sanitizer log files for all servers in deployment.

        Returns structured sanitizer data with timestamps for matching.

        Returns:
            Dictionary mapping server IDs to list of SanitizerError objects
        """
        sanitizer_errors: Dict[str, List[SanitizerError]] = {}

        for server_id, server in self.deployment.get_servers().items():
            sanitizer_handler = server.create_sanitizer_handler()
            if not sanitizer_handler:
                continue

            # Get PID for log file matching
            pid = server.get_pid()
            if not pid:
                continue

            # Get structured sanitizer errors with timestamps
            san_errors = sanitizer_handler.check_sanitizer_logs(pid)

            # Set server_id on each error
            for error in san_errors:
                error.server_id = str(server_id)

            if san_errors:
                sanitizer_errors[str(server_id)] = san_errors

        return sanitizer_errors

    # Properties

    @property
    def endpoint(self) -> str:
        """Primary coordination endpoint.

        For single server: the server endpoint
        For cluster: first coordinator endpoint

        Returns:
            Endpoint URL (e.g., "http://127.0.0.1:8529")
        """
        return self.deployment.get_coordination_endpoints()[0]

    @property
    def endpoints(self) -> List[str]:
        """All coordination endpoints.

        For single server: list with one endpoint
        For cluster: all coordinator endpoints

        Returns:
            List of endpoint URLs
        """
        return self.deployment.get_coordination_endpoints()

    @property
    def agency_endpoints(self) -> List[str]:
        """Agency endpoints (cluster only).

        Returns:
            List of agency endpoints (empty for single server)
        """
        return self.deployment.get_agency_endpoints()

    @property
    def is_healthy(self) -> bool:
        """Current health status (from last check).

        Note: This reflects the last health check result.
        Call check_health() to perform a fresh check.

        Returns:
            True if deployment is healthy, False otherwise
        """
        return self.deployment.is_healthy()

    # Context manager support

    def __enter__(self) -> "DeploymentController":
        """Context manager entry - no-op, use start() explicitly."""
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        """Context manager exit - ensure cleanup.

        Stops servers even if exception occurred.
        """
        try:
            if self.deployment.is_deployed():
                self.stop()
        except Exception as e:
            logger.error("Error during context manager cleanup: %s", e)
