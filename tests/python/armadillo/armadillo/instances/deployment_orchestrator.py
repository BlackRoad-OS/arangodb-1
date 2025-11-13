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
from .deployment import Deployment, SingleServerDeployment
from .server import ArangoServer
from .server_factory import ServerFactory
from .deployment_executor import (
    SingleServerExecutor,
    ClusterExecutor,
)
from .deployment_executor_factory import DeploymentExecutorFactory


class DeploymentOrchestrator:
    """Orchestrates high-level deployment lifecycle operations.

    This class is responsible for:
    - Executing deployments based on a DeploymentPlan
    - Managing deployment lifecycle (start, stop)
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
        self._deployment: Optional[Deployment] = None
        self._current_executor: Optional[object] = (
            None  # SingleServerExecutor or ClusterExecutor
        )
        self._executor_factory = DeploymentExecutorFactory(
            logger=logger,
            server_factory=server_factory,
            thread_executor=executor,
            timeout_config=self._timeouts,
        )

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
            executor = self._executor_factory.create_executor(plan)
            deployment = executor.deploy(plan, timeout=timeout)
            self._deployment = deployment
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
        if not self._deployment or not self._current_executor:
            self._logger.debug("No deployment to shutdown")
            return

        if timeout is None:
            # Calculate timeout based on number of servers
            # Allow per-server timeout + 20% buffer for coordination overhead
            num_servers = self._deployment.get_server_count()
            timeout = self._timeouts.server_shutdown * max(1, num_servers) * 1.2
        else:
            num_servers = self._deployment.get_server_count()

        self._logger.info(
            "Shutting down %d server(s) with %.1fs timeout",
            num_servers,
            timeout,
        )

        # Print shutdown message with newline to separate from test output
        if isinstance(self._deployment, SingleServerDeployment):
            print_status("\nShutting down server")
        else:
            print_status(
                f"\nShutting down cluster with {self._deployment.get_server_count()} servers"
            )

        # Delegate to executor (it knows the correct shutdown order)
        self._current_executor.shutdown(self._deployment, timeout)

        # Clear storage after shutdown
        self._deployment = None
        self._current_executor = None

    def get_servers(self) -> Dict[ServerId, ArangoServer]:
        """Get current servers dict."""
        return self._deployment.get_servers() if self._deployment else {}

    def get_server(self, server_id: ServerId) -> Optional[ArangoServer]:
        """Get a single server by ID."""
        return self._deployment.get_server(server_id) if self._deployment else None

    def get_deployment(self) -> Optional[Deployment]:
        """Get the current deployment."""
        return self._deployment
