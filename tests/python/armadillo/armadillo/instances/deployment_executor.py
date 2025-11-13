"""Deployment executors for different ArangoDB deployment modes."""

import time
from typing import Dict, Optional
from concurrent.futures import ThreadPoolExecutor
from ..core.log import Logger
from ..core.types import TimeoutConfig, ServerRole
from ..core.errors import ServerError, ClusterError, ServerShutdownError, ProcessError
from ..core.value_objects import ServerId
from .server import ArangoServer
from .deployment_plan import (
    DeploymentPlan,
    SingleServerDeploymentPlan,
    ClusterDeploymentPlan,
)
from .deployment import (
    Deployment,
    SingleServerDeployment,
    ClusterDeployment,
    DeploymentStatus,
    DeploymentTiming,
)
from .cluster_bootstrapper import ClusterBootstrapper
from .server_factory import ServerFactory


class SingleServerExecutor:
    """Executor for single server deployments.

    Responsibilities:
    - Create server instance from plan via ServerFactory
    - Start server and verify readiness
    - Shutdown server
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

    def deploy(
        self, plan: DeploymentPlan, timeout: Optional[float] = None
    ) -> SingleServerDeployment:
        """Deploy a single server and return deployment.

        Args:
            plan: SingleServerDeploymentPlan instance
            timeout: Optional override (falls back to configured single deployment timeout)

        Returns:
            SingleServerDeployment with deployed server

        Raises:
            ServerError: On type mismatch or health verification failure
        """
        if not isinstance(plan, SingleServerDeploymentPlan):
            raise ServerError(
                f"SingleServerExecutor requires SingleServerDeploymentPlan, got {type(plan)}"
            )

        effective_timeout = timeout or self._timeouts.deployment_single
        servers = self._factory.create_server_instances([plan.server])

        if len(servers) != 1:
            raise ServerError(f"Factory created unexpected server count: {len(servers)}")

        server_id, server = next(iter(servers.items()))
        self._logger.info("Starting single server: %s", server_id)

        server.start(timeout=effective_timeout)

        self._logger.debug("Verifying single server readiness")
        health = server.health_check_sync(timeout=effective_timeout)
        if not health.is_healthy:
            raise ServerError(
                f"Single server health check failed: {health.error_message}"
            )

        self._logger.info("Single server %s started and verified", server_id)
        return SingleServerDeployment(
            plan=plan,
            server=server,  # Single server object, not dict
            status=DeploymentStatus(is_deployed=True, is_healthy=True),
            timing=DeploymentTiming(startup_time=time.time()),
        )

    def shutdown(self, deployment: SingleServerDeployment, timeout: float) -> None:
        """Shutdown single server.

        Trivial: only one server to stop.

        Args:
            deployment: SingleServerDeployment to shutdown
            timeout: Maximum time to wait for shutdown

        Raises:
            ServerShutdownError: If shutdown fails
        """
        server = deployment.server  # Direct access, no dict iteration needed
        self._logger.info("Shutting down single server: %s", server.server_id)

        try:
            server.stop(timeout=timeout)
            self._logger.info("Server stopped successfully")
            deployment.status.is_deployed = False
        except (ServerShutdownError, ProcessError, OSError) as e:
            self._logger.error("Failed to stop server: %s", e)
            raise


class ClusterExecutor:
    """Executor for cluster deployments.

    Responsibilities:
    - Create all cluster servers from plan via ServerFactory
    - Delegate ordered parallel startup + readiness to ClusterBootstrapper
    - Shutdown servers in role-based order (non-agents → agents)
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

    def deploy(
        self, plan: DeploymentPlan, timeout: Optional[float] = None
    ) -> ClusterDeployment:
        """Deploy a cluster and return deployment.

        Args:
            plan: ClusterDeploymentPlan instance
            timeout: Optional total deployment timeout (defaults to configured cluster timeout)

        Returns:
            ClusterDeployment with deployed servers

        Raises:
            ClusterError: On type mismatch or readiness failure propagated from bootstrapper
        """
        if not isinstance(plan, ClusterDeploymentPlan):
            raise ClusterError(
                f"ClusterExecutor requires ClusterDeploymentPlan, got {type(plan)}"
            )

        effective_timeout = timeout or self._timeouts.deployment_cluster
        servers = self._factory.create_server_instances(plan.servers)

        self._logger.info("Starting cluster with %d servers", len(servers))

        self._bootstrapper.bootstrap_cluster(servers, timeout=effective_timeout)

        self._logger.info("Cluster deployment successful")
        return ClusterDeployment(
            plan=plan,
            servers=servers,  # Dict for multiple servers
            status=DeploymentStatus(is_deployed=True, is_healthy=True),
            timing=DeploymentTiming(startup_time=time.time()),
        )

    def shutdown(self, deployment: ClusterDeployment, timeout: float) -> None:
        """Shutdown cluster in role-based order.

        Shutdown order: Non-agents first, then agents

        This is NOT reverse of startup because agents provide coordination
        services. They must shut down LAST to maintain cluster state during
        shutdown of coordinators and dbservers.

        Args:
            deployment: ClusterDeployment to shutdown
            timeout: Maximum time to wait for shutdown

        Raises:
            ServerShutdownError: If shutdown fails critically
        """
        servers = deployment.get_servers()
        if not servers:
            return

        # Separate by role
        agents = deployment.get_servers_by_role(ServerRole.AGENT)
        non_agents = [s for s in servers.values() if s.role != ServerRole.AGENT]

        self._logger.info(
            "Shutting down cluster: %d non-agents, then %d agents",
            len(non_agents),
            len(agents),
        )

        # Calculate per-server timeout
        total_servers = deployment.get_server_count()
        per_server_timeout = timeout / max(1, total_servers)

        failed_shutdowns = []

        # Shutdown non-agents first
        for server in non_agents:
            try:
                self._logger.info("Shutting down %s", server.server_id)
                server.stop(timeout=per_server_timeout)
                self._logger.info("Server %s stopped", server.server_id)
            except (ServerShutdownError, ProcessError, OSError) as e:
                # Continue shutting down other servers even if one fails
                self._logger.error("Failed to stop %s: %s", server.server_id, e)
                failed_shutdowns.append(server.server_id)

        # Shutdown agents last
        for server in agents:
            try:
                self._logger.info("Shutting down agent %s", server.server_id)
                server.stop(timeout=per_server_timeout)
                self._logger.info("Agent %s stopped", server.server_id)
            except (ServerShutdownError, ProcessError, OSError) as e:
                # Continue shutting down other servers even if one fails
                self._logger.error("Failed to stop agent %s: %s", server.server_id, e)
                failed_shutdowns.append(server.server_id)

        if failed_shutdowns:
            self._logger.warning(
                "Some servers failed to shutdown cleanly: %s", failed_shutdowns
            )

        deployment.status.is_deployed = False

