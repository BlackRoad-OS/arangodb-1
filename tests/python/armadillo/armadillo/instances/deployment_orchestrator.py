"""High-level deployment orchestration and lifecycle management."""

from typing import Optional, Dict, Union
import time
from concurrent.futures import ThreadPoolExecutor
from ..core.types import TimeoutConfig
from ..core.log import Logger
from ..core.value_objects import ServerId
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
from .server import ArangoServer
from .server_factory import ServerFactory
from .deployment_executor import (
    SingleServerExecutor,
    ClusterExecutor,
)


class DeploymentOrchestrator:
    """Orchestrates high-level deployment lifecycle operations.

    This class is responsible for:
    - Executing deployments based on a DeploymentPlan
    - Managing deployment lifecycle (start, stop, restart)
    - Coordinating between specialized components
    - Delegating mode-specific logic to deployment executors
    """

    def __init__(
        self,
        logger: Logger,
        server_factory: ServerFactory,
        executor: ThreadPoolExecutor,
        timeout_config: Optional[TimeoutConfig] = None,
    ) -> None:
        """Initialize deployment orchestrator.

        Args:
            logger: Logger instance
            server_factory: Factory for creating servers
            executor: Thread pool executor for parallel operations
            timeout_config: Optional timeout configuration (uses defaults if not provided)
        """
        self._logger = logger
        self._server_factory = server_factory
        self._executor = executor
        self._timeouts = timeout_config or TimeoutConfig()
        self._servers: Dict[ServerId, ArangoServer] = {}
        self._current_executor: Optional[object] = (
            None  # SingleServerExecutor or ClusterExecutor
        )

    def _create_executor(
        self, plan: DeploymentPlan
    ) -> Union[SingleServerExecutor, ClusterExecutor]:
        """Create lifecycle-owning deployment executor based on plan type."""
        if isinstance(plan, SingleServerDeploymentPlan):
            return SingleServerExecutor(
                self._logger, self._server_factory, self._timeouts
            )
        if isinstance(plan, ClusterDeploymentPlan):
            return ClusterExecutor(
                self._logger, self._server_factory, self._executor, self._timeouts
            )
        raise ServerError(f"Unsupported deployment plan type: {type(plan)}")

    def execute_deployment(
        self, plan: DeploymentPlan, timeout: Optional[float] = None
    ) -> None:
        """Execute deployment based on plan using executor pattern."""
        # Use config defaults if timeout not specified
        if timeout is None:
            timeout = (
                self._timeouts.deployment_single
                if isinstance(plan, SingleServerDeploymentPlan)
                else self._timeouts.deployment_cluster
            )

        num_servers = (
            1 if isinstance(plan, SingleServerDeploymentPlan) else len(plan.servers)
        )
        plan_type = (
            "single_server"
            if isinstance(plan, SingleServerDeploymentPlan)
            else "cluster"
        )

        self._logger.info(
            "Executing %s deployment with %d server(s) (timeout: %.1fs)",
            plan_type,
            num_servers,
            timeout,
        )
        start_time = time.time()

        try:
            # Executor owns full lifecycle (create + start + verify)
            executor = self._create_executor(plan)
            self._servers = executor.deploy(plan, timeout=timeout)
            self._current_executor = executor

            elapsed_total = time.time() - start_time
            self._logger.info(
                "Deployment completed successfully in %.2fs", elapsed_total
            )

        except (ServerStartupError, ProcessError, ClusterError, OSError) as e:
            self._logger.error("Deployment failed: %s", e, exc_info=True)
            raise

    def shutdown_deployment(
        self,
        timeout: Optional[float] = None,
    ) -> None:
        """Shutdown all servers in the deployment using executor.

        Args:
            timeout: Maximum time to wait for shutdown (uses config default if None)

        Raises:
            ServerError: If shutdown fails critically
        """
        if not self._servers or not self._current_executor:
            self._logger.debug("No deployment to shutdown")
            return

        if timeout is None:
            # Calculate timeout based on number of servers
            # Allow per-server timeout + 20% buffer for coordination overhead
            num_servers = len(self._servers)
            timeout = self._timeouts.server_shutdown * max(1, num_servers) * 1.2

        self._logger.info(
            "Shutting down %d server(s) with %.1fs timeout",
            len(self._servers),
            timeout,
        )

        # Print shutdown message with newline to separate from test output
        if len(self._servers) == 1:
            print_status("\nShutting down server")
        else:
            print_status(f"\nShutting down cluster with {len(self._servers)} servers")

        # Delegate to executor (it knows the correct shutdown order)
        self._current_executor.shutdown(self._servers, timeout)

        # Clear storage after shutdown
        self._servers.clear()
        self._current_executor = None

    def restart_deployment(self, timeout: Optional[float] = None) -> None:
        """Restart all servers in the deployment.

        Args:
            timeout: Maximum time for restart operation (uses config default if None)
        """
        if timeout is None:
            timeout = self._timeouts.deployment_cluster  # Conservative default

        self._logger.info("Restarting deployment (timeout: %.1fs)", timeout)

        # Shutdown first
        shutdown_timeout = timeout * 0.3
        self.shutdown_deployment(timeout=shutdown_timeout)

        # We can't restart without a plan - this would need to be stored
        raise NotImplementedError(
            "Restart requires storing the original deployment plan. "
            "Use InstanceManager.restart_deployment() instead."
        )

    def get_servers(self) -> Dict[ServerId, ArangoServer]:
        """Get current servers dict."""
        return self._servers

    def get_server(self, server_id: ServerId) -> Optional[ArangoServer]:
        """Get a single server by ID."""
        servers = self.get_servers()
        return servers.get(server_id)
