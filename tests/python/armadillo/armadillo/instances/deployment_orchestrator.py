"""High-level deployment orchestration and lifecycle management."""

from typing import Optional
import time
from ..core.types import ServerRole
from ..core.log import Logger
from ..core.errors import (
    ServerError,
    ServerStartupError,
    ServerShutdownError,
    ProcessError,
    ClusterError,
)
from ..utils import print_status
from .deployment_plan import (
    DeploymentPlan,
    SingleServerDeploymentPlan,
    ClusterDeploymentPlan,
)
from .server_registry import ServerRegistry
from .server_factory import ServerFactory
from .cluster_bootstrapper import ClusterBootstrapper
from .health_monitor import HealthMonitor
from .deployment_strategy import (
    DeploymentStrategy,
    SingleServerStrategy,
    ClusterStrategy,
)


class DeploymentOrchestrator:
    """Orchestrates high-level deployment lifecycle operations.

    This class is responsible for:
    - Executing deployments based on a DeploymentPlan
    - Managing deployment lifecycle (start, stop, restart)
    - Coordinating between specialized components
    - Delegating mode-specific logic to deployment strategies
    """

    def __init__(
        self,
        logger: Logger,
        server_factory: ServerFactory,
        server_registry: ServerRegistry,
        cluster_bootstrapper: Optional[ClusterBootstrapper] = None,
        health_monitor: Optional[HealthMonitor] = None,
    ) -> None:
        """Initialize deployment orchestrator.

        Args:
            logger: Logger instance
            server_factory: Factory for creating servers
            server_registry: Registry for server storage/lookup
            cluster_bootstrapper: Optional bootstrapper for cluster deployments
            health_monitor: Optional health monitor for verification
        """
        self._logger = logger
        self._server_factory = server_factory
        self._server_registry = server_registry
        self._cluster_bootstrapper = cluster_bootstrapper
        self._health_monitor = health_monitor
        self._startup_order: list[str] = []

    def _create_strategy(self, plan: DeploymentPlan) -> DeploymentStrategy:
        """Create deployment strategy based on plan type."""
        if isinstance(plan, SingleServerDeploymentPlan):
            return SingleServerStrategy(self._logger)
        elif isinstance(plan, ClusterDeploymentPlan):
            if not self._cluster_bootstrapper:
                raise ServerError(
                    "ClusterBootstrapper required for cluster deployments"
                )
            return ClusterStrategy(self._logger, self._cluster_bootstrapper)
        else:
            raise ServerError(f"Unsupported deployment plan type: {type(plan)}")

    def execute_deployment(self, plan: DeploymentPlan, timeout: float = 300.0) -> None:
        """Execute deployment based on plan using strategy pattern."""
        num_servers = (
            1 if isinstance(plan, SingleServerDeploymentPlan) else len(plan.servers)
        )
        plan_type = (
            "single_server"
            if isinstance(plan, SingleServerDeploymentPlan)
            else "cluster"
        )

        self._logger.info(
            "Executing %s deployment with %d server(s)",
            plan_type,
            num_servers,
        )
        start_time = time.time()

        try:
            strategy = self._create_strategy(plan)

            self._create_servers_from_plan(plan)
            servers = self._server_registry.get_all_servers()

            elapsed = time.time() - start_time
            remaining = max(60.0, timeout - elapsed)
            strategy.start_servers(
                servers, plan, self._startup_order, timeout=remaining
            )

            elapsed = time.time() - start_time
            remaining = max(30.0, timeout - elapsed)
            strategy.verify_readiness(servers, timeout=remaining)

            if self._health_monitor:
                elapsed = time.time() - start_time
                remaining = max(30.0, timeout - elapsed)
                health = self._health_monitor.check_deployment_health(
                    servers, timeout=remaining
                )
                if not health.is_healthy:
                    raise ServerError(
                        f"Deployment health check failed: {health.error_message}"
                    )

            elapsed_total = time.time() - start_time
            self._logger.info(
                "Deployment completed successfully in %.2fs", elapsed_total
            )

        except (ServerStartupError, ProcessError, ClusterError, OSError) as e:
            self._logger.error("Deployment failed: %s", e, exc_info=True)
            raise

    def shutdown_deployment(
        self, shutdown_order: Optional[list[str]] = None, timeout: float = 120.0
    ) -> None:
        """Shutdown all servers in the deployment.

        Args:
            shutdown_order: Optional custom shutdown order (defaults to reverse of startup)
            timeout: Total timeout for shutdown

        Raises:
            ServerError: If shutdown fails critically
        """
        servers = self._server_registry.get_all_servers()
        self._logger.debug(
            "DeploymentOrchestrator.shutdown_deployment called: %d servers registered",
            len(servers),
        )
        if not servers:
            self._logger.debug("No servers to shutdown")
            return

        # Determine shutdown order
        if shutdown_order is None:
            shutdown_order = list(reversed(self._startup_order))

        # Print shutdown message with newline to separate from test output
        # Distinguish between single server and cluster shutdown
        if len(servers) == 1:
            print_status("\nShutting down server")
        else:
            print_status(f"\nShutting down cluster with {len(servers)} servers")

        # Separate agents from other servers for proper cluster shutdown
        agents = []
        non_agents = []
        for server_id in shutdown_order:
            if server_id in servers:
                server = servers[server_id]
                if server.role == ServerRole.AGENT:
                    agents.append(server)
                else:
                    non_agents.append(server)

        # Shutdown non-agents first, then agents (cluster best practice)
        all_servers_to_stop = non_agents + agents

        if all_servers_to_stop:
            order_names = [s.server_id for s in all_servers_to_stop]
            self._logger.info("Shutdown order: %s", " -> ".join(order_names))

        failed_shutdowns = []
        per_server_timeout = timeout / max(1, len(all_servers_to_stop))

        for server in all_servers_to_stop:
            try:
                self._logger.info("Shutting down %s", server.server_id)
                server.stop(timeout=per_server_timeout)
                self._logger.info("Server %s stopped", server.server_id)
            except (ServerShutdownError, ProcessError, OSError) as e:
                # Continue shutting down other servers even if one fails
                self._logger.error("Failed to stop %s: %s", server.server_id, e)
                failed_shutdowns.append(server.server_id)

        # Clear registry after shutdown
        self._server_registry.clear()
        self._startup_order.clear()

        if failed_shutdowns:
            self._logger.warning(
                "Some servers failed to shutdown cleanly: %s", failed_shutdowns
            )

    def restart_deployment(self, timeout: float = 300.0) -> None:
        """Restart all servers in the deployment.

        Args:
            timeout: Total timeout for restart
        """
        self._logger.info("Restarting deployment")

        # Shutdown first
        shutdown_timeout = timeout * 0.3
        self.shutdown_deployment(timeout=shutdown_timeout)

        # We can't restart without a plan - this would need to be stored
        raise NotImplementedError(
            "Restart requires storing the original deployment plan. "
            "Use InstanceManager.restart_deployment() instead."
        )

    def _create_servers_from_plan(self, plan: DeploymentPlan) -> None:
        """Create and register server instances from plan."""
        if isinstance(plan, SingleServerDeploymentPlan):
            server_configs = [plan.server]
            num_servers = 1
        else:
            server_configs = plan.servers
            num_servers = len(server_configs)

        self._logger.info("Creating %d server instance(s) from plan", num_servers)

        servers = self._server_factory.create_server_instances(server_configs)

        for server_id, server in servers.items():
            self._logger.debug(
                "Registering server: %s (role: %s)", server_id, server.role.value
            )
            self._server_registry.register_server(server_id, server)

        self._logger.info("All server instances created and registered")

    def get_startup_order(self) -> list[str]:
        """Get the order in which servers were started.

        Returns:
            List of server IDs in startup order
        """
        return list(self._startup_order)
