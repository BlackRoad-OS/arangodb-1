"""Instance Manager for multi-server orchestration and lifecycle management."""

from typing import Dict, List, Optional, Any
import time
from concurrent.futures import ThreadPoolExecutor
import threading
import requests

from ..core.types import (
    DeploymentMode, ServerRole, ServerConfig, ClusterConfig,
    HealthStatus, ServerStats, ArmadilloConfig
)
from ..core.errors import (
    ServerError, ClusterError, ServerStartupError, ServerShutdownError,
    HealthCheckError, TimeoutError, AgencyError
)
from ..core.log import get_logger, Logger, log_server_event
from ..core.time import timeout_scope, clamp_timeout
from ..core.process import stop_supervised_process
from .server import ArangoServer
from .deployment_planner import DeploymentPlanner, StandardDeploymentPlanner
from .server_factory import ServerFactory, StandardServerFactory
from ..core.config import get_config, ConfigProvider
from ..utils.ports import get_port_manager, PortAllocator
from ..utils.auth import get_auth_provider
from .deployment_plan import DeploymentPlan

logger = get_logger(__name__)




class InstanceManager:
    """Manages lifecycle of multiple ArangoDB server instances."""

    def __init__(self, deployment_id: str, config_provider: Optional[ConfigProvider] = None, logger: Optional[Logger] = None, port_allocator: Optional[PortAllocator] = None, deployment_planner: Optional[DeploymentPlanner] = None, server_factory: Optional[ServerFactory] = None) -> None:
        """Initialize instance manager.

        Args:
            deployment_id: Unique identifier for this deployment
            config_provider: Configuration provider (uses global config if None)
            logger: Logger instance (uses global logger if None)
            port_allocator: Port allocator (uses global manager if None)
            deployment_planner: Deployment planner (creates standard planner if None)
            server_factory: Server factory (creates standard factory if None)
        """
        self.deployment_id = deployment_id
        self.config = config_provider or get_config()
        self._logger = logger or get_logger(__name__)
        self.port_manager = port_allocator or get_port_manager()
        self.auth_provider = get_auth_provider()

        # Create deployment planner with injected dependencies
        self._deployment_planner = deployment_planner or StandardDeploymentPlanner(
            port_allocator=self.port_manager,
            logger=self._logger
        )

        # Create server factory with injected dependencies
        self._server_factory = server_factory or StandardServerFactory(
            config_provider=self.config,
            logger=self._logger,
            port_allocator=self.port_manager
        )

        # Instance state
        self._servers: Dict[str, ArangoServer] = {}
        self._deployment_plan: Optional[DeploymentPlan] = None
        self._startup_order: List[str] = []
        self._shutdown_order: List[str] = []

        # Lifecycle state
        self._is_deployed = False
        self._is_healthy = False
        self._startup_time: Optional[float] = None
        self._shutdown_time: Optional[float] = None

        # Threading
        self._executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix=f"InstanceMgr-{deployment_id}")
        self._lock = threading.RLock()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        try:
            if self._is_deployed:
                self.shutdown_deployment()
        finally:
            self._executor.shutdown(wait=True)

    def create_deployment_plan(
        self,
        mode: DeploymentMode,
        cluster_config: Optional[ClusterConfig] = None
    ) -> DeploymentPlan:
        """Create deployment plan for the specified mode using injected planner.

        Args:
            mode: Deployment mode
            cluster_config: Cluster configuration (for cluster mode)

        Returns:
            Deployment plan
        """
        # Use default cluster config if none provided for cluster mode
        if mode == DeploymentMode.CLUSTER and cluster_config is None:
            cluster_config = self.config.cluster

        plan = self._deployment_planner.create_deployment_plan(
            deployment_id=self.deployment_id,
            mode=mode,
            cluster_config=cluster_config
        )

        self._deployment_plan = plan
        return plan

    def deploy_servers(self, timeout: float = 300.0) -> None:
        """Deploy all servers according to the current plan.

        Args:
            timeout: Maximum time to wait for deployment

        Raises:
            ServerStartupError: If server deployment fails
            TimeoutError: If deployment times out
        """
        if not self._deployment_plan:
            raise ServerError("No deployment plan created")

        if self._is_deployed:
            raise ServerError("Deployment already active")

        plan = self._deployment_plan
        timeout = clamp_timeout(timeout, "deployment")

        with timeout_scope(timeout, f"deploy_servers_{self.deployment_id}"):
            logger.info("Starting deployment of %s servers", len(plan.servers))
            self._startup_time = time.time()

            try:
                # Create server instances
                self._create_server_instances()

                # Start servers in proper order
                if plan.deployment_mode == DeploymentMode.SINGLE_SERVER:
                    self._start_single_server()
                elif plan.deployment_mode == DeploymentMode.CLUSTER:
                    self._start_cluster()

                # Mark deployment as active before health check
                self._is_deployed = True

                # Verify deployment health
                self._verify_deployment_health()

                self._is_healthy = True

                deployment_time = time.time() - self._startup_time
                logger.info("Deployment completed successfully in %.2fs", deployment_time)

            except Exception as e:
                logger.error("Deployment failed: %s", e)
                # Try to cleanup partial deployment
                try:
                    self.shutdown_deployment()
                except:
                    pass
                raise ServerStartupError(f"Failed to deploy servers: {e}") from e

    def _create_server_instances(self) -> None:
        """Create ArangoServer instances using injected server factory."""
        if not self._deployment_plan:
            raise ServerError("No deployment plan available")

        self._servers = self._server_factory.create_server_instances(
            self._deployment_plan.servers
        )

    def shutdown_deployment(self, timeout: float = 120.0) -> None:
        """Shutdown all deployed servers.

        Args:
            timeout: Maximum time to wait for shutdown
        """
        if not self._is_deployed:
            logger.debug("No deployment to shutdown")
            return

        timeout = clamp_timeout(timeout, "shutdown")
        self._shutdown_time = time.time()

        with timeout_scope(timeout, f"shutdown_deployment_{self.deployment_id}"):
            logger.info("Shutting down deployment with %s servers", len(self._servers))

            # Shutdown in reverse order
            shutdown_order = list(reversed(self._startup_order))

            # Stop servers concurrently but with ordering constraints
            futures = []
            for server_id in shutdown_order:
                if server_id in self._servers:
                    server = self._servers[server_id]
                    future = self._executor.submit(self._shutdown_server, server, 30.0)
                    futures.append((server_id, future))

            # Wait for all shutdowns to complete
            failed_shutdowns = []
            for server_id, future in futures:
                try:
                    future.result(timeout=30.0)
                    logger.debug("Server %s shutdown completed", server_id)
                except Exception as e:
                    logger.error("Failed to shutdown server %s: %s", server_id, e)
                    failed_shutdowns.append(server_id)

            if failed_shutdowns:
                logger.warning("Some servers failed to shutdown cleanly: %s", failed_shutdowns)

            # Release allocated ports
            self._release_ports()

            # Clear state
            self._servers.clear()
            self._startup_order.clear()
            self._shutdown_order.clear()
            self._is_deployed = False
            self._is_healthy = False

            shutdown_time = time.time() - self._shutdown_time
            logger.info("Deployment shutdown completed in %.2fs", shutdown_time)

    def _shutdown_server(self, server: 'ArangoServer', timeout: float = 30.0) -> None:
        """Shutdown a single server instance with bulletproof termination.

        Args:
            server: The server instance to shutdown
            timeout: Maximum time to wait for shutdown
        """
        try:
            log_server_event(logger, "stopping", server_id=server.server_id, timeout=timeout)

            # Try to stop the server gracefully first
            if hasattr(server, 'stop') and callable(server.stop):
                # Use server's own stop method (should use graceful=True by default)
                server.stop(timeout=timeout)
            else:
                # Fallback: stop via process supervisor with graceful escalation
                if hasattr(server, '_process_info') and server._process_info:
                    stop_supervised_process(server.server_id, graceful=True, timeout=timeout)
                else:
                    logger.warning("Server %s has no process info - may already be stopped", server.server_id)

            log_server_event(logger, "stopped", server_id=server.server_id)
            logger.debug("Server %s shutdown completed successfully", server.server_id)

        except Exception as e:
            log_server_event(logger, "stop_failed", server_id=server.server_id, error=str(e))
            logger.error("Failed to shutdown server %s: %s", server.server_id, e)

            # Try emergency force kill if graceful shutdown failed
            try:
                logger.warning("Attempting emergency force kill of server %s", server.server_id)
                if hasattr(server, '_process_info') and server._process_info:
                    stop_supervised_process(server.server_id, graceful=False, timeout=5.0)
                    logger.info("Emergency force kill of server %s succeeded", server.server_id)
                else:
                    logger.debug("Server %s has no process info for force kill", server.server_id)

            except Exception as force_e:
                logger.error("CRITICAL: Emergency force kill failed for server %s: %s", server.server_id, force_e)
                # Don't re-raise - we want to continue shutting down other servers

            # Re-raise the original error for the caller to handle
            raise

    def restart_deployment(self, timeout: float = 300.0) -> None:
        """Restart the entire deployment.

        Args:
            timeout: Maximum time for restart operation
        """
        logger.info("Restarting deployment")

        # Preserve current plan
        current_plan = self._deployment_plan

        # Shutdown current deployment
        self.shutdown_deployment(timeout / 2)

        # Restore plan and redeploy
        self._deployment_plan = current_plan
        self.deploy_servers(timeout / 2)

    def get_server(self, server_id: str) -> Optional[ArangoServer]:
        """Get server instance by ID.

        Args:
            server_id: Server identifier

        Returns:
            Server instance or None if not found
        """
        return self._servers.get(server_id)

    def get_servers_by_role(self, role: ServerRole) -> List[ArangoServer]:
        """Get all servers with the specified role.

        Args:
            role: Server role to filter by

        Returns:
            List of servers with the specified role
        """
        return [
            server for server in self._servers.values()
            if server.role == role
        ]

    def get_coordination_endpoints(self) -> List[str]:
        """Get coordination endpoints (coordinators or single server).

        Returns:
            List of coordination endpoints
        """
        if not self._deployment_plan:
            return []
        return self._deployment_plan.coordination_endpoints

    def get_agency_endpoints(self) -> List[str]:
        """Get agency endpoints.

        Returns:
            List of agency endpoints
        """
        if not self._deployment_plan:
            return []
        return self._deployment_plan.agency_endpoints

    def check_deployment_health(self, timeout: float = 30.0) -> HealthStatus:
        """Check health of the entire deployment.

        Args:
            timeout: Timeout for health check

        Returns:
            Overall deployment health status
        """
        if not self._is_deployed:
            return HealthStatus(
                is_healthy=False,
                response_time=0.0,
                error_message="No deployment active"
            )

        start_time = time.time()

        try:
            # Check all servers
            unhealthy_servers = []
            total_response_time = 0.0

            for server_id, server in self._servers.items():
                try:
                    health = server.health_check_sync(timeout=timeout / len(self._servers))
                    total_response_time += health.response_time

                    if not health.is_healthy:
                        unhealthy_servers.append(f"{server_id}: {health.error_message}")

                except Exception as e:
                    unhealthy_servers.append(f"{server_id}: {str(e)}")

            elapsed_time = time.time() - start_time
            avg_response_time = total_response_time / len(self._servers) if self._servers else 0.0

            if unhealthy_servers:
                error_msg = f"Unhealthy servers: {', '.join(unhealthy_servers)}"
                self._is_healthy = False
                return HealthStatus(
                    is_healthy=False,
                    response_time=elapsed_time,
                    error_message=error_msg,
                    details={"unhealthy_count": len(unhealthy_servers), "total_count": len(self._servers)}
                )

            self._is_healthy = True
            return HealthStatus(
                is_healthy=True,
                response_time=avg_response_time,
                details={"server_count": len(self._servers)}
            )

        except Exception as e:
            self._is_healthy = False
            return HealthStatus(
                is_healthy=False,
                response_time=time.time() - start_time,
                error_message=f"Health check failed: {str(e)}"
            )

    def collect_server_stats(self) -> Dict[str, ServerStats]:
        """Collect statistics from all servers.

        Returns:
            Dictionary mapping server IDs to their stats
        """
        stats = {}

        for server_id, server in self._servers.items():
            try:
                server_stats = server.collect_stats()
                stats[server_id] = server_stats
            except Exception as e:
                logger.warning("Failed to collect stats from %s: %s", server_id, e)

        return stats

    def is_deployed(self) -> bool:
        """Check if deployment is active."""
        return self._is_deployed

    def is_healthy(self) -> bool:
        """Check if deployment is healthy."""
        return self._is_healthy

    def get_server_count(self) -> int:
        """Get total number of servers in deployment."""
        return len(self._servers)

    def get_deployment_info(self) -> Dict[str, Any]:
        """Get comprehensive deployment information.

        Returns:
            Dictionary with deployment details
        """
        info = {
            "deployment_id": self.deployment_id,
            "is_deployed": self._is_deployed,
            "is_healthy": self._is_healthy,
            "server_count": len(self._servers),
            "startup_time": self._startup_time,
            "shutdown_time": self._shutdown_time,
        }

        if self._deployment_plan:
            info.update({
                "deployment_mode": self._deployment_plan.deployment_mode.value,
                "coordination_endpoints": self._deployment_plan.coordination_endpoints,
                "agency_endpoints": self._deployment_plan.agency_endpoints,
            })

        # Add server details
        info["servers"] = {}
        for server_id, server in self._servers.items():
            info["servers"][server_id] = {
                "role": server.role.value,
                "endpoint": server.endpoint,
                "is_running": server.is_running(),
                "pid": server.get_pid(),
            }

        return info

    # Private methods


    def _start_single_server(self) -> None:
        """Start single server deployment."""
        server = list(self._servers.values())[0]
        server_id = list(self._servers.keys())[0]

        logger.info("Starting single server %s", server_id)
        server.start(timeout=60.0)

        self._startup_order.append(server_id)
        logger.info("Single server %s started successfully", server_id)

    def _start_cluster(self) -> None:
        """Start cluster deployment in proper sequence: agents -> wait -> dbservers -> coordinators."""
        logger.info("Starting cluster servers in sequence")

        # 1. Start agents first
        logger.info("Starting agents...")
        agent_futures = []
        for server_id, server in self._servers.items():
            if server.role == ServerRole.AGENT:
                logger.info("Starting agent %s", server_id)
                future = self._executor.submit(server.start, 60.0)
                agent_futures.append((server_id, future))

        # Wait for all agents to start
        for server_id, future in agent_futures:
            try:
                future.result(timeout=60.0)
                self._startup_order.append(server_id)
                logger.info("Agent %s started successfully", server_id)
            except Exception as e:
                raise ServerStartupError(f"Failed to start agent {server_id}: {e}") from e

        # 2. Wait for agency to become ready
        logger.info("Waiting for agency to become ready...")
        self._wait_for_agency_ready()
        logger.info("Agency is ready!")

        # 3. Start database servers
        logger.info("Starting database servers...")
        dbserver_futures = []
        for server_id, server in self._servers.items():
            if server.role == ServerRole.DBSERVER:
                logger.info("Starting database server %s", server_id)
                future = self._executor.submit(server.start, 60.0)
                dbserver_futures.append((server_id, future))

        # Wait for all database servers to start
        for server_id, future in dbserver_futures:
            try:
                future.result(timeout=60.0)
                self._startup_order.append(server_id)
                logger.info("Database server %s started successfully", server_id)
            except Exception as e:
                raise ServerStartupError(f"Failed to start database server {server_id}: {e}") from e

        # 4. Start coordinators
        logger.info("Starting coordinators...")
        coordinator_futures = []
        for server_id, server in self._servers.items():
            if server.role == ServerRole.COORDINATOR:
                logger.info("Starting coordinator %s", server_id)
                future = self._executor.submit(server.start, 60.0)
                coordinator_futures.append((server_id, future))

        # Wait for all coordinators to start
        for server_id, future in coordinator_futures:
            try:
                future.result(timeout=60.0)
                self._startup_order.append(server_id)
                logger.info("Coordinator %s started successfully", server_id)
            except Exception as e:
                raise ServerStartupError(f"Failed to start coordinator {server_id}: {e}") from e

        logger.info("All cluster servers started successfully")

        # 5. Final readiness check
        logger.info("Performing final cluster readiness check...")
        self._wait_for_cluster_ready()
        logger.info("Cluster is fully ready!")

    def _wait_for_agency_ready(self, timeout: float = 30.0) -> None:
        """Wait for agency to become ready - matches JavaScript detectAgencyAlive logic.

        Args:
            timeout: Maximum time to wait
        """
        logger.info("Waiting for agency to become ready")

        start_time = time.time()

        # Get all agents
        agents = [(server_id, server) for server_id, server in self._servers.items()
                 if server.role == ServerRole.AGENT]

        iteration = 0
        while time.time() - start_time < timeout:
            iteration += 1
            try:
                have_config = 0
                have_leader = 0
                leader_id = None

                logger.debug("Agency check iteration %s", iteration)

                # Check each agent for leadership and configuration
                for server_id, server in agents:
                    try:
                        logger.debug("Checking agent %s at %s", server_id, server.endpoint)
                        response = requests.get(f"{server.endpoint}/_api/agency/config", timeout=2.0)
                        logger.debug("Agent %s response: %s", server_id, response.status_code)

                        if response.status_code == 200:
                            config = response.json()
                            logger.debug("Agent %s config keys: %s", server_id, list(config.keys()))

                            # Check for leadership (like JS lastAcked check)
                            if 'lastAcked' in config:
                                have_leader += 1
                                logger.debug("Agent %s has leadership", server_id)

                            # Check for configuration (like JS leaderId check)
                            if 'leaderId' in config and config['leaderId'] != "":
                                have_config += 1
                                logger.debug("Agent %s has leaderId: %s", server_id, config['leaderId'])
                                if leader_id is None:
                                    leader_id = config['leaderId']
                                elif leader_id != config['leaderId']:
                                    # Agents disagree on leader - reset
                                    logger.debug("Agent %s disagrees on leader: %s vs %s", server_id, config['leaderId'], leader_id)
                                    have_leader = 0
                                    have_config = 0
                                    break
                        else:
                            logger.debug("Agent %s not ready: %s", server_id, response.status_code)
                    except Exception as e:
                        # Agent not ready yet
                        logger.debug("Agent %s not responding: %s", server_id, e)
                        pass

                logger.debug("Agency status: have_leader=%s, have_config=%s, need_config=%s", have_leader, have_config, len(agents))

                # Check if agency is fully ready (like JavaScript condition)
                if have_leader >= 1 and have_config == len(agents):
                    logger.info("Agency is ready!")
                    return

            except Exception as e:
                logger.debug("Agency check exception: %s", e)
                pass

            # Log progress every 10 iterations to avoid spam
            if iteration % 10 == 0:
                logger.info("Still waiting for agency (iteration %s)", iteration)

            time.sleep(0.5)

        raise AgencyError("Agency did not become ready within timeout")

    def _wait_for_cluster_ready(self, timeout: float = 600.0) -> None:
        """Wait for all cluster nodes to become ready - matches JavaScript checkClusterAlive logic.

        Args:
            timeout: Maximum time to wait (10 minutes like JS framework)
        """
        logger.info("Waiting for all cluster nodes to become ready")

        start_time = time.time()
        count = 0

        while time.time() - start_time < timeout:
            count += 1
            all_ready = True

            for server_id, server in self._servers.items():
                try:
                    # Choose endpoint based on server role (like JavaScript logic)
                    if server.role == ServerRole.COORDINATOR:
                        # Use /_api/foxx for coordinators (like JS)
                        url = f"{server.endpoint}/_api/foxx"
                        method = 'GET'
                    else:
                        # Use /_api/version for agents and dbservers (like JS)
                        url = f"{server.endpoint}/_api/version"
                        method = 'POST'

                    response = requests.request(method, url, timeout=2.0)

                    if response.status_code == 200:
                        logger.debug("Server %s (%s) is ready", server_id, server.role.value)
                        continue
                    elif response.status_code == 403:
                        # Service API might be disabled (like JS error handling)
                        try:
                            error_body = response.json()
                            if error_body.get('errorNum') == 1931:  # ERROR_SERVICE_API_DISABLED
                                logger.debug("Service API disabled on %s, continuing", server_id)
                                continue
                        except:
                            pass

                    # Server not ready
                    all_ready = False
                    logger.debug("Server %s not ready yet (status: %s)", server_id, response.status_code)

                except Exception as e:
                    # Server not responding
                    all_ready = False
                    logger.debug("Server %s not responding: %s", server_id, e)

            if all_ready:
                logger.info("All cluster nodes are ready!")
                return

            # Avoid log spam - only log every 10 iterations
            if count % 10 == 0:
                logger.info("Still waiting for cluster readiness (attempt %s)...", count)

            time.sleep(0.5)

        raise ClusterError(f"Cluster did not become ready within {timeout} seconds")

    def _verify_deployment_health(self) -> None:
        """Verify that all servers in deployment are healthy."""
        logger.info("Verifying deployment health")

        health = self.check_deployment_health(timeout=30.0)
        if not health.is_healthy:
            raise HealthCheckError(f"Deployment health verification failed: {health.error_message}")

        logger.info("Deployment health verification passed")

    def _shutdown_server(self, server: ArangoServer, timeout: float) -> None:
        """Shutdown a single server.

        Args:
            server: Server to shutdown
            timeout: Shutdown timeout
        """
        try:
            if server.is_running():
                server.stop(timeout=timeout)
        except Exception as e:
            logger.error("Error shutting down server %s: %s", server.server_id, e)
            raise

    def _release_ports(self) -> None:
        """Release all allocated ports."""
        try:
            self.port_manager.release_all()
        except Exception as e:
            logger.warning("Error releasing ports: %s", e)


# Global instance manager registry
_instance_managers: Dict[str, InstanceManager] = {}
_manager_lock = threading.Lock()


def get_instance_manager(deployment_id: str) -> InstanceManager:
    """Get or create instance manager for deployment.

    Args:
        deployment_id: Unique deployment identifier

    Returns:
        Instance manager instance
    """
    with _manager_lock:
        if deployment_id not in _instance_managers:
            _instance_managers[deployment_id] = InstanceManager(deployment_id)
        return _instance_managers[deployment_id]


def cleanup_instance_managers() -> None:
    """Cleanup all instance managers."""
    with _manager_lock:
        for manager in _instance_managers.values():
            try:
                if manager.is_deployed():
                    manager.shutdown_deployment()
            except Exception as e:
                logger.error("Error during manager cleanup: %s", e)

        _instance_managers.clear()
