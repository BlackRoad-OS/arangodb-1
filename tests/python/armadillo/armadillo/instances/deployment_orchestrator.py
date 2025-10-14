"""High-level deployment orchestration and lifecycle management."""

from typing import Optional
import time
from ..core.types import DeploymentMode, ServerRole
from ..core.log import Logger
from ..core.errors import ServerError, ClusterError
from ..utils import print_status
from .deployment_plan import DeploymentPlan
from .server_registry import ServerRegistry
from .server_factory import ServerFactory
from .cluster_bootstrapper import ClusterBootstrapper
from .health_monitor import HealthMonitor


class DeploymentOrchestrator:
    """Orchestrates high-level deployment lifecycle operations.

    This class is responsible for:
    - Executing deployments based on a DeploymentPlan
    - Managing deployment lifecycle (start, stop, restart)
    - Coordinating between specialized components
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

    def execute_deployment(self, plan: DeploymentPlan, timeout: float = 300.0) -> None:
        """Execute a deployment based on the provided plan.

        This is the key method that actually USES the DeploymentPlan to drive
        the deployment process.

        Args:
            plan: DeploymentPlan to execute
            timeout: Total timeout for deployment

        Raises:
            ServerError: If deployment fails
        """
        self._logger.info(
            "Executing %s deployment with %d server(s)",
            plan.deployment_mode.value,
            len(plan.servers),
        )
        start_time = time.time()

        try:
            # 1. Create server instances from plan
            self._create_servers_from_plan(plan)

            # 2. Start servers based on deployment mode
            elapsed = time.time() - start_time
            remaining = max(60.0, timeout - elapsed)

            if plan.deployment_mode == DeploymentMode.SINGLE_SERVER:
                self._start_single_server(remaining)
            elif plan.deployment_mode == DeploymentMode.CLUSTER:
                self._start_cluster(remaining)
            else:
                raise ServerError(
                    f"Unsupported deployment mode: {plan.deployment_mode}"
                )

            # 3. Optional health verification
            if self._health_monitor:
                elapsed = time.time() - start_time
                remaining = max(30.0, timeout - elapsed)
                servers = self._server_registry.get_all_servers()
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

        except Exception as e:
            self._logger.error("Deployment failed: %s", e)
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
            except Exception as e:
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
        """Create server instances from deployment plan.

        Args:
            plan: DeploymentPlan to create servers from
        """
        self._logger.info("Creating %d server instance(s) from plan", len(plan.servers))

        # Delegate to ServerFactory to create all servers
        # The factory generates server IDs based on role and index
        servers = self._server_factory.create_server_instances(plan.servers)

        # Register all created servers
        for server_id, server in servers.items():
            self._logger.debug(
                "Registering server: %s (role: %s)", server_id, server.role.value
            )
            self._server_registry.register_server(server_id, server)

        self._logger.info("All server instances created and registered")

    def _start_single_server(self, timeout: float) -> None:
        """Start a single server deployment.

        Args:
            timeout: Timeout for startup
        """
        servers = self._server_registry.get_all_servers()
        if len(servers) != 1:
            raise ServerError(f"Expected 1 server for single mode, got {len(servers)}")

        server_id, server = next(iter(servers.items()))
        self._logger.info("Starting single server: %s", server_id)

        server.start(timeout=timeout)
        self._startup_order.append(server_id)

        self._logger.info("Single server %s started successfully", server_id)

    def _start_cluster(self, timeout: float) -> None:
        """Start a cluster deployment.

        Args:
            timeout: Timeout for startup

        Raises:
            ClusterError: If cluster bootstrapping fails
        """
        if not self._cluster_bootstrapper:
            raise ClusterError("ClusterBootstrapper required for cluster deployments")

        servers = self._server_registry.get_all_servers()

        # Count servers by role
        agents = sum(1 for s in servers.values() if s.role == ServerRole.AGENT)
        dbservers = sum(1 for s in servers.values() if s.role == ServerRole.DBSERVER)
        coordinators = sum(
            1 for s in servers.values() if s.role == ServerRole.COORDINATOR
        )

        print_status(
            f"Starting cluster with {agents} agents, {dbservers} dbservers, {coordinators} coordinators"
        )

        # Delegate to cluster bootstrapper
        self._cluster_bootstrapper.bootstrap_cluster(
            servers, self._startup_order, timeout=timeout
        )

    def get_startup_order(self) -> list[str]:
        """Get the order in which servers were started.

        Returns:
            List of server IDs in startup order
        """
        return list(self._startup_order)
