"""Factory for creating deployment executors based on deployment plan type."""

from typing import Union
from concurrent.futures import ThreadPoolExecutor
from ..core.types import TimeoutConfig
from ..core.log import Logger
from ..core.errors import ServerError
from .deployment_plan import (
    DeploymentPlan,
    SingleServerDeploymentPlan,
    ClusterDeploymentPlan,
)
from .deployment_executor import SingleServerExecutor, ClusterExecutor
from .server_factory import ServerFactory


class DeploymentExecutorFactory:
    """Factory for creating deployment executors based on plan type.

    This factory encapsulates the logic for selecting and creating the appropriate
    executor for a given deployment plan, separating strategy selection from execution.
    """

    def __init__(
        self,
        logger: Logger,
        server_factory: ServerFactory,
        thread_executor: ThreadPoolExecutor,
        timeout_config: TimeoutConfig,
    ) -> None:
        """Initialize executor factory.

        Args:
            logger: Logger instance
            server_factory: Factory for creating servers
            thread_executor: Thread pool executor for parallel operations
            timeout_config: Timeout configuration
        """
        self._logger = logger
        self._server_factory = server_factory
        self._thread_executor = thread_executor
        self._timeouts = timeout_config

    def create_executor(
        self, plan: DeploymentPlan
    ) -> Union[SingleServerExecutor, ClusterExecutor]:
        """Create deployment executor based on plan type.

        Args:
            plan: Deployment plan to create executor for

        Returns:
            Appropriate executor instance (SingleServerExecutor or ClusterExecutor)

        Raises:
            ServerError: If plan type is unsupported
        """
        if isinstance(plan, SingleServerDeploymentPlan):
            return SingleServerExecutor(
                self._logger, self._server_factory, self._timeouts
            )
        if isinstance(plan, ClusterDeploymentPlan):
            return ClusterExecutor(
                self._logger,
                self._server_factory,
                self._thread_executor,
                self._timeouts,
            )
        raise ServerError(f"Unsupported deployment plan type: {type(plan)}")
