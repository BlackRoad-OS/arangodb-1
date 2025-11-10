"""Deployment strategies for different ArangoDB deployment modes."""

from typing import Protocol, Dict, List
from concurrent.futures import ThreadPoolExecutor
from ..core.log import Logger
from ..core.types import TimeoutConfig
from ..core.errors import ServerError, ClusterError
from .server import ArangoServer
from .deployment_plan import (
    DeploymentPlan,
    SingleServerDeploymentPlan,
    ClusterDeploymentPlan,
)
from .cluster_bootstrapper import ClusterBootstrapper


class DeploymentStrategy(Protocol):
    """Strategy interface for mode-specific deployment logic."""

    def start_servers(
        self,
        servers: Dict[str, ArangoServer],
        plan: DeploymentPlan,
        startup_order: List[str],
        timeout: float,
    ) -> None:
        """Start servers and verify they are ready."""


class SingleServerStrategy:
    """Strategy for single server deployments."""

    def __init__(self, logger: Logger) -> None:
        self._logger = logger

    def start_servers(
        self,
        servers: Dict[str, ArangoServer],
        plan: DeploymentPlan,
        startup_order: List[str],
        timeout: float,
    ) -> None:
        """Start single server deployment and verify it's ready."""
        if not isinstance(plan, SingleServerDeploymentPlan):
            raise ServerError(
                f"SingleServerStrategy requires SingleServerDeploymentPlan, got {type(plan)}"
            )

        if len(servers) != 1:
            raise ServerError(f"Expected 1 server for single mode, got {len(servers)}")

        server_id, server = next(iter(servers.items()))
        self._logger.info("Starting single server: %s", server_id)

        server.start(timeout=timeout)
        startup_order.append(server_id)

        self._logger.info("Single server %s started successfully", server_id)

        # Verify server is ready and healthy
        self._logger.debug("Verifying single server readiness")
        health = server.health_check_sync(timeout=timeout)
        if not health.is_healthy:
            raise ServerError(
                f"Single server health check failed: {health.error_message}"
            )

        self._logger.debug("Single server is ready")


class ClusterStrategy:
    """Strategy for cluster deployments with agents, dbservers, and coordinators."""

    def __init__(
        self,
        logger: Logger,
        executor: ThreadPoolExecutor,
        timeout_config: TimeoutConfig,
    ) -> None:
        self._logger = logger
        self._bootstrapper = ClusterBootstrapper(logger, executor, timeout_config)

    def start_servers(
        self,
        servers: Dict[str, ArangoServer],
        plan: DeploymentPlan,
        startup_order: List[str],
        timeout: float,
    ) -> None:
        """Start cluster deployment with agents, dbservers, and coordinators.

        Bootstrapper handles server startup and verification internally.
        """
        if not isinstance(plan, ClusterDeploymentPlan):
            raise ClusterError(
                f"ClusterStrategy requires ClusterDeploymentPlan, got {type(plan)}"
            )

        from ..core.types import ServerRole
        from ..utils import print_status

        agents = sum(1 for s in servers.values() if s.role == ServerRole.AGENT)
        dbservers = sum(1 for s in servers.values() if s.role == ServerRole.DBSERVER)
        coordinators = sum(
            1 for s in servers.values() if s.role == ServerRole.COORDINATOR
        )

        print_status(
            f"Starting cluster with {agents} agents, {dbservers} dbservers, {coordinators} coordinators"
        )

        # Bootstrap cluster (includes startup and verification)
        self._bootstrapper.bootstrap_cluster(servers, startup_order, timeout=timeout)
