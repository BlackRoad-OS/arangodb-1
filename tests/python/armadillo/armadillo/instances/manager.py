"""Instance Manager for multi-server orchestration and lifecycle management."""

from typing import Dict, List, Optional, Any
import time
from concurrent.futures import ThreadPoolExecutor
import threading
from dataclasses import dataclass, field

from ..core.types import (
    DeploymentMode,
    ServerRole,
    ClusterConfig,
    HealthStatus,
    ServerStats,
)
from ..core.errors import (
    ServerError,
    ServerStartupError,
    ServerShutdownError,
    ProcessError,
)
from ..core.log import get_logger, Logger, log_server_event
from ..core.time import timeout_scope, clamp_timeout
from ..core.process import stop_supervised_process
from .server import ArangoServer
from .deployment_planner import DeploymentPlanner, StandardDeploymentPlanner
from .server_factory import ServerFactory, StandardServerFactory
from ..core.config import get_config, ConfigProvider
from ..utils.ports import get_port_manager, PortAllocator
from ..utils.auth import get_auth_provider, AuthProvider
from .deployment_plan import DeploymentPlan
from .server_registry import ServerRegistry
from .health_monitor import HealthMonitor
from .cluster_bootstrapper import ClusterBootstrapper
from .deployment_orchestrator import DeploymentOrchestrator

logger = get_logger(__name__)


@dataclass
class ManagerDependencies:
    """Injectable dependencies for InstanceManager."""

    config: ConfigProvider
    logger: Logger
    port_manager: PortAllocator
    auth_provider: "AuthProvider"
    deployment_planner: DeploymentPlanner
    server_factory: ServerFactory

    @classmethod
    def create_defaults(
        cls,
        deployment_id: str,
        config: Optional[ConfigProvider] = None,
        custom_logger: Optional[Logger] = None,
        port_allocator: Optional[PortAllocator] = None,
    ) -> "ManagerDependencies":
        """Create dependencies with deployment-specific defaults."""
        final_config = config or get_config()

        # Create deployment-specific logger with context if not provided
        if custom_logger:
            final_logger = custom_logger
        else:
            base_logger = get_logger(f"{__name__}.{deployment_id}")
            final_logger = base_logger

        final_port_manager = port_allocator or get_port_manager()

        return cls(
            config=final_config,
            logger=final_logger,
            port_manager=final_port_manager,
            auth_provider=get_auth_provider(),
            deployment_planner=StandardDeploymentPlanner(
                port_allocator=final_port_manager,
                logger=final_logger,
                config_provider=final_config,
            ),
            server_factory=StandardServerFactory(
                config_provider=final_config,
                logger=final_logger,
                port_allocator=final_port_manager,
            ),
        )


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

    servers: Dict[str, ArangoServer] = field(default_factory=dict)
    deployment_plan: Optional[DeploymentPlan] = None
    startup_order: List[str] = field(default_factory=list)
    shutdown_order: List[str] = field(default_factory=list)
    status: DeploymentStatus = field(default_factory=DeploymentStatus)
    timing: DeploymentTiming = field(default_factory=DeploymentTiming)


@dataclass
class ThreadingResources:
    """Threading resources for parallel operations."""

    executor: ThreadPoolExecutor
    lock: threading.RLock

    @classmethod
    def create_for_deployment(cls, deployment_id: str) -> "ThreadingResources":
        """Create threading resources for a deployment."""
        return cls(
            executor=ThreadPoolExecutor(
                max_workers=10, thread_name_prefix=f"InstanceMgr-{deployment_id}"
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
        deployment_id: str,
        *,
        dependencies: Optional[ManagerDependencies] = None,
        config_provider=None,
        logger=None,
        port_allocator=None,
        deployment_planner=None,
        server_factory=None,
    ) -> None:
        """Initialize instance manager with composition-based design.

        Args:
            deployment_id: Unique identifier for this deployment
            dependencies: Composed dependencies object (recommended)
            config_provider: Optional config provider (alternative to dependencies)
            logger: Optional logger (alternative to dependencies)
            port_allocator: Optional port allocator (alternative to dependencies)
            deployment_planner: Optional deployment planner (alternative to dependencies)
            server_factory: Optional server factory (alternative to dependencies)
        """
        self.deployment_id = deployment_id

        # Initialize dependencies - handle both composed and individual parameters
        if dependencies is not None:
            self._deps = dependencies
        elif any(
            [
                config_provider,
                logger,
                port_allocator,
                deployment_planner,
                server_factory,
            ]
        ):
            # Individual parameters provided - compose them
            self._deps = ManagerDependencies.create_defaults(
                deployment_id=deployment_id,
                config=config_provider,
                custom_logger=logger,
                port_allocator=port_allocator,
            )
            # Override with explicitly provided parameters
            if deployment_planner is not None:
                self._deps.deployment_planner = deployment_planner
            if server_factory is not None:
                self._deps.server_factory = server_factory
        else:
            # No parameters provided, use all defaults
            self._deps = ManagerDependencies.create_defaults(
                deployment_id=deployment_id
            )

        # Initialize runtime state and threading resources
        self.state = DeploymentState()
        self._threading = ThreadingResources.create_for_deployment(deployment_id)

        # Initialize new architectural components
        self._server_registry = ServerRegistry()
        self._health_monitor = HealthMonitor(self._deps.logger)
        self._cluster_bootstrapper = ClusterBootstrapper(
            self._deps.logger, self._threading.executor
        )
        self._deployment_orchestrator = DeploymentOrchestrator(
            logger=self._deps.logger,
            server_factory=self._deps.server_factory,
            server_registry=self._server_registry,
            cluster_bootstrapper=self._cluster_bootstrapper,
            health_monitor=self._health_monitor,
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
            cluster_config = self._deps.config.cluster

        return self._deps.deployment_planner.create_deployment_plan(
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
            logger.info("Starting deployment of %s servers", len(plan.servers))
            self.state.timing.startup_time = time.time()

            try:
                # Delegate to DeploymentOrchestrator for the actual deployment
                self._deployment_orchestrator.execute_deployment(plan, timeout=timeout)

                # Sync state from registry to maintain backward compatibility
                self._sync_state_from_registry()

                # Mark deployment as active
                self.state.status.is_deployed = True
                self.state.status.is_healthy = True

                deployment_time = time.time() - self.state.timing.startup_time
                logger.info(
                    "Deployment completed successfully in %.2fs", deployment_time
                )

            except Exception as e:
                logger.error("Deployment failed: %s", e)
                # Try to cleanup partial deployment
                try:
                    self.shutdown_deployment()
                except (OSError, ProcessLookupError, RuntimeError, AttributeError):
                    pass
                raise ServerStartupError(f"Failed to deploy servers: {e}") from e

    def _sync_state_from_registry(self) -> None:
        """Synchronize state from ServerRegistry to maintain backward compatibility.

        This allows existing code that accesses self.state.servers and self.state.startup_order
        to continue working while the actual deployment is managed by new components.
        """
        # Sync servers from registry
        self.state.servers = self._server_registry.get_all_servers()

        # Sync startup order from orchestrator
        self.state.startup_order = self._deployment_orchestrator.get_startup_order()

    def shutdown_deployment(self, timeout: float = 120.0) -> None:
        """Shutdown all deployed servers in correct order.

        For clusters, agents are shut down LAST after all other servers.

        Args:
            timeout: Maximum time to wait for shutdown
        """
        if not self.state.status.is_deployed:
            logger.debug("No deployment to shutdown")
            return

        timeout = clamp_timeout(timeout, "shutdown")
        self.state.timing.shutdown_time = time.time()

        with timeout_scope(timeout, f"shutdown_deployment_{self.deployment_id}"):
            try:
                # Delegate to DeploymentOrchestrator for shutdown
                shutdown_order = list(reversed(self.state.startup_order))
                self._deployment_orchestrator.shutdown_deployment(
                    shutdown_order=shutdown_order, timeout=timeout
                )
            except Exception as e:
                logger.error("Shutdown via orchestrator failed: %s", e)
                # Fallback to direct shutdown if orchestrator fails
                self._direct_shutdown_deployment(timeout)

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

    def _direct_shutdown_deployment(self, _timeout: float) -> None:
        """Direct shutdown implementation as fallback when orchestrator fails.

        Args:
            _timeout: Maximum time to wait for shutdown (currently unused; using fixed timeouts)
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
                    self._shutdown_server(server, timeout=30.0)
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
                    self._shutdown_server(server, timeout=90.0)
                except (OSError, ServerShutdownError) as e:
                    logger.error("Failed to shutdown agent %s: %s", server.server_id, e)
                    failed_shutdowns.append(server.server_id)

        if failed_shutdowns:
            logger.warning(
                "Some servers failed to shutdown cleanly: %s", failed_shutdowns
            )

    def _shutdown_server(self, server: "ArangoServer", timeout: float = 30.0) -> None:
        """Shutdown a single server with bulletproof termination and polling.

        Combines graceful shutdown with emergency force kill fallback and
        polling to ensure the server actually stops before continuing.

        Args:
            server: The server instance to shutdown
            timeout: Maximum time to wait for shutdown
        """
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
            poll_interval = 1.0
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

        except Exception as e:
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
                    stop_supervised_process(
                        server.server_id, graceful=False, timeout=5.0
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

    def restart_deployment(self, timeout: float = 300.0) -> None:
        """Restart the entire deployment.

        Args:
            timeout: Maximum time for restart operation
        """
        logger.info("Restarting deployment")

        # Preserve current plan
        current_plan = self.state.deployment_plan

        # Shutdown current deployment
        self.shutdown_deployment(timeout / 2)

        # Restore plan and redeploy
        self.state.deployment_plan = current_plan
        self.deploy_servers(timeout / 2)

    def get_server(self, server_id: str) -> Optional[ArangoServer]:
        """Get server instance by ID.

        Args:
            server_id: Server identifier

        Returns:
            Server instance or None if not found
        """
        # Delegate to ServerRegistry for better performance and consistency
        return self._server_registry.get_server(server_id) or self.state.servers.get(
            server_id
        )

    def get_servers_by_role(self, role: ServerRole) -> List[ArangoServer]:
        """Get all servers with the specified role.

        Args:
            role: Server role to filter by

        Returns:
            List of servers with the specified role
        """
        # Delegate to ServerRegistry for better performance
        return self._server_registry.get_servers_by_role(role)

    def get_all_servers(self) -> Dict[str, ArangoServer]:
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
        if not self.state.deployment_plan:
            return []
        return self.state.deployment_plan.coordination_endpoints

    def get_agency_endpoints(self) -> List[str]:
        """Get agency endpoints.

        Returns:
            List of agency endpoints
        """
        if not self.state.deployment_plan:
            return []
        return self.state.deployment_plan.agency_endpoints

    def check_deployment_health(self, timeout: float = 30.0) -> HealthStatus:
        """Check health of the entire deployment.

        Args:
            timeout: Timeout for health check

        Returns:
            Overall deployment health status
        """
        if not self.state.status.is_deployed:
            return HealthStatus(
                is_healthy=False,
                response_time=0.0,
                error_message="No deployment active",
            )

        # Delegate to HealthMonitor for health checking
        servers = self._server_registry.get_all_servers()
        if not servers:
            servers = self.state.servers  # Fallback to state if registry empty

        health_status = self._health_monitor.check_deployment_health(
            servers, timeout=timeout
        )

        # Update state based on health status
        self.state.status.is_healthy = health_status.is_healthy

        return health_status

    def collect_server_stats(self) -> Dict[str, ServerStats]:
        """Collect statistics from all servers.

        Returns:
            Dictionary mapping server IDs to their stats
        """
        # Delegate to HealthMonitor for stats collection
        servers = self._server_registry.get_all_servers()
        if not servers:
            servers = self.state.servers  # Fallback to state if registry empty

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
            info.update(
                {
                    "deployment_mode": self.state.deployment_plan.deployment_mode.value,
                    "coordination_endpoints": self.state.deployment_plan.coordination_endpoints,
                    "agency_endpoints": self.state.deployment_plan.agency_endpoints,
                }
            )

        # Add server details
        info["servers"] = {}
        for server_id, server in self.state.servers.items():
            info["servers"][server_id] = {
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
                    self._deps.port_manager.release_port(server.port)
                    logger.debug(
                        "Released port %s for server %s", server.port, server.server_id
                    )
        except (OSError, RuntimeError, ValueError) as e:
            logger.warning("Error releasing ports: %s", e)


# Global instance manager registry
_instance_managers: Dict[str, InstanceManager] = {}
_manager_lock = threading.Lock()


def get_instance_manager(deployment_id: str) -> InstanceManager:
    """Get or create instance manager for deployment.

    Args:
        deployment_id: Unique deployment identifier

    Returns:
        Instance manager instance
    """
    with _manager_lock:
        if deployment_id not in _instance_managers:
            _instance_managers[deployment_id] = InstanceManager(deployment_id)
        return _instance_managers[deployment_id]


def cleanup_instance_managers() -> None:
    """Cleanup all instance managers."""
    with _manager_lock:
        for manager in _instance_managers.values():
            try:
                if manager.is_deployed():
                    manager.shutdown_deployment()
            except (ServerError, ServerShutdownError, OSError) as e:
                logger.error("Error during manager cleanup: %s", e)

        _instance_managers.clear()
