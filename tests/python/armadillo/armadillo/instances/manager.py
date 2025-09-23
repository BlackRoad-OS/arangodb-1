"""Instance Manager for multi-server orchestration and lifecycle management."""

from typing import Dict, List, Optional, Any, Tuple
import time
from concurrent.futures import ThreadPoolExecutor
import threading
from dataclasses import dataclass, field
import requests

from ..core.types import (
    DeploymentMode, ServerRole, ClusterConfig,
    HealthStatus, ServerStats
)
from ..core.errors import (
    ServerError, ClusterError, ServerStartupError, ServerShutdownError,
    HealthCheckError, AgencyError
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

@dataclass
class ManagerDependencies:
    """Injectable dependencies for InstanceManager."""
    config: ConfigProvider
    logger: Logger
    port_manager: PortAllocator
    auth_provider: 'AuthProvider'
    deployment_planner: DeploymentPlanner
    server_factory: ServerFactory

    @classmethod
    def create_defaults(cls, deployment_id: str,
                       config: Optional[ConfigProvider] = None,
                       custom_logger: Optional[Logger] = None,
                       port_allocator: Optional[PortAllocator] = None) -> 'ManagerDependencies':
        """Create dependencies with deployment-specific defaults."""
        final_config = config or get_config()

        # Create deployment-specific logger with context if not provided
        if custom_logger:
            final_logger = custom_logger
        else:
            base_logger = get_logger(f"{__name__}.{deployment_id}")
            final_logger = base_logger

        final_port_manager = port_allocator or get_port_manager()

        return cls(
            config=final_config,
            logger=final_logger,
            port_manager=final_port_manager,
            auth_provider=get_auth_provider(),
            deployment_planner=StandardDeploymentPlanner(
                port_allocator=final_port_manager,
                logger=final_logger
            ),
            server_factory=StandardServerFactory(
                config_provider=final_config,
                logger=final_logger,
                port_allocator=final_port_manager
            )
        )

@dataclass
class DeploymentStatus:
    """Status information for a deployment."""
    is_deployed: bool = False
    is_healthy: bool = False

@dataclass
class DeploymentTiming:
    """Timing information for a deployment."""
    startup_time: Optional[float] = None
    shutdown_time: Optional[float] = None

@dataclass
class DeploymentState:
    """Runtime state of a deployment."""
    servers: Dict[str, ArangoServer] = field(default_factory=dict)
    deployment_plan: Optional[DeploymentPlan] = None
    startup_order: List[str] = field(default_factory=list)
    shutdown_order: List[str] = field(default_factory=list)
    status: DeploymentStatus = field(default_factory=DeploymentStatus)
    timing: DeploymentTiming = field(default_factory=DeploymentTiming)

@dataclass
class ThreadingResources:
    """Threading resources for parallel operations."""
    executor: ThreadPoolExecutor
    lock: threading.RLock

    @classmethod
    def create_for_deployment(cls, deployment_id: str) -> 'ThreadingResources':
        """Create threading resources for a deployment."""
        return cls(
            executor=ThreadPoolExecutor(
                max_workers=10,
                thread_name_prefix=f"InstanceMgr-{deployment_id}"
            ),
            lock=threading.RLock()
        )

    def cleanup(self) -> None:
        """Clean up threading resources."""
        self.executor.shutdown(wait=True)


class InstanceManager:
    """Manages lifecycle of multiple ArangoDB server instances."""

    def __init__(self,
                 deployment_id: str,
                 *,
                 dependencies: Optional[ManagerDependencies] = None,
                 **legacy_kwargs) -> None:
        """Initialize instance manager with composition-based design.

        Args:
            deployment_id: Unique identifier for this deployment
            dependencies: Composed dependencies object (recommended)
            **legacy_kwargs: Backward compatibility support for:
                config_provider, logger, port_allocator, deployment_planner, server_factory
        """
        self.deployment_id = deployment_id

        # Initialize dependencies - handle both new and legacy styles
        if dependencies is not None:
            self._deps = dependencies
        elif legacy_kwargs:
            # Legacy constructor style - extract from kwargs
            config_provider = legacy_kwargs.get('config_provider')
            legacy_logger = legacy_kwargs.get('logger')
            port_allocator = legacy_kwargs.get('port_allocator')
            deployment_planner = legacy_kwargs.get('deployment_planner')
            server_factory = legacy_kwargs.get('server_factory')

            self._deps = ManagerDependencies.create_defaults(
                deployment_id=deployment_id,
                config=config_provider,
                custom_logger=legacy_logger,
                port_allocator=port_allocator
            )
            # Override with explicitly provided legacy parameters
            if deployment_planner is not None:
                self._deps.deployment_planner = deployment_planner
            if server_factory is not None:
                self._deps.server_factory = server_factory
        else:
            # No parameters provided, use all defaults
            self._deps = ManagerDependencies.create_defaults(deployment_id=deployment_id)

        # Initialize runtime state and threading resources
        self.state = DeploymentState()
        self._threading = ThreadingResources.create_for_deployment(deployment_id)

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        try:
            if self.state.status.is_deployed:
                self.shutdown_deployment()
        finally:
            self._threading.executor.shutdown(wait=True)

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
            cluster_config = self._deps.config.cluster

        plan = self._deps.deployment_planner.create_deployment_plan(
            deployment_id=self.deployment_id,
            mode=mode,
            cluster_config=cluster_config
        )

        self.state.deployment_plan = plan
        return plan

    def deploy_servers(self, timeout: float = 300.0) -> None:
        """Deploy all servers according to the current plan.

        Args:
            timeout: Maximum time to wait for deployment

        Raises:
            ServerStartupError: If server deployment fails
            TimeoutError: If deployment times out
        """
        if not self.state.deployment_plan:
            raise ServerError("No deployment plan created")

        if self.state.status.is_deployed:
            raise ServerError("Deployment already active")

        plan = self.state.deployment_plan
        timeout = clamp_timeout(timeout, "deployment")

        with timeout_scope(timeout, f"deploy_servers_{self.deployment_id}"):
            logger.info("Starting deployment of %s servers", len(plan.servers))
            self.state.timing.startup_time = time.time()

            try:
                # Create server instances
                self._create_server_instances()

                # Start servers in proper order
                if plan.deployment_mode == DeploymentMode.SINGLE_SERVER:
                    self._start_single_server()
                elif plan.deployment_mode == DeploymentMode.CLUSTER:
                    self._start_cluster()

                # Mark deployment as active before health check
                self.state.status.is_deployed = True

                # Verify deployment health
                self._verify_deployment_health()

                self.state.status.is_healthy = True

                deployment_time = time.time() - self.state.timing.startup_time
                logger.info("Deployment completed successfully in %.2fs", deployment_time)

            except Exception as e:
                logger.error("Deployment failed: %s", e)
                # Try to cleanup partial deployment
                try:
                    self.shutdown_deployment()
                except (OSError, ProcessLookupError, RuntimeError, AttributeError):
                    pass
                raise ServerStartupError(f"Failed to deploy servers: {e}") from e

    def _create_server_instances(self) -> None:
        """Create ArangoServer instances using injected server factory."""
        if not self.state.deployment_plan:
            raise ServerError("No deployment plan available")

        self.state.servers = self._deps.server_factory.create_server_instances(
            self.state.deployment_plan.servers
        )

    def shutdown_deployment(self, timeout: float = 120.0) -> None:
        """Shutdown all deployed servers.

        Args:
            timeout: Maximum time to wait for shutdown
        """
        if not self.state.status.is_deployed:
            logger.debug("No deployment to shutdown")
            return

        timeout = clamp_timeout(timeout, "shutdown")
        self.state.timing.shutdown_time = time.time()

        with timeout_scope(timeout, f"shutdown_deployment_{self.deployment_id}"):
            logger.info("Shutting down deployment with %s servers", len(self.state.servers))

            # Shutdown in reverse order
            shutdown_order = list(reversed(self.state.startup_order))

            # Stop servers concurrently but with ordering constraints
            futures = []
            for server_id in shutdown_order:
                if server_id in self.state.servers:
                    server = self.state.servers[server_id]
                    future = self._threading.executor.submit(self._shutdown_server, server, 30.0)
                    futures.append((server_id, future))

            # Wait for all shutdowns to complete
            failed_shutdowns = []
            for server_id, future in futures:
                try:
                    future.result(timeout=30.0)
                    logger.debug("Server %s shutdown completed", server_id)
                except (TimeoutError, OSError, ServerShutdownError) as e:
                    logger.error("Failed to shutdown server %s: %s", server_id, e)
                    failed_shutdowns.append(server_id)

            if failed_shutdowns:
                logger.warning("Some servers failed to shutdown cleanly: %s", failed_shutdowns)

            # Release allocated ports
            self._release_ports()

            # Clear state
            self.state.servers.clear()
            self.state.startup_order.clear()
            self.state.shutdown_order.clear()
            self.state.status.is_deployed = False
            self.state.status.is_healthy = False

            shutdown_time = time.time() - self.state.timing.shutdown_time
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
                if server.is_running():
                    stop_supervised_process(
                        server.server_id, graceful=True, timeout=timeout
                    )
                else:
                    logger.warning(
                        "Server %s has no process info - may already be stopped", server.server_id
                    )

            log_server_event(logger, "stopped", server_id=server.server_id)
            logger.debug("Server %s shutdown completed successfully", server.server_id)

        except Exception as e:
            log_server_event(logger, "stop_failed", server_id=server.server_id, error=str(e))
            logger.error("Failed to shutdown server %s: %s", server.server_id, e)

            # Try emergency force kill if graceful shutdown failed
            try:
                logger.warning("Attempting emergency force kill of server %s", server.server_id)
                if server.is_running():
                    stop_supervised_process(server.server_id, graceful=False, timeout=5.0)
                    logger.info("Emergency force kill of server %s succeeded", server.server_id)
                else:
                    logger.debug("Server %s has no process info for force kill", server.server_id)

            except (OSError, PermissionError, ProcessError) as force_e:
                logger.error(
                    "CRITICAL: Emergency force kill failed for server %s: %s",
                    server.server_id, force_e
                )
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
        current_plan = self.state.deployment_plan

        # Shutdown current deployment
        self.shutdown_deployment(timeout / 2)

        # Restore plan and redeploy
        self.state.deployment_plan = current_plan
        self.deploy_servers(timeout / 2)

    def get_server(self, server_id: str) -> Optional[ArangoServer]:
        """Get server instance by ID.

        Args:
            server_id: Server identifier

        Returns:
            Server instance or None if not found
        """
        return self.state.servers.get(server_id)

    def get_servers_by_role(self, role: ServerRole) -> List[ArangoServer]:
        """Get all servers with the specified role.

        Args:
            role: Server role to filter by

        Returns:
            List of servers with the specified role
        """
        return [
            server for server in self.state.servers.values()
            if server.role == role
        ]

    def get_all_servers(self) -> Dict[str, ArangoServer]:
        """Get all servers as a dictionary.

        Returns:
            Dictionary mapping server IDs to server instances
        """
        return dict(self.state.servers)

    def get_coordination_endpoints(self) -> List[str]:
        """Get coordination endpoints (coordinators or single server).

        Returns:
            List of coordination endpoints
        """
        if not self.state.deployment_plan:
            return []
        return self.state.deployment_plan.coordination_endpoints

    def get_agency_endpoints(self) -> List[str]:
        """Get agency endpoints.

        Returns:
            List of agency endpoints
        """
        if not self.state.deployment_plan:
            return []
        return self.state.deployment_plan.agency_endpoints

    def check_deployment_health(self, timeout: float = 30.0) -> HealthStatus:
        """Check health of the entire deployment.

        Args:
            timeout: Timeout for health check

        Returns:
            Overall deployment health status
        """
        if not self.state.status.is_deployed:
            return HealthStatus(
                is_healthy=False,
                response_time=0.0,
                error_message="No deployment active"
            )

        start_time = time.time()

        try:
            # Collect health data from all servers
            unhealthy_servers, total_response_time = self._collect_server_health_data(timeout)

            # Calculate metrics
            elapsed_time = time.time() - start_time
            avg_response_time = (
                total_response_time / len(self.state.servers) if self.state.servers else 0.0
            )

            # Determine overall health and update state
            is_healthy = len(unhealthy_servers) == 0
            self.state.status.is_healthy = is_healthy

            if is_healthy:
                return self._create_health_status(True, avg_response_time)

            error_msg = f"Unhealthy servers: {', '.join(unhealthy_servers)}"
            return self._create_health_status(False, elapsed_time, error_msg, unhealthy_servers)

        except (ServerError, NetworkError, OSError) as e:
            self.state.status.is_healthy = False
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

        for server_id, server in self.state.servers.items():
            try:
                server_stats = server.collect_stats()
                stats[server_id] = server_stats
            except (OSError, ConnectionError, TimeoutError) as e:
                logger.warning("Failed to collect stats from %s: %s", server_id, e)

        return stats

    def is_deployed(self) -> bool:
        """Check if deployment is active."""
        return self.state.status.is_deployed

    def is_healthy(self) -> bool:
        """Check if deployment is healthy."""
        return self.state.status.is_healthy

    def get_server_count(self) -> int:
        """Get total number of servers in deployment."""
        return len(self.state.servers)

    def get_deployment_info(self) -> Dict[str, Any]:
        """Get comprehensive deployment information.

        Returns:
            Dictionary with deployment details
        """
        info = {
            "deployment_id": self.deployment_id,
            "is_deployed": self.state.status.is_deployed,
            "is_healthy": self.state.status.is_healthy,
            "server_count": len(self.state.servers),
            "startup_time": self.state.timing.startup_time,
            "shutdown_time": self.state.timing.shutdown_time,
        }

        if self.state.deployment_plan:
            info.update({
                "deployment_mode": self.state.deployment_plan.deployment_mode.value,
                "coordination_endpoints": self.state.deployment_plan.coordination_endpoints,
                "agency_endpoints": self.state.deployment_plan.agency_endpoints,
            })

        # Add server details
        info["servers"] = {}
        for server_id, server in self.state.servers.items():
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
        server = list(self.state.servers.values())[0]
        server_id = list(self.state.servers.keys())[0]

        logger.info("Starting single server %s", server_id)
        server.start(timeout=60.0)

        self.state.startup_order.append(server_id)
        logger.info("Single server %s started successfully", server_id)

    def _start_cluster(self) -> None:
        """Start cluster deployment in proper sequence:
        agents -> wait -> dbservers -> coordinators.
        """
        logger.info("Starting cluster servers in sequence")

        # 1. Start agents first
        self._start_servers_by_role(ServerRole.AGENT)

        # 2. Wait for agency to become ready
        logger.info("Waiting for agency to become ready...")
        self._wait_for_agency_ready()
        logger.info("Agency is ready!")

        # 3. Start database servers
        self._start_servers_by_role(ServerRole.DBSERVER)

        # 4. Start coordinators
        self._start_servers_by_role(ServerRole.COORDINATOR)

        logger.info("All cluster servers started successfully")

        # 5. Final readiness check
        logger.info("Performing final cluster readiness check...")
        self._wait_for_cluster_ready()
        logger.info("Cluster is fully ready!")

    def _get_agents(self) -> List[Tuple[str, ArangoServer]]:
        """Get list of agent servers."""
        return [(server_id, server) for server_id, server in self.state.servers.items()
                if server.role == ServerRole.AGENT]

    def _check_agent_config(self, server_id: str, server: ArangoServer) -> Optional[Dict[str, Any]]:
        """Check configuration of a single agent.

        Returns:
            Agent config dict if successful, None if agent not ready
        """
        try:
            logger.debug("Checking agent %s at %s", server_id, server.endpoint)
            response = requests.get(f"{server.endpoint}/_api/agency/config", timeout=2.0)
            logger.debug("Agent %s response: %s", server_id, response.status_code)

            if response.status_code == 200:
                config = response.json()
                logger.debug("Agent %s config keys: %s", server_id, list(config.keys()))
                return config

            logger.debug("Agent %s not ready: %s", server_id, response.status_code)
            return None
        except (requests.RequestException, OSError, TimeoutError) as e:
            logger.debug("Agent %s not responding: %s", server_id, e)
            return None

    def _analyze_agency_status(self, agents: List[Tuple[str, ArangoServer]]) -> Tuple[int, int, bool]:
        """Analyze agency status across all agents.

        Returns:
            Tuple of (have_leader, have_config, consensus_valid)
        """
        have_config = 0
        have_leader = 0
        leader_id = None
        consensus_valid = True

        for server_id, server in agents:
            config = self._check_agent_config(server_id, server)
            if not config:
                continue

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
                    consensus_valid = False
                    break

        return have_leader, have_config, consensus_valid

    def _start_servers_by_role(self, role: ServerRole, timeout: float = 60.0) -> None:
        """Start all servers of a specific role in parallel.

        Args:
            role: Server role to start
            timeout: Timeout for each server startup
        """
        role_name = role.value
        servers_to_start = [(server_id, server) for server_id, server in self.state.servers.items()
                           if server.role == role]

        if not servers_to_start:
            logger.debug("No %s servers to start", role_name)
            return

        logger.info("Starting %s servers...", role_name)

        # Start all servers of this role in parallel
        futures = []
        for server_id, server in servers_to_start:
            logger.info("Starting %s %s", role_name, server_id)
            future = self._threading.executor.submit(server.start, timeout)
            futures.append((server_id, future))

        # Wait for all servers to complete startup
        for server_id, future in futures:
            try:
                future.result(timeout=timeout)
                self.state.startup_order.append(server_id)
                logger.info("%s %s started successfully", role_name.title(), server_id)
            except Exception as e:
                raise ServerStartupError(f"Failed to start {role_name} {server_id}: {e}") from e

    def _wait_for_agency_ready(self, timeout: float = 30.0) -> None:
        """Wait for agency to become ready - matches JavaScript detectAgencyAlive logic.

        Args:
            timeout: Maximum time to wait
        """
        logger.info("Waiting for agency to become ready")

        start_time = time.time()
        agents = self._get_agents()
        iteration = 0

        while time.time() - start_time < timeout:
            iteration += 1

            try:
                logger.debug("Agency check iteration %s", iteration)

                have_leader, have_config, consensus_valid = self._analyze_agency_status(agents)

                if not consensus_valid:
                    # Reset and try again if agents disagree
                    have_leader = 0
                    have_config = 0

                logger.debug("Agency status: have_leader=%s, have_config=%s, need_config=%s",
                           have_leader, have_config, len(agents))

                # Check if agency is fully ready (like JavaScript condition)
                if have_leader >= 1 and have_config == len(agents):
                    logger.info("Agency is ready!")
                    return

            except (requests.RequestException, OSError, TimeoutError) as e:
                logger.debug("Agency check exception: %s", e)

            # Log progress every 10 iterations to avoid spam
            if iteration % 10 == 0:
                logger.info("Still waiting for agency (iteration %s)", iteration)

            time.sleep(0.5)

        raise AgencyError("Agency did not become ready within timeout")

    def _get_server_readiness_endpoint(self, server: ArangoServer) -> Tuple[str, str]:
        """Get the appropriate readiness check endpoint for a server.

        Args:
            server: Server to check

        Returns:
            Tuple of (url, method) for readiness check
        """
        if server.role == ServerRole.COORDINATOR:
            # Use /_api/foxx for coordinators (like JS)
            return f"{server.endpoint}/_api/foxx", 'GET'

        # Use /_api/version for agents and dbservers (like JS)
        return f"{server.endpoint}/_api/version", 'POST'

    def _check_server_readiness(self, server_id: str, server: ArangoServer) -> bool:
        """Check if a single server is ready.

        Args:
            server_id: Server identifier
            server: Server instance

        Returns:
            True if server is ready, False otherwise
        """
        try:
            url, method = self._get_server_readiness_endpoint(server)
            response = requests.request(method, url, timeout=2.0)

            if response.status_code == 200:
                logger.debug("Server %s (%s) is ready", server_id, server.role.value)
                return True

            if response.status_code == 403:
                # Service API might be disabled (like JS error handling)
                if self._is_service_api_disabled_error(response):
                    logger.debug("Service API disabled on %s, continuing", server_id)
                    return True

            # Server not ready
            logger.debug("Server %s not ready yet (status: %s)", server_id, response.status_code)
            return False

        except (requests.RequestException, OSError, NetworkError) as e:
            # Server not responding
            logger.debug("Server %s not responding: %s", server_id, e)
            return False

    def _is_service_api_disabled_error(self, response) -> bool:
        """Check if response indicates service API is disabled.

        Args:
            response: HTTP response object

        Returns:
            True if this is a service API disabled error
        """
        try:
            error_body = response.json()
            return error_body.get('errorNum') == 1931  # ERROR_SERVICE_API_DISABLED
        except (ValueError, KeyError, AttributeError):
            return False

    def _check_all_servers_ready(self) -> bool:
        """Check if all servers in the cluster are ready.

        Returns:
            True if all servers are ready, False otherwise
        """
        for server_id, server in self.state.servers.items():
            if not self._check_server_readiness(server_id, server):
                return False
        return True

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

            if self._check_all_servers_ready():
                logger.info("All cluster nodes are ready!")
                return

            # Avoid log spam - only log every 10 iterations
            if count % 10 == 0:
                logger.info("Still waiting for cluster readiness (attempt %s)...", count)

            time.sleep(0.5)

        raise ClusterError(f"Cluster did not become ready within {timeout} seconds")

    def _collect_server_health_data(self, timeout: float) -> Tuple[List[str], float]:
        """Collect health data from all servers.

        Args:
            timeout: Total timeout to distribute among servers

        Returns:
            Tuple of (unhealthy_servers, total_response_time)
        """
        unhealthy_servers = []
        total_response_time = 0.0
        per_server_timeout = timeout / len(self.state.servers) if self.state.servers else timeout

        for server_id, server in self.state.servers.items():
            try:
                health = server.health_check_sync(timeout=per_server_timeout)
                total_response_time += health.response_time

                if not health.is_healthy:
                    unhealthy_servers.append(f"{server_id}: {health.error_message}")

            except (OSError, TimeoutError, HealthCheckError) as e:
                unhealthy_servers.append(f"{server_id}: {str(e)}")

        return unhealthy_servers, total_response_time

    def _create_health_status(self, is_healthy: bool, response_time: float,
                             error_message: str = "", unhealthy_servers: List[str] = None) -> HealthStatus:
        """Create a HealthStatus object with appropriate details.

        Args:
            is_healthy: Whether the deployment is healthy
            response_time: Response time for the check
            error_message: Error message if unhealthy
            unhealthy_servers: List of unhealthy server descriptions

        Returns:
            Configured HealthStatus object
        """
        if is_healthy:
            return HealthStatus(
                is_healthy=True,
                response_time=response_time,
                details={"server_count": len(self.state.servers)}
            )

        details = {"unhealthy_count": len(unhealthy_servers or []), "total_count": len(self.state.servers)}
        return HealthStatus(
            is_healthy=False,
            response_time=response_time,
            error_message=error_message,
            details=details
        )

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
            self._deps.port_manager.release_all()
        except (OSError, RuntimeError, ValueError) as e:
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
            except (ServerError, ServerShutdownError, OSError) as e:
                logger.error("Error during manager cleanup: %s", e)

        _instance_managers.clear()
