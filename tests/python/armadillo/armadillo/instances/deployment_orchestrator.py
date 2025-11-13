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
        self._executor_factory = DeploymentExecutorFactory(
            logger=logger,
            server_factory=server_factory,
            thread_executor=executor,
            timeout_config=self._timeouts,
        )

    def execute_deployment(
        self, plan: DeploymentPlan, timeout: Optional[float] = None
    ) -> Deployment:
        """Execute deployment based on plan using executor pattern.

        Args:
            plan: Deployment plan to execute
            timeout: Optional timeout override

        Returns:
            Deployment object with deployed servers

        Raises:
            ServerStartupError: If deployment fails
        """
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

            elapsed_total = time.time() - start_time
            self._logger.info(
                "Deployment completed successfully in %.2fs", elapsed_total
            )

            return deployment

        except (ServerStartupError, ProcessError, ClusterError, OSError) as e:
            self._logger.error("Deployment failed: %s", e, exc_info=True)
            raise

    def shutdown_deployment(
        self,
        deployment: Deployment,
        timeout: Optional[float] = None,
    ) -> None:
        """Shutdown all servers in the deployment using executor.

        Args:
            deployment: Deployment to shutdown
            timeout: Maximum time to wait for shutdown (uses config default if None)

        Raises:
            ServerError: If shutdown fails critically
        """
        if timeout is None:
            # Calculate timeout based on number of servers
            # Allow per-server timeout + 20% buffer for coordination overhead
            num_servers = deployment.get_server_count()
            timeout = self._timeouts.server_shutdown * max(1, num_servers) * 1.2
        else:
            num_servers = deployment.get_server_count()

        self._logger.info(
            "Shutting down %d server(s) with %.1fs timeout",
            num_servers,
            timeout,
        )

        # Print shutdown message with newline to separate from test output
        if isinstance(deployment, SingleServerDeployment):
            print_status("\nShutting down server")
        else:
            print_status(
                f"\nShutting down cluster with {deployment.get_server_count()} servers"
            )

        # Create executor for shutdown (executors are stateless, can recreate)
        executor = self._executor_factory.create_executor(deployment.plan)
        executor.shutdown(deployment, timeout)
