"""Deployment strategies for different ArangoDB deployment modes."""

from typing import Dict, Optional
from concurrent.futures import ThreadPoolExecutor
from ..core.log import Logger
from ..core.types import TimeoutConfig
from ..core.errors import ServerError, ClusterError
from ..core.value_objects import ServerId
from .server import ArangoServer
from .deployment_plan import (
    DeploymentPlan,
    SingleServerDeploymentPlan,
    ClusterDeploymentPlan,
)
from .cluster_bootstrapper import ClusterBootstrapper
from .server_factory import ServerFactory


class SingleServerDeploymentStrategy:
    """Strategy for single server deployments.

    Responsibilities:
    - Create server instance from plan via ServerFactory
    - Start server and verify readiness
    - Record startup order
    - Return authoritative Dict[ServerId, ArangoServer]
    """

    def __init__(
        self,
        logger: Logger,
        server_factory: ServerFactory,
        timeout_config: TimeoutConfig,
    ) -> None:
        self._logger = logger
        self._factory = server_factory
        self._timeouts = timeout_config
        self._startup_order: list[ServerId] = []

    @property
    def startup_order(self) -> list[ServerId]:
        """Get startup order (copy)."""
        return list(self._startup_order)

    def deploy(
        self, plan: DeploymentPlan, timeout: Optional[float] = None
    ) -> Dict[ServerId, ArangoServer]:
        """Deploy a single server and return instances dict.

        Args:
            plan: SingleServerDeploymentPlan instance
            timeout: Optional override (falls back to configured single deployment timeout)

        Returns:
            Dict mapping ServerId -> ArangoServer

        Raises:
            ServerError: On type mismatch or health verification failure
        """
        if not isinstance(plan, SingleServerDeploymentPlan):
            raise ServerError(
                f"SingleServerDeploymentStrategy requires SingleServerDeploymentPlan, got {type(plan)}"
            )

        effective_timeout = timeout or self._timeouts.deployment_single
        servers = self._factory.create_server_instances([plan.server])

        if len(servers) != 1:
            raise ServerError(f"Factory created unexpected server count: {len(servers)}")

        server_id, server = next(iter(servers.items()))
        self._logger.info("Starting single server: %s", server_id)

        server.start(timeout=effective_timeout)
        self._startup_order.append(server_id)

        self._logger.debug("Verifying single server readiness")
        health = server.health_check_sync(timeout=effective_timeout)
        if not health.is_healthy:
            raise ServerError(
                f"Single server health check failed: {health.error_message}"
            )

        self._logger.info("Single server %s started and verified", server_id)
        return servers


class ClusterDeploymentStrategy:
    """Strategy for cluster deployments.

    Responsibilities:
    - Create all cluster servers from plan via ServerFactory
    - Delegate ordered parallel startup + readiness to ClusterBootstrapper
    - Record startup order
    - Return authoritative Dict[ServerId, ArangoServer]
    """

    def __init__(
        self,
        logger: Logger,
        server_factory: ServerFactory,
        executor: ThreadPoolExecutor,
        timeout_config: TimeoutConfig,
    ) -> None:
        self._logger = logger
        self._factory = server_factory
        self._bootstrapper = ClusterBootstrapper(logger, executor, timeout_config)
        self._timeouts = timeout_config
        self._startup_order: list[ServerId] = []

    @property
    def startup_order(self) -> list[ServerId]:
        """Get startup order (copy)."""
        return list(self._startup_order)

    def deploy(
        self, plan: DeploymentPlan, timeout: Optional[float] = None
    ) -> Dict[ServerId, ArangoServer]:
        """Deploy a cluster and return instances dict.

        Args:
            plan: ClusterDeploymentPlan instance
            timeout: Optional total deployment timeout (defaults to configured cluster timeout)

        Returns:
            Dict mapping ServerId -> ArangoServer

        Raises:
            ClusterError: On type mismatch or readiness failure propagated from bootstrapper
        """
        if not isinstance(plan, ClusterDeploymentPlan):
            raise ClusterError(
                f"ClusterDeploymentStrategy requires ClusterDeploymentPlan, got {type(plan)}"
            )

        effective_timeout = timeout or self._timeouts.deployment_cluster
        servers = self._factory.create_server_instances(plan.servers)

        self._logger.info("Starting cluster with %d servers", len(servers))

        self._bootstrapper.bootstrap_cluster(
            servers, self._startup_order, timeout=effective_timeout
        )

        self._logger.info(
            "Cluster deployment successful; startup order: %s",
            " -> ".join(str(sid) for sid in self._startup_order),
        )
        return servers
