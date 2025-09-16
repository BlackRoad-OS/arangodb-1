"""Instance Manager for multi-server orchestration and lifecycle management."""

import asyncio
from typing import Dict, List, Optional, Set, Any, Callable
from pathlib import Path
from dataclasses import dataclass, field
import time
from concurrent.futures import ThreadPoolExecutor
import threading

from ..core.types import (
    DeploymentMode, ServerRole, ServerConfig, ClusterConfig,
    HealthStatus, ServerStats, ArmadilloConfig
)
from ..core.errors import (
    ServerError, ClusterError, ServerStartupError, ServerShutdownError,
    HealthCheckError, TimeoutError, AgencyError
)
from ..core.log import get_logger, Logger
from ..core.time import timeout_scope, clamp_timeout
from .server import ArangoServer
from ..core.config import get_config, ConfigProvider
from ..utils.ports import get_port_manager
from ..utils.filesystem import work_dir, server_dir, ensure_dir
from ..utils.auth import get_auth_provider

logger = get_logger(__name__)


@dataclass
class DeploymentPlan:
    """Plan for deploying a multi-server ArangoDB setup."""

    deployment_mode: DeploymentMode
    servers: List[ServerConfig] = field(default_factory=list)
    coordination_endpoints: List[str] = field(default_factory=list)
    agency_endpoints: List[str] = field(default_factory=list)

    def get_agents(self) -> List[ServerConfig]:
        """Get agent server configurations."""
        return [s for s in self.servers if s.role == ServerRole.AGENT]

    def get_coordinators(self) -> List[ServerConfig]:
        """Get coordinator server configurations."""
        return [s for s in self.servers if s.role == ServerRole.COORDINATOR]

    def get_dbservers(self) -> List[ServerConfig]:
        """Get database server configurations."""
        return [s for s in self.servers if s.role == ServerRole.DBSERVER]


class InstanceManager:
    """Manages lifecycle of multiple ArangoDB server instances."""

    def __init__(self, deployment_id: str, config_provider: Optional[ConfigProvider] = None, logger: Optional[Logger] = None) -> None:
        """Initialize instance manager.

        Args:
            deployment_id: Unique identifier for this deployment
            config_provider: Configuration provider (uses global config if None)
            logger: Logger instance (uses global logger if None)
        """
        self.deployment_id = deployment_id
        self.config = config_provider or get_config()
        self._logger = logger or get_logger(__name__)
        self.port_manager = get_port_manager()
        self.auth_provider = get_auth_provider()

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
        """Create deployment plan for the specified mode.

        Args:
            mode: Deployment mode
            cluster_config: Cluster configuration (for cluster mode)

        Returns:
            Deployment plan
        """
        plan = DeploymentPlan(deployment_mode=mode)

        if mode == DeploymentMode.SINGLE_SERVER:
            # Single server deployment
            port = self.port_manager.allocate_port("single")
            server_config = ServerConfig(
                role=ServerRole.SINGLE,
                port=port,
                data_dir=server_dir(self.deployment_id) / "single" / "data",
                log_file=server_dir(self.deployment_id) / "single" / "arangod.log"
            )
            plan.servers.append(server_config)
            plan.coordination_endpoints.append(f"http://127.0.0.1:{port}")

        elif mode == DeploymentMode.CLUSTER:
            cluster_cfg = cluster_config or self.config.cluster

            # Create agents
            agent_endpoints = []
            for i in range(cluster_cfg.agents):
                port = self.port_manager.allocate_port()  # Allocate any available port
                agent_config = ServerConfig(
                    role=ServerRole.AGENT,
                    port=port,
                    data_dir=server_dir(self.deployment_id) / f"agent_{i}" / "data",
                    log_file=server_dir(self.deployment_id) / f"agent_{i}" / "arangod.log",
                    args={
                        "agency.activate": "true",
                        "agency.size": str(cluster_cfg.agents),
                        "agency.supervision": "true",
                        "server.authentication": "false",  # Start with auth disabled
                        "agency.my-address": f"tcp://127.0.0.1:{port}",
                    }
                )
                plan.servers.append(agent_config)
                agent_endpoints.append(f"tcp://127.0.0.1:{port}")

            plan.agency_endpoints = agent_endpoints

            # Add agency endpoints to all agents
            for server in plan.get_agents():
                server.args["agency.endpoint"] = ",".join(agent_endpoints)

            # Create database servers
            for i in range(cluster_cfg.dbservers):
                port = self.port_manager.allocate_port()  # Allocate any available port
                dbserver_config = ServerConfig(
                    role=ServerRole.DBSERVER,
                    port=port,
                    data_dir=server_dir(self.deployment_id) / f"dbserver_{i}" / "data",
                    log_file=server_dir(self.deployment_id) / f"dbserver_{i}" / "arangod.log",
                    args={
                        "cluster.my-role": "PRIMARY",
                        "cluster.my-address": f"tcp://127.0.0.1:{port}",
                        "cluster.agency-endpoint": ",".join(agent_endpoints),
                        "server.authentication": "false",
                    }
                )
                plan.servers.append(dbserver_config)

            # Create coordinators
            coordinator_endpoints = []
            for i in range(cluster_cfg.coordinators):
                port = self.port_manager.allocate_port()  # Allocate any available port
                coordinator_config = ServerConfig(
                    role=ServerRole.COORDINATOR,
                    port=port,
                    data_dir=server_dir(self.deployment_id) / f"coordinator_{i}" / "data",
                    log_file=server_dir(self.deployment_id) / f"coordinator_{i}" / "arangod.log",
                    args={
                        "cluster.my-role": "COORDINATOR",
                        "cluster.my-address": f"tcp://127.0.0.1:{port}",
                        "cluster.agency-endpoint": ",".join(agent_endpoints),
                        "server.authentication": "false",
                    }
                )
                plan.servers.append(coordinator_config)
                coordinator_endpoints.append(f"http://127.0.0.1:{port}")

            plan.coordination_endpoints = coordinator_endpoints

        else:
            raise ValueError(f"Unsupported deployment mode: {mode}")

        self._deployment_plan = plan
        logger.info(f"Created deployment plan: {mode.value} with {len(plan.servers)} servers")
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
            logger.info(f"Starting deployment of {len(plan.servers)} servers")
            self._startup_time = time.time()

            try:
                # Create server instances
                self._create_server_instances()

                # Start servers in proper order
                if plan.deployment_mode == DeploymentMode.SINGLE_SERVER:
                    self._start_single_server()
                elif plan.deployment_mode == DeploymentMode.CLUSTER:
                    self._start_cluster()

                # Verify deployment health
                self._verify_deployment_health()

                self._is_deployed = True
                self._is_healthy = True

                deployment_time = time.time() - self._startup_time
                logger.info(f"Deployment completed successfully in {deployment_time:.2f}s")

            except Exception as e:
                logger.error(f"Deployment failed: {e}")
                # Try to cleanup partial deployment
                try:
                    self.shutdown_deployment()
                except:
                    pass
                raise ServerStartupError(f"Failed to deploy servers: {e}")

    def _create_server_instances(self) -> None:
        """Create ArangoServer instances from ServerConfig objects."""
        if not self._deployment_plan:
            raise ServerError("No deployment plan available")

        # Define a minimal config class to pass only needed data to ArangoServer
        @dataclass
        class MinimalConfig:
            args: dict
            memory_limit_mb: Optional[int] = None
            startup_timeout: float = 30.0

        self._servers = {}

        for i, server_config in enumerate(self._deployment_plan.servers):
            # Create server ID based on role and index
            if server_config.role == ServerRole.AGENT:
                server_id = f"agent_{i}"
            elif server_config.role == ServerRole.DBSERVER:
                server_id = f"dbserver_{i}"
            elif server_config.role == ServerRole.COORDINATOR:
                server_id = f"coordinator_{i}"
            else:
                server_id = f"server_{i}"

            # Create ArangoServer instance with explicit port value
            # Extract the integer port from server_config to avoid any object reference issues
            port_value = server_config.port
            if not isinstance(port_value, int):
                raise ServerError(f"Invalid port type for {server_id}: {type(port_value)} (expected int)")

            # Create a minimal config object with just the needed data to avoid port overrides
            minimal_config = MinimalConfig(
                args=server_config.args.copy(),
                memory_limit_mb=server_config.memory_limit_mb,
                startup_timeout=server_config.startup_timeout
            )

            server = ArangoServer(
                server_id=server_id,
                role=server_config.role,
                port=port_value,  # Use explicit integer port value
                config=minimal_config,  # Only pass needed configuration data
                config_provider=self.config,  # Pass injected config provider
                logger=self._logger  # Pass injected logger
            )

            # Set directories from ServerConfig after creation
            server.data_dir = server_config.data_dir
            server.log_file = server_config.log_file

            # Store the full ServerConfig for reference
            server._server_config = server_config

            self._servers[server_id] = server

            logger.debug(f"Created server instance {server_id} with role {server_config.role.value} on port {port_value}")

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
            logger.info(f"Shutting down deployment with {len(self._servers)} servers")

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
                    logger.debug(f"Server {server_id} shutdown completed")
                except Exception as e:
                    logger.error(f"Failed to shutdown server {server_id}: {e}")
                    failed_shutdowns.append(server_id)

            if failed_shutdowns:
                logger.warning(f"Some servers failed to shutdown cleanly: {failed_shutdowns}")

            # Release allocated ports
            self._release_ports()

            # Clear state
            self._servers.clear()
            self._startup_order.clear()
            self._shutdown_order.clear()
            self._is_deployed = False
            self._is_healthy = False

            shutdown_time = time.time() - self._shutdown_time
            logger.info(f"Deployment shutdown completed in {shutdown_time:.2f}s")

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
                from ..core.process import stop_supervised_process
                if hasattr(server, '_process_info') and server._process_info:
                    stop_supervised_process(server.server_id, graceful=True, timeout=timeout)
                else:
                    logger.warning(f"Server {server.server_id} has no process info - may already be stopped")

            log_server_event(logger, "stopped", server_id=server.server_id)
            logger.debug(f"Server {server.server_id} shutdown completed successfully")

        except Exception as e:
            log_server_event(logger, "stop_failed", server_id=server.server_id, error=str(e))
            logger.error(f"Failed to shutdown server {server.server_id}: {e}")

            # Try emergency force kill if graceful shutdown failed
            try:
                logger.warning(f"Attempting emergency force kill of server {server.server_id}")
                from ..core.process import stop_supervised_process
                if hasattr(server, '_process_info') and server._process_info:
                    stop_supervised_process(server.server_id, graceful=False, timeout=5.0)
                    logger.info(f"Emergency force kill of server {server.server_id} succeeded")
                else:
                    logger.debug(f"Server {server.server_id} has no process info for force kill")

            except Exception as force_e:
                logger.error(f"CRITICAL: Emergency force kill failed for server {server.server_id}: {force_e}")
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
                logger.warning(f"Failed to collect stats from {server_id}: {e}")

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

        logger.info(f"Starting single server {server_id}")
        server.start(timeout=60.0)

        self._startup_order.append(server_id)
        logger.info(f"Single server {server_id} started successfully")

    def _start_cluster(self) -> None:
        """Start cluster deployment in proper order."""
        # Start agents first
        agent_futures = []
        for server_id, server in self._servers.items():
            if server.role == ServerRole.AGENT:
                logger.info(f"Starting agent {server_id}")
                future = self._executor.submit(server.start, 60.0)
                agent_futures.append((server_id, future))

        # Wait for all agents to start
        for server_id, future in agent_futures:
            try:
                future.result(timeout=60.0)
                self._startup_order.append(server_id)
                logger.info(f"Agent {server_id} started successfully")
            except Exception as e:
                raise ServerStartupError(f"Failed to start agent {server_id}: {e}")

        # Wait for agency to become ready
        self._wait_for_agency_ready()

        # Start database servers
        dbserver_futures = []
        for server_id, server in self._servers.items():
            if server.role == ServerRole.DBSERVER:
                logger.info(f"Starting database server {server_id}")
                future = self._executor.submit(server.start, 60.0)
                dbserver_futures.append((server_id, future))

        # Wait for all database servers to start
        for server_id, future in dbserver_futures:
            try:
                future.result(timeout=60.0)
                self._startup_order.append(server_id)
                logger.info(f"Database server {server_id} started successfully")
            except Exception as e:
                raise ServerStartupError(f"Failed to start database server {server_id}: {e}")

        # Start coordinators
        coordinator_futures = []
        for server_id, server in self._servers.items():
            if server.role == ServerRole.COORDINATOR:
                logger.info(f"Starting coordinator {server_id}")
                future = self._executor.submit(server.start, 60.0)
                coordinator_futures.append((server_id, future))

        # Wait for all coordinators to start
        for server_id, future in coordinator_futures:
            try:
                future.result(timeout=60.0)
                self._startup_order.append(server_id)
                logger.info(f"Coordinator {server_id} started successfully")
            except Exception as e:
                raise ServerStartupError(f"Failed to start coordinator {server_id}: {e}")

        logger.info("All cluster servers started successfully")

    def _wait_for_agency_ready(self, timeout: float = 30.0) -> None:
        """Wait for agency to become ready.

        Args:
            timeout: Maximum time to wait
        """
        logger.info("Waiting for agency to become ready")

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                # Check if any agent is responsive
                for server_id, server in self._servers.items():
                    if server.role == ServerRole.AGENT:
                        health = server.health_check_sync(timeout=2.0)
                        if health.is_healthy:
                            logger.info("Agency is ready")
                            return
            except Exception:
                pass

            time.sleep(1.0)

        raise AgencyError("Agency did not become ready within timeout")

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
            logger.error(f"Error shutting down server {server.server_id}: {e}")
            raise

    def _release_ports(self) -> None:
        """Release all allocated ports."""
        try:
            self.port_manager.release_all()
        except Exception as e:
            logger.warning(f"Error releasing ports: {e}")


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
                logger.error(f"Error during manager cleanup: {e}")

        _instance_managers.clear()
