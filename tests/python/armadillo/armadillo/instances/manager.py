"""Instance Manager for multi-server orchestration and lifecycle management."""

from typing import Dict, List, Optional, Any, Type
from types import TracebackType
import time
from concurrent.futures import ThreadPoolExecutor
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
from .server import ArangoServer
from .deployment_plan import DeploymentPlan, SingleServerDeploymentPlan
from .deployment import Deployment, SingleServerDeployment, ClusterDeployment
from .health_monitor import HealthMonitor
from .deployment_orchestrator import DeploymentOrchestrator

logger = get_logger(__name__)


@dataclass
class ThreadingResources:
    """Threading resources for parallel operations."""

    executor: ThreadPoolExecutor

    @classmethod
    def create_for_deployment(
        cls, deployment_id: DeploymentId, max_workers: int
    ) -> "ThreadingResources":
        """Create threading resources for a deployment.

        Args:
            deployment_id: Deployment identifier for thread naming
            max_workers: Maximum number of worker threads
        """
        return cls(
            executor=ThreadPoolExecutor(
                max_workers=max_workers,
                thread_name_prefix=f"InstanceMgr-{deployment_id}",
            ),
        )


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

        # Initialize deployment state and threading resources
        self._deployment: Optional[Deployment] = None
        self._threading = ThreadingResources.create_for_deployment(
            deployment_id,
            max_workers=self._app_context.config.infrastructure.manager_max_workers,
        )

        # Initialize architectural components
        self._health_monitor = HealthMonitor(
            self._app_context.logger, self._app_context.config.timeouts
        )
        self._deployment_orchestrator = DeploymentOrchestrator(
            logger=self._app_context.logger,
            server_factory=self._app_context.server_factory,
            executor=self._threading.executor,
            timeout_config=self._app_context.config.timeouts,
        )

    def __enter__(self) -> "InstanceManager":
        """Context manager entry."""
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        """Context manager exit."""
        try:
            if self._deployment and self._deployment.is_deployed():
                self.shutdown_deployment()
        finally:
            self._threading.executor.shutdown(wait=True)

    def create_single_server_plan(self) -> "SingleServerDeploymentPlan":
        """Create deployment plan for single server.

        This is a pure function that creates and returns a plan without side effects.

        Returns:
            Single server deployment plan
        """
        # Convert DeploymentId to ServerId for single server plan
        # For single server deployments, deployment_id is used as server_id
        server_id = ServerId(str(self.deployment_id))
        return self._app_context.deployment_planner.create_single_server_plan(server_id)

    def create_cluster_deployment_plan(
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
        if self._deployment and self._deployment.is_deployed():
            raise ServerError("Deployment already active")

        timeout = clamp_timeout(timeout, "deployment")

        with timeout_scope(timeout, f"deploy_servers_{self.deployment_id}"):
            from .deployment_plan import SingleServerDeploymentPlan

            # Determine number of servers based on plan type
            num_servers = (
                1 if isinstance(plan, SingleServerDeploymentPlan) else len(plan.servers)
            )
            logger.info("Starting deployment of %s servers", num_servers)

            try:
                # Delegate to DeploymentOrchestrator for the actual deployment
                # InstanceManager is the single source of truth for deployment state
                self._deployment = self._deployment_orchestrator.execute_deployment(
                    plan, timeout=timeout
                )
                if self._deployment:
                    startup_time = time.time()
                    self._deployment.mark_deployed(startup_time)

                    deployment_time = time.time() - startup_time
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

    def shutdown_deployment(self, timeout: Optional[float] = None) -> None:
        """Shutdown all deployed servers in correct order.

        For clusters, agents are shut down LAST after all other servers.

        Args:
            timeout: Maximum time to wait for shutdown (uses config default if None)
        """
        if not self._deployment or not self._deployment.is_deployed():
            logger.debug("No deployment to shutdown")
            return

        # Use config default if not specified (scales with server count)
        if timeout is None:
            num_servers = self._deployment.get_server_count()
            timeout = (
                self._app_context.config.timeouts.server_shutdown
                * max(1, num_servers)
                * 1.2
            )

        timeout = clamp_timeout(timeout, "shutdown")
        shutdown_start_time = time.time()

        logger.debug(
            "InstanceManager.shutdown_deployment: deployment_id=%s, servers=%d",
            self.deployment_id,
            self._deployment.get_server_count(),
        )

        with timeout_scope(timeout, f"shutdown_deployment_{self.deployment_id}"):
            # Delegate to DeploymentOrchestrator for shutdown
            # Pass deployment explicitly - InstanceManager is single source of truth
            logger.debug("Calling DeploymentOrchestrator.shutdown_deployment")
            self._deployment_orchestrator.shutdown_deployment(
                self._deployment, timeout=timeout
            )
            logger.debug(
                "DeploymentOrchestrator.shutdown_deployment completed successfully"
            )

            # Release allocated ports
            self._release_ports()

            # Mark deployment as shut down
            shutdown_time = time.time()
            self._deployment.mark_shutdown(shutdown_time)

            shutdown_duration = shutdown_time - shutdown_start_time
            logger.info("Deployment shutdown completed in %.2fs", shutdown_duration)

    def get_server_health(self) -> ServerHealthInfo:
        """Collect server health information after deployment shutdown.

        Returns health data including:
        - Exit codes from intentional shutdown (non-zero may indicate sanitizer issues)
        - Crash information from unexpected termination

        Should be called after shutdown_deployment() to capture exit codes.

        Returns:
            ServerHealthInfo with crashes and exit codes (filtered to this deployment's servers)
        """
        # Get all health data from the injected process supervisor
        all_exit_codes = self._app_context.process_supervisor.get_exit_codes()
        all_crashes = self._app_context.process_supervisor.get_crash_state()

        # Get the set of server IDs that belong to this deployment
        servers = self._deployment.get_servers() if self._deployment else {}
        deployment_server_ids = set(servers.keys())

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

    def get_server(self, server_id: ServerId) -> Optional[ArangoServer]:
        """Get server instance by ID."""
        return self._deployment.get_server(server_id) if self._deployment else None

    def get_servers_by_role(self, role: ServerRole) -> List[ArangoServer]:
        """Get all servers with the specified role."""
        return self._deployment.get_servers_by_role(role) if self._deployment else []

    def get_all_servers(self) -> Dict[ServerId, ArangoServer]:
        """Get all servers as a dictionary.

        Returns:
            Dictionary mapping server IDs to server instances
        """
        return self._deployment.get_servers() if self._deployment else {}

    def get_coordination_endpoints(self) -> List[str]:
        """Get coordination endpoints (coordinators or single server).

        Returns:
            List of coordination endpoints
        """
        if not self._deployment:
            return []
        return self._deployment.get_coordination_endpoints()

    def get_agency_endpoints(self) -> List[str]:
        """Get agency endpoints.

        Returns:
            List of agency endpoints
        """
        if not self._deployment:
            return []
        return self._deployment.get_agency_endpoints()

    def check_deployment_health(self, timeout: Optional[float] = None) -> HealthStatus:
        """Check health of the entire deployment.

        Args:
            timeout: Timeout for health check (uses config default if None)

        Returns:
            Overall deployment health status
        """
        if timeout is None:
            timeout = self._app_context.config.timeouts.health_check_extended

        if not self._deployment or not self._deployment.is_deployed():
            return HealthStatus(
                is_healthy=False,
                response_time=0.0,
                error_message="No deployment active",
            )

        # Delegate to HealthMonitor for health checking
        servers = self._deployment.get_servers()

        health_status = self._health_monitor.check_deployment_health(
            servers, timeout=timeout
        )

        # Update state based on health status
        self._deployment.mark_healthy(health_status.is_healthy)

        return health_status

    def collect_server_stats(self) -> Dict[ServerId, ServerStats]:
        """Collect statistics from all servers.

        Returns:
            Dictionary mapping server IDs to their stats
        """
        # Delegate to HealthMonitor for stats collection
        servers = self._deployment.get_servers() if self._deployment else {}

        return self._health_monitor.collect_deployment_stats(servers)

    def is_deployed(self) -> bool:
        """Check if deployment is active."""
        return self._deployment is not None and self._deployment.is_deployed()

    def is_healthy(self) -> bool:
        """Check if deployment is healthy."""
        return self._deployment is not None and self._deployment.is_healthy()

    def get_server_count(self) -> int:
        """Get total number of servers in deployment."""
        return self._deployment.get_server_count() if self._deployment else 0

    def get_deployment_info(self) -> Dict[str, Any]:
        """Get comprehensive deployment information.

        Returns:
            Dictionary with deployment details
        """
        timing = self._deployment.get_timing() if self._deployment else None

        info = {
            "deployment_id": self.deployment_id,
            "is_deployed": (
                self._deployment.is_deployed() if self._deployment else False
            ),
            "is_healthy": self._deployment.is_healthy() if self._deployment else False,
            "server_count": (
                self._deployment.get_server_count() if self._deployment else 0
            ),
            "startup_time": timing.startup_time if timing else None,
            "shutdown_time": timing.shutdown_time if timing else None,
        }

        if self._deployment:
            info.update(
                {
                    "deployment_mode": self._deployment.get_deployment_mode(),
                    "coordination_endpoints": self.get_coordination_endpoints(),
                    "agency_endpoints": self.get_agency_endpoints(),
                }
            )

        # Add server details using proper interface
        servers_dict: Dict[str, Any] = {}
        servers = self._deployment.get_servers() if self._deployment else {}
        for server_id, server in servers.items():
            server_info = server.get_info()
            server_context = server.get_context()
            servers_dict[str(server_id)] = {
                "role": server_info.role.value,
                "endpoint": server_info.endpoint,
                "is_running": server.is_running(),
                "pid": server_context.pid,
            }
        info["servers"] = servers_dict

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
            servers = self._deployment.get_servers() if self._deployment else {}
            for server in servers.values():
                port = server.get_port()
                self._app_context.port_allocator.release_port(port)
                logger.debug("Released port %s for server %s", port, server.server_id)
        except (OSError, RuntimeError, ValueError) as e:
            logger.warning("Error releasing ports: %s", e)
