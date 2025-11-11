"""Instance Manager for multi-server orchestration and lifecycle management."""

from typing import Dict, List, Optional, Any
import time
from concurrent.futures import ThreadPoolExecutor
import threading
from dataclasses import dataclass, field

from ..core.types import (
    ServerRole,
    ClusterConfig,
    HealthStatus,
    ServerStats,
    ServerHealthInfo,
)
from ..core.config import get_config
from ..core.context import ApplicationContext
from ..core.value_objects import ServerId, DeploymentId
from ..core.errors import (
    ServerError,
    ServerStartupError,
    ServerShutdownError,
    ProcessError,
    ProcessStartupError,
    ProcessTimeoutError,
    ArmadilloTimeoutError,
)
from ..core.log import get_logger, log_server_event
from ..core.time import timeout_scope, clamp_timeout
from ..core.process import stop_supervised_process
from .server import ArangoServer
from .deployment_plan import DeploymentPlan, SingleServerDeploymentPlan
from .health_monitor import HealthMonitor
from .deployment_orchestrator import DeploymentOrchestrator

logger = get_logger(__name__)


@dataclass
class DeploymentStatus:
    """Status information for a deployment."""

    is_deployed: bool = False
    is_healthy: bool = False


@dataclass
class DeploymentTiming:
    """Timing information for a deployment."""

    startup_time: Optional[float] = None
    shutdown_time: Optional[float] = None


@dataclass
class DeploymentState:
    """Runtime state of a deployment."""

    servers: Dict[ServerId, ArangoServer] = field(default_factory=dict)
    deployment_plan: Optional[DeploymentPlan] = None
    startup_order: List[ServerId] = field(default_factory=list)
    shutdown_order: List[ServerId] = field(default_factory=list)
    status: DeploymentStatus = field(default_factory=DeploymentStatus)
    timing: DeploymentTiming = field(default_factory=DeploymentTiming)


@dataclass
class ThreadingResources:
    """Threading resources for parallel operations."""

    executor: ThreadPoolExecutor
    lock: threading.RLock

    @classmethod
    def create_for_deployment(cls, deployment_id: DeploymentId) -> "ThreadingResources":
        """Create threading resources for a deployment."""
        config = get_config()
        return cls(
            executor=ThreadPoolExecutor(
                max_workers=config.infrastructure.manager_max_workers,
                thread_name_prefix=f"InstanceMgr-{deployment_id}",
            ),
            lock=threading.RLock(),
        )

    def cleanup(self) -> None:
        """Clean up threading resources."""
        self.executor.shutdown(wait=True)


class InstanceManager:
    """Manages lifecycle of multiple ArangoDB server instances."""

    def __init__(
        self,
        deployment_id: DeploymentId,
        *,
        app_context: ApplicationContext,
    ) -> None:
        """Initialize instance manager with application context.

        Args:
            deployment_id: Unique identifier for this deployment
            app_context: Application context with all dependencies
        """
        self.deployment_id = deployment_id
        self._app_context = app_context

        # Initialize runtime state and threading resources
        self.state = DeploymentState()
        self._threading = ThreadingResources.create_for_deployment(deployment_id)

        # Initialize architectural components
        self._health_monitor = HealthMonitor(
            self._app_context.logger, self._app_context.config.timeouts
        )
        self._deployment_orchestrator = DeploymentOrchestrator(
            logger=self._app_context.logger,
            server_factory=self._app_context.server_factory,
            executor=self._threading.executor,
            health_monitor=self._health_monitor,
            timeout_config=self._app_context.config.timeouts,
        )

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        try:
            if self.state.status.is_deployed:
                self.shutdown_deployment()
        finally:
            self._threading.executor.shutdown(wait=True)

    def create_single_server_plan(self) -> "SingleServerDeploymentPlan":
        """Create deployment plan for single server.

        This is a pure function that creates and returns a plan without side effects.

        Returns:
            Single server deployment plan
        """
        return self._app_context.deployment_planner.create_single_server_plan(
            self.deployment_id
        )

    def create_deployment_plan(
        self, cluster_config: Optional[ClusterConfig] = None
    ) -> DeploymentPlan:
        """Create deployment plan for cluster using injected planner.

        This is a pure function that creates and returns a plan without side effects.

        Args:
            cluster_config: Cluster configuration (uses default if None)

        Returns:
            Deployment plan
        """
        # Use default cluster config if none provided
        if cluster_config is None:
            cluster_config = self._app_context.config.cluster

        return self._app_context.deployment_planner.create_cluster_plan(
            deployment_id=self.deployment_id, cluster_config=cluster_config
        )

    def deploy_servers(self, plan: DeploymentPlan, timeout: float = 300.0) -> None:
        """Deploy all servers according to the provided plan.

        Args:
            plan: Deployment plan with server configurations
            timeout: Maximum time to wait for deployment

        Raises:
            ServerStartupError: If server deployment fails
            TimeoutError: If deployment times out
        """
        if self.state.status.is_deployed:
            raise ServerError("Deployment already active")

        # Store the plan being deployed
        self.state.deployment_plan = plan
        timeout = clamp_timeout(timeout, "deployment")

        with timeout_scope(timeout, f"deploy_servers_{self.deployment_id}"):
            from .deployment_plan import SingleServerDeploymentPlan

            # Determine number of servers based on plan type
            num_servers = (
                1 if isinstance(plan, SingleServerDeploymentPlan) else len(plan.servers)
            )
            logger.info("Starting deployment of %s servers", num_servers)
            self.state.timing.startup_time = time.time()

            try:
                # Delegate to DeploymentOrchestrator for the actual deployment
                self._deployment_orchestrator.execute_deployment(plan, timeout=timeout)

                # Sync state from orchestrator internal dict (new lifecycle path)
                self._sync_state_from_orchestrator()

                # Mark deployment as active
                self.state.status.is_deployed = True
                self.state.status.is_healthy = True

                deployment_time = time.time() - self.state.timing.startup_time
                logger.info(
                    "Deployment completed successfully in %.2fs", deployment_time
                )

            except (
                ServerStartupError,
                ProcessStartupError,
                ProcessTimeoutError,
                OSError,
                ArmadilloTimeoutError,
            ) as e:
                logger.error("Deployment failed: %s", e)
                # Try to cleanup partial deployment
                try:
                    self.shutdown_deployment()
                except (OSError, ProcessLookupError, RuntimeError, AttributeError):
                    # Cleanup errors are acceptable - we're already in error handling
                    pass
                raise ServerStartupError(f"Failed to deploy servers: {e}") from e

    def _sync_state_from_orchestrator(self) -> None:
        """Synchronize state from DeploymentOrchestrator internal storage (lifecycle strategies).

        The orchestrator now owns the authoritative servers dict; we mirror it for facade access.
        """
        self.state.servers = self._deployment_orchestrator.get_servers()
        self.state.startup_order = self._deployment_orchestrator.get_startup_order()

    def shutdown_deployment(self, timeout: Optional[float] = None) -> None:
        """Shutdown all deployed servers in correct order.

        For clusters, agents are shut down LAST after all other servers.

        Args:
            timeout: Maximum time to wait for shutdown (uses config default if None)
        """
        if not self.state.status.is_deployed:
            logger.debug("No deployment to shutdown")
            return

        # Use config default if not specified (scales with server count)
        if timeout is None:
            num_servers = len(self.state.servers)
            timeout = (
                self._app_context.config.timeouts.server_shutdown
                * max(1, num_servers)
                * 1.2
            )

        timeout = clamp_timeout(timeout, "shutdown")
        self.state.timing.shutdown_time = time.time()

        logger.debug(
            "InstanceManager.shutdown_deployment: deployment_id=%s, servers=%d",
            self.deployment_id,
            len(self.state.servers),
        )

        with timeout_scope(timeout, f"shutdown_deployment_{self.deployment_id}"):
            try:
                # Delegate to DeploymentOrchestrator for shutdown
                shutdown_order = list(reversed(self.state.startup_order))
                logger.debug(
                    "Calling DeploymentOrchestrator.shutdown_deployment with order: %s",
                    shutdown_order,
                )
                self._deployment_orchestrator.shutdown_deployment(
                    shutdown_order=shutdown_order, timeout=timeout
                )
                logger.debug(
                    "DeploymentOrchestrator.shutdown_deployment completed successfully"
                )
            except (ServerShutdownError, ProcessError, OSError, RuntimeError) as e:
                logger.error("Shutdown via orchestrator failed: %s", e)
                # Fallback to direct shutdown if orchestrator fails
                self._direct_shutdown_deployment()

            # Release allocated ports
            self._release_ports()

            # Clear state
            self.state.servers.clear()
            self.state.startup_order.clear()
            self.state.shutdown_order.clear()
            self.state.status.is_deployed = False
            self.state.status.is_healthy = False

            shutdown_time = time.time() - self.state.timing.shutdown_time
            logger.info("Deployment shutdown completed in %.2fs", shutdown_time)

    def get_server_health(self) -> ServerHealthInfo:
        """Collect server health information after deployment shutdown.

        Returns health data including:
        - Exit codes from intentional shutdown (non-zero may indicate sanitizer issues)
        - Crash information from unexpected termination

        Should be called after shutdown_deployment() to capture exit codes.

        Returns:
            ServerHealthInfo with crashes and exit codes (filtered to this deployment's servers)
        """
        from ..core.process import _process_supervisor

        # Get all health data from the global supervisor
        all_exit_codes = _process_supervisor.get_exit_codes()
        all_crashes = _process_supervisor.get_crash_state()

        # Get the set of server IDs that belong to this deployment
        deployment_server_ids = set(self.state.servers.keys())

        # Filter to only include servers from THIS deployment
        relevant_crashes = {
            server_id: crash_info
            for server_id, crash_info in all_crashes.items()
            if server_id in deployment_server_ids
        }
        relevant_exit_codes = {
            server_id: exit_code
            for server_id, exit_code in all_exit_codes.items()
            if server_id in deployment_server_ids
        }

        # Convert to string keys for ServerHealthInfo (it uses Dict[str, ...])
        return ServerHealthInfo(
            crashes={str(k): v for k, v in relevant_crashes.items()},
            exit_codes={str(k): v for k, v in relevant_exit_codes.items()},
        )

    def _direct_shutdown_deployment(self) -> None:
        """Direct shutdown implementation as fallback when orchestrator fails.

        Uses fixed timeouts from configuration based on server roles.
        """
        logger.info("Using direct shutdown for %d servers", len(self.state.servers))

        # Shutdown in reverse startup order, but agents go LAST
        shutdown_order = list(reversed(self.state.startup_order))

        # Separate agents from non-agents
        agents = []
        non_agents = []
        for server_id in shutdown_order:
            if server_id in self.state.servers:
                server = self.state.servers[server_id]
                if server.role == ServerRole.AGENT:
                    agents.append(server)
                else:
                    non_agents.append(server)

        # Log shutdown order
        if non_agents or agents:
            order_names = [s.server_id for s in non_agents] + [
                s.server_id for s in agents
            ]
            logger.info("Shutdown order: %s", " -> ".join(order_names))

        failed_shutdowns = []

        # Phase 1: Shutdown non-agent servers (coordinators, dbservers, single servers)
        if non_agents:
            logger.debug("Phase 1: Shutting down %d non-agent servers", len(non_agents))
            for server in non_agents:
                try:
                    timeout = self._app_context.config.timeouts.server_shutdown
                    self._shutdown_server(server, timeout=timeout)
                except (OSError, ServerShutdownError) as e:
                    logger.error(
                        "Failed to shutdown server %s: %s", server.server_id, e
                    )
                    failed_shutdowns.append(server.server_id)

        # Phase 2: Shutdown agents AFTER all non-agents are down
        if agents:
            logger.debug("Phase 2: Shutting down %d agent servers", len(agents))
            for server in agents:
                try:
                    # Agents get extra timeout
                    timeout = self._app_context.config.timeouts.server_shutdown_agent
                    self._shutdown_server(server, timeout=timeout)
                except (OSError, ServerShutdownError) as e:
                    logger.error("Failed to shutdown agent %s: %s", server.server_id, e)
                    failed_shutdowns.append(server.server_id)

        if failed_shutdowns:
            logger.warning(
                "Some servers failed to shutdown cleanly: %s", failed_shutdowns
            )

    def _shutdown_server(
        self, server: "ArangoServer", timeout: Optional[float] = None
    ) -> None:
        """Shutdown a single server with bulletproof termination and polling.

        Combines graceful shutdown with emergency force kill fallback and
        polling to ensure the server actually stops before continuing.

        Args:
            server: The server instance to shutdown
            timeout: Maximum time to wait for shutdown (uses config default if None)
        """
        if timeout is None:
            timeout = self._app_context.config.timeouts.server_shutdown

        if not server.is_running():
            logger.debug("Server %s already stopped", server.server_id)
            return

        logger.info(
            "Shutting down server: %s (role: %s)", server.server_id, server.role.value
        )
        start_time = time.time()

        try:
            log_server_event(
                logger, "stopping", server_id=server.server_id, timeout=timeout
            )

            # Try to stop the server gracefully first
            if hasattr(server, "stop") and callable(server.stop):
                server.stop(timeout=timeout)
            else:
                # Fallback: stop via process supervisor
                if server.is_running():
                    stop_supervised_process(
                        server.server_id, graceful=True, timeout=timeout
                    )

            # Poll to ensure server actually stops
            poll_interval = (
                self._app_context.config.infrastructure.server_shutdown_poll_interval
            )
            while server.is_running():
                elapsed = time.time() - start_time
                if elapsed > timeout:
                    raise ServerShutdownError(
                        f"Server {server.server_id} failed to stop within {timeout}s"
                    )
                logger.debug(
                    "Waiting for server %s to stop (%.1fs elapsed)...",
                    server.server_id,
                    elapsed,
                )
                time.sleep(poll_interval)

            shutdown_time = time.time() - start_time
            log_server_event(logger, "stopped", server_id=server.server_id)
            logger.info(
                "Server %s stopped successfully (%.2fs)",
                server.server_id,
                shutdown_time,
            )

        except (ServerShutdownError, ProcessError, OSError) as e:
            log_server_event(
                logger, "stop_failed", server_id=server.server_id, error=str(e)
            )
            logger.error("Failed to shutdown server %s: %s", server.server_id, e)

            # Try emergency force kill if graceful shutdown failed
            try:
                logger.warning(
                    "Attempting emergency force kill of server %s", server.server_id
                )
                if server.is_running():
                    timeout = self._app_context.config.timeouts.process_force_kill
                    stop_supervised_process(
                        server.server_id, graceful=False, timeout=timeout
                    )
                    logger.info(
                        "Emergency force kill of server %s succeeded", server.server_id
                    )
            except (OSError, PermissionError, ProcessError) as force_e:
                logger.error(
                    "CRITICAL: Emergency force kill failed for server %s: %s",
                    server.server_id,
                    force_e,
                )

            # Re-raise the original error for the caller to handle
            raise

    def restart_deployment(self, timeout: Optional[float] = None) -> None:
        """Restart the entire deployment.

        Args:
            timeout: Maximum time for restart operation (uses config default if None)
        """
        if timeout is None:
            timeout = self._app_context.config.timeouts.deployment_cluster

        logger.info("Restarting deployment (timeout: %.1fs)", timeout)

        # Preserve current plan
        current_plan = self.state.deployment_plan

        # Shutdown current deployment (allocate half the timeout)
        self.shutdown_deployment(timeout / 2)

        # Restore plan and redeploy
        self.state.deployment_plan = current_plan
        self.deploy_servers(timeout / 2)

    def get_server(self, server_id: ServerId) -> Optional[ArangoServer]:
        """Get server instance by ID."""
        return self.state.servers.get(server_id)

    def get_servers_by_role(self, role: ServerRole) -> List[ArangoServer]:
        """Get all servers with the specified role."""
        return [s for s in self.state.servers.values() if s.role == role]

    def get_all_servers(self) -> Dict[ServerId, ArangoServer]:
        """Get all servers as a dictionary.

        Returns:
            Dictionary mapping server IDs to server instances
        """
        return dict(self.state.servers)

    def get_coordination_endpoints(self) -> List[str]:
        """Get coordination endpoints (coordinators or single server).

        Returns:
            List of coordination endpoints
        """
        from .deployment_plan import ClusterDeploymentPlan

        if not self.state.deployment_plan:
            return []
        if isinstance(self.state.deployment_plan, ClusterDeploymentPlan):
            return self.state.deployment_plan.coordination_endpoints
        return []

    def get_agency_endpoints(self) -> List[str]:
        """Get agency endpoints.

        Returns:
            List of agency endpoints
        """
        from .deployment_plan import ClusterDeploymentPlan

        if not self.state.deployment_plan:
            return []
        if isinstance(self.state.deployment_plan, ClusterDeploymentPlan):
            return self.state.deployment_plan.agency_endpoints
        return []

    def check_deployment_health(self, timeout: Optional[float] = None) -> HealthStatus:
        """Check health of the entire deployment.

        Args:
            timeout: Timeout for health check (uses config default if None)

        Returns:
            Overall deployment health status
        """
        if timeout is None:
            timeout = self._app_context.config.timeouts.health_check_extended

        if not self.state.status.is_deployed:
            return HealthStatus(
                is_healthy=False,
                response_time=0.0,
                error_message="No deployment active",
            )

        # Delegate to HealthMonitor for health checking (authoritative orchestrator dict)
        servers = self._deployment_orchestrator.get_servers()

        health_status = self._health_monitor.check_deployment_health(
            servers, timeout=timeout
        )

        # Update state based on health status
        self.state.status.is_healthy = health_status.is_healthy

        return health_status

    def collect_server_stats(self) -> Dict[ServerId, ServerStats]:
        """Collect statistics from all servers.

        Returns:
            Dictionary mapping server IDs to their stats
        """
        # Delegate to HealthMonitor for stats collection (authoritative orchestrator dict)
        servers = self._deployment_orchestrator.get_servers()

        return self._health_monitor.collect_deployment_stats(servers)

    def is_deployed(self) -> bool:
        """Check if deployment is active."""
        return self.state.status.is_deployed

    def is_healthy(self) -> bool:
        """Check if deployment is healthy."""
        return self.state.status.is_healthy

    def get_server_count(self) -> int:
        """Get total number of servers in deployment."""
        return len(self.state.servers)

    def get_deployment_info(self) -> Dict[str, Any]:
        """Get comprehensive deployment information.

        Returns:
            Dictionary with deployment details
        """
        info = {
            "deployment_id": self.deployment_id,
            "is_deployed": self.state.status.is_deployed,
            "is_healthy": self.state.status.is_healthy,
            "server_count": len(self.state.servers),
            "startup_time": self.state.timing.startup_time,
            "shutdown_time": self.state.timing.shutdown_time,
        }

        if self.state.deployment_plan:
            from .deployment_plan import SingleServerDeploymentPlan

            # Determine deployment mode from plan type
            deployment_mode = (
                "single_server"
                if isinstance(self.state.deployment_plan, SingleServerDeploymentPlan)
                else "cluster"
            )

            info.update(
                {
                    "deployment_mode": deployment_mode,
                    "coordination_endpoints": self.get_coordination_endpoints(),
                    "agency_endpoints": self.get_agency_endpoints(),
                }
            )

        # Add server details
        info["servers"] = {}
        for server_id, server in self.state.servers.items():
            info["servers"][str(server_id)] = {
                "role": server.role.value,
                "endpoint": server.endpoint,
                "is_running": server.is_running(),
                "pid": server.get_pid(),
            }

        return info

    # Private methods

    # Note: Cluster bootstrap methods (_start_cluster, _wait_for_agency_ready, etc.)
    # have been moved to ClusterBootstrapper component.
    # Health check methods (_verify_deployment_health, _collect_server_health_data, etc.)
    # have been moved to HealthMonitor component.
    # These methods are now accessed via delegation in deploy_servers() and check_deployment_health().

    def _release_ports(self) -> None:
        """Release all allocated ports for this deployment."""
        try:
            # Release ports for each server in this deployment
            for server in self.state.servers.values():
                if hasattr(server, "port"):
                    self._app_context.port_allocator.release_port(server.port)
                    logger.debug(
                        "Released port %s for server %s", server.port, server.server_id
                    )
        except (OSError, RuntimeError, ValueError) as e:
            logger.warning("Error releasing ports: %s", e)
