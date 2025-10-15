"""Deployment strategies for different ArangoDB deployment modes."""

from typing import Protocol, Dict, List
from ..core.log import Logger
from ..core.errors import ServerError, ClusterError
from .server import ArangoServer
from .server_registry import ServerRegistry
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
    ) -> None: ...

    def verify_readiness(
        self, servers: Dict[str, ArangoServer], timeout: float
    ) -> None: ...


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

    def verify_readiness(
        self, servers: Dict[str, ArangoServer], timeout: float
    ) -> None:
        server = next(iter(servers.values()))
        self._logger.debug("Verifying single server readiness")

        health = server.health_check_sync(timeout=timeout)
        if not health.is_healthy:
            raise ServerError(
                f"Single server health check failed: {health.error_message}"
            )

        self._logger.debug("Single server is ready")


class ClusterStrategy:
    """Strategy for cluster deployments with agents, dbservers, and coordinators."""

    def __init__(self, logger: Logger, bootstrapper: ClusterBootstrapper) -> None:
        self._logger = logger
        self._bootstrapper = bootstrapper

    def start_servers(
        self,
        servers: Dict[str, ArangoServer],
        plan: DeploymentPlan,
        startup_order: List[str],
        timeout: float,
    ) -> None:
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

        self._bootstrapper.bootstrap_cluster(servers, startup_order, timeout=timeout)

    def verify_readiness(
        self, servers: Dict[str, ArangoServer], timeout: float
    ) -> None:
        # Bootstrapper already verified cluster readiness
        self._logger.debug("Cluster readiness already verified by bootstrapper")
