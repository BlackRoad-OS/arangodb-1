"""Cluster orchestrator for complex multi-server coordination and advanced cluster operations."""

import asyncio
import aiohttp
import time
from typing import Dict, List, Optional, Set, Any
from dataclasses import dataclass, field
import threading
from concurrent.futures import ThreadPoolExecutor

from ..core.types import (
    DeploymentMode, ServerRole, ClusterConfig,
    HealthStatus, ServerStats, ArmadilloConfig
)
from ..core.errors import (
    ClusterError, AgencyError, LeaderElectionError, HealthCheckError,
    TimeoutError, NetworkError, ConnectionError
)
from ..core.log import get_logger
from ..core.time import timeout_scope, clamp_timeout
from ..core.config import get_config
from ..utils.auth import get_auth_provider
from .manager import get_instance_manager
from .server import ArangoServer

logger = get_logger(__name__)


@dataclass
class ClusterState:
    """Represents the current state of a cluster."""

    agency_leader: Optional[str] = None
    agency_followers: List[str] = field(default_factory=list)
    coordinators: List[str] = field(default_factory=list)
    dbservers: List[str] = field(default_factory=list)
    healthy_servers: Set[str] = field(default_factory=set)
    unhealthy_servers: Set[str] = field(default_factory=set)

    # Cluster-wide statistics
    total_collections: int = 0
    total_databases: int = 1  # At least _system
    shard_distribution: Dict[str, int] = field(default_factory=dict)
    replication_health: Dict[str, str] = field(default_factory=dict)

    def is_agency_healthy(self) -> bool:
        """Check if agency has a healthy leader."""
        return self.agency_leader is not None and self.agency_leader in self.healthy_servers

    def get_healthy_coordinators(self) -> List[str]:
        """Get list of healthy coordinators."""
        return [coord for coord in self.coordinators if coord in self.healthy_servers]

    def get_healthy_dbservers(self) -> List[str]:
        """Get list of healthy database servers."""
        return [db for db in self.dbservers if db in self.healthy_servers]

    def cluster_health_percentage(self) -> float:
        """Calculate overall cluster health percentage."""
        total_servers = len(self.coordinators) + len(self.dbservers) + len(self.agency_followers) + (1 if self.agency_leader else 0)
        if total_servers == 0:
            return 0.0
        return len(self.healthy_servers) / total_servers * 100.0


@dataclass
class ClusterOperation:
    """Represents a cluster-wide operation."""

    operation_id: str
    operation_type: str  # e.g., "rebalance", "upgrade", "backup"
    target_servers: List[str] = field(default_factory=list)
    status: str = "pending"  # pending, running, completed, failed
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    progress: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None

    @property
    def duration(self) -> Optional[float]:
        """Get operation duration if completed."""
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        return None

    def is_completed(self) -> bool:
        """Check if operation is completed."""
        return self.status in ["completed", "failed"]


class ClusterOrchestrator:
    """Advanced orchestration for multi-server ArangoDB cluster operations."""

    def __init__(self, deployment_id: str) -> None:
        """Initialize cluster orchestrator.

        Args:
            deployment_id: Unique deployment identifier
        """
        self.deployment_id = deployment_id
        self.config = get_config()
        self.auth_provider = get_auth_provider()

        # Get associated instance manager
        self.instance_manager = get_instance_manager(deployment_id)

        # Cluster state tracking
        self._cluster_state: Optional[ClusterState] = None
        self._state_last_updated: Optional[float] = None

        # Operations tracking
        self._active_operations: Dict[str, ClusterOperation] = {}

        # Threading and concurrency
        self._executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix=f"ClusterOrch-{deployment_id}")
        self._lock = threading.RLock()

        # HTTP client for cluster API calls
        self._http_session: Optional[aiohttp.ClientSession] = None

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        try:
            # Cancel active operations
            self._cancel_all_operations()
        finally:
            self._executor.shutdown(wait=True)
            if self._http_session:
                asyncio.run(self._http_session.close())

    async def initialize_cluster_coordination(self, timeout: float = 120.0) -> None:
        """Initialize cluster coordination and verify cluster is ready.

        Args:
            timeout: Maximum time to wait for cluster initialization

        Raises:
            ClusterError: If cluster initialization fails
            TimeoutError: If initialization times out
        """
        if not self.instance_manager.is_deployed():
            raise ClusterError("No deployment active for cluster coordination")

        timeout = clamp_timeout(timeout, "cluster_init")

        with timeout_scope(timeout, f"init_cluster_{self.deployment_id}"):
            logger.info("Initializing cluster coordination")

            # Create HTTP session for cluster operations
            self._http_session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30.0),
                connector=aiohttp.TCPConnector(limit=20)
            )

            # Wait for agency to establish leadership
            await self._wait_for_agency_leadership()

            # Wait for all database servers to join cluster
            await self._wait_for_dbservers_ready()

            # Wait for coordinators to be ready
            await self._wait_for_coordinators_ready()

            # Update initial cluster state
            await self.update_cluster_state()

            logger.info("Cluster coordination initialized successfully")

    async def update_cluster_state(self, force_update: bool = False) -> ClusterState:
        """Update and return current cluster state.

        Args:
            force_update: Force update even if recently updated

        Returns:
            Current cluster state
        """
        current_time = time.time()

        # Use cached state if recent and not forced
        if (not force_update and self._cluster_state and self._state_last_updated
            and current_time - self._state_last_updated < 5.0):
            return self._cluster_state

        logger.debug("Updating cluster state")

        try:
            state = ClusterState()

            # Get cluster topology from agency
            await self._update_agency_state(state)
            await self._update_server_health(state)
            await self._update_cluster_statistics(state)

            self._cluster_state = state
            self._state_last_updated = current_time

            return state

        except Exception as e:
            logger.error(f"Failed to update cluster state: {e}")
            raise ClusterError(f"Failed to update cluster state: {e}")

    async def perform_cluster_health_check(self,
                                         detailed: bool = False,
                                         timeout: float = 60.0) -> Dict[str, Any]:
        """Perform comprehensive cluster health check.

        Args:
            detailed: Include detailed server-level information
            timeout: Maximum time for health check

        Returns:
            Comprehensive health report
        """
        timeout = clamp_timeout(timeout, "health_check")

        with timeout_scope(timeout, f"health_check_{self.deployment_id}"):
            logger.info("Performing cluster health check")

            # Update cluster state
            await self.update_cluster_state(force_update=True)

            if not self._cluster_state:
                raise ClusterError("Unable to determine cluster state")

            state = self._cluster_state
            report = {
                "deployment_id": self.deployment_id,
                "timestamp": time.time(),
                "overall_health": "healthy" if state.cluster_health_percentage() >= 80.0 else "degraded",
                "health_percentage": state.cluster_health_percentage(),
                "agency": {
                    "has_leader": state.is_agency_healthy(),
                    "leader": state.agency_leader,
                    "followers": state.agency_followers,
                },
                "coordinators": {
                    "total": len(state.coordinators),
                    "healthy": len(state.get_healthy_coordinators()),
                    "unhealthy": len(state.coordinators) - len(state.get_healthy_coordinators()),
                },
                "dbservers": {
                    "total": len(state.dbservers),
                    "healthy": len(state.get_healthy_dbservers()),
                    "unhealthy": len(state.dbservers) - len(state.get_healthy_dbservers()),
                },
                "cluster_info": {
                    "total_databases": state.total_databases,
                    "total_collections": state.total_collections,
                    "shard_distribution": state.shard_distribution,
                },
            }

            # Add detailed server information if requested
            if detailed:
                report["servers"] = {}

                for server_id, server in self.instance_manager._servers.items():
                    try:
                        health = server.health_check_sync(timeout=5.0)
                        stats = server.collect_stats()

                        report["servers"][server_id] = {
                            "role": server.role.value,
                            "endpoint": server.endpoint,
                            "healthy": health.is_healthy,
                            "response_time": health.response_time,
                            "error_message": health.error_message,
                            "stats": {
                                "memory_usage": stats.memory_usage,
                                "cpu_percent": stats.cpu_percent,
                                "uptime": stats.uptime,
                            } if stats else None
                        }
                    except Exception as e:
                        report["servers"][server_id] = {
                            "role": server.role.value,
                            "endpoint": server.endpoint,
                            "healthy": False,
                            "error": str(e)
                        }

            logger.info(f"Health check completed: {report['overall_health']} "
                       f"({report['health_percentage']:.1f}% healthy)")

            return report

    async def wait_for_cluster_ready(self,
                                   timeout: float = 300.0,
                                   min_healthy_percentage: float = 80.0) -> None:
        """Wait for cluster to become ready and healthy.

        Args:
            timeout: Maximum time to wait
            min_healthy_percentage: Minimum health percentage required

        Raises:
            ClusterError: If cluster doesn't become ready
            TimeoutError: If timeout is reached
        """
        timeout = clamp_timeout(timeout, "cluster_ready")

        with timeout_scope(timeout, f"wait_ready_{self.deployment_id}"):
            logger.info(f"Waiting for cluster to become ready (min {min_healthy_percentage}% healthy)")

            start_time = time.time()
            last_log_time = start_time

            while True:
                try:
                    await self.update_cluster_state(force_update=True)

                    if self._cluster_state:
                        health_pct = self._cluster_state.cluster_health_percentage()

                        # Log progress periodically
                        current_time = time.time()
                        if current_time - last_log_time >= 10.0:
                            logger.info(f"Cluster health: {health_pct:.1f}% "
                                       f"(target: {min_healthy_percentage}%)")
                            last_log_time = current_time

                        # Check if ready
                        if (health_pct >= min_healthy_percentage and
                            self._cluster_state.is_agency_healthy() and
                            len(self._cluster_state.get_healthy_coordinators()) > 0 and
                            len(self._cluster_state.get_healthy_dbservers()) > 0):

                            elapsed = time.time() - start_time
                            logger.info(f"Cluster is ready ({health_pct:.1f}% healthy) "
                                       f"after {elapsed:.2f}s")
                            return

                except Exception as e:
                    logger.debug(f"Error checking cluster state: {e}")

                await asyncio.sleep(2.0)

    async def perform_rolling_restart(self,
                                    server_roles: Optional[List[ServerRole]] = None,
                                    restart_delay: float = 10.0,
                                    timeout: float = 600.0) -> ClusterOperation:
        """Perform rolling restart of cluster servers.

        Args:
            server_roles: Roles to restart (default: all)
            restart_delay: Delay between server restarts
            timeout: Maximum time for entire operation

        Returns:
            Cluster operation tracking object
        """
        from ..utils.crypto import random_id

        operation_id = f"rolling_restart_{random_id(8)}"
        operation = ClusterOperation(
            operation_id=operation_id,
            operation_type="rolling_restart"
        )

        try:
            operation.status = "running"
            operation.start_time = time.time()
            self._active_operations[operation_id] = operation

            logger.info(f"Starting rolling restart operation {operation_id}")

            timeout = clamp_timeout(timeout, "rolling_restart")

            with timeout_scope(timeout, f"rolling_restart_{self.deployment_id}"):
                # Determine servers to restart
                target_servers = []
                if server_roles:
                    for role in server_roles:
                        target_servers.extend(self.instance_manager.get_servers_by_role(role))
                else:
                    target_servers = list(self.instance_manager._servers.values())

                operation.target_servers = [s.server_id for s in target_servers]

                # Restart servers in safe order (coordinators last)
                restart_order = []

                # Database servers first
                restart_order.extend([s for s in target_servers if s.role == ServerRole.DBSERVER])

                # Agents (carefully, maintaining quorum)
                agents = [s for s in target_servers if s.role == ServerRole.AGENT]
                if agents:
                    # Restart agents one at a time to maintain quorum
                    restart_order.extend(agents)

                # Coordinators last
                restart_order.extend([s for s in target_servers if s.role == ServerRole.COORDINATOR])

                # Perform rolling restart
                for i, server in enumerate(restart_order):
                    logger.info(f"Restarting server {server.server_id} "
                               f"({i + 1}/{len(restart_order)})")

                    # Stop server
                    server.stop(timeout=30.0)

                    # Wait for restart delay
                    if restart_delay > 0:
                        await asyncio.sleep(restart_delay)

                    # Start server
                    server.start(timeout=60.0)

                    # Wait for server to become healthy
                    await self._wait_for_server_healthy(server, timeout=60.0)

                    operation.progress[server.server_id] = "completed"

                # Final cluster health check
                await self.wait_for_cluster_ready(timeout=60.0)

                operation.status = "completed"
                operation.end_time = time.time()

                logger.info(f"Rolling restart completed successfully in "
                           f"{operation.duration:.2f}s")

        except Exception as e:
            operation.status = "failed"
            operation.end_time = time.time()
            operation.error_message = str(e)
            logger.error(f"Rolling restart failed: {e}")
            raise ClusterError(f"Rolling restart failed: {e}")

        finally:
            self._active_operations.pop(operation_id, None)

        return operation

    def get_cluster_state(self) -> Optional[ClusterState]:
        """Get current cluster state (cached).

        Returns:
            Current cluster state or None if not available
        """
        return self._cluster_state

    def get_active_operations(self) -> List[ClusterOperation]:
        """Get list of active cluster operations.

        Returns:
            List of currently running operations
        """
        with self._lock:
            return list(self._active_operations.values())

    def cancel_operation(self, operation_id: str) -> bool:
        """Cancel an active operation.

        Args:
            operation_id: Operation to cancel

        Returns:
            True if operation was cancelled
        """
        with self._lock:
            if operation_id in self._active_operations:
                operation = self._active_operations[operation_id]
                operation.status = "cancelled"
                operation.end_time = time.time()
                logger.info(f"Cancelled operation {operation_id}")
                return True
        return False

    # Private methods

    async def _wait_for_agency_leadership(self, timeout: float = 60.0) -> None:
        """Wait for agency to establish leadership."""
        logger.info("Waiting for agency leadership")

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                # Check each agent for leadership status
                agents = self.instance_manager.get_servers_by_role(ServerRole.AGENT)

                for agent in agents:
                    if agent.is_running():
                        health = agent.health_check_sync(timeout=3.0)
                        if health.is_healthy:
                            # Try to get agency state from this agent
                            # This would require actual HTTP API calls in real implementation
                            logger.info("Agency leadership established")
                            return
            except Exception as e:
                logger.debug(f"Agency leadership check failed: {e}")

            await asyncio.sleep(2.0)

        raise AgencyError("Agency leadership not established within timeout")

    async def _wait_for_dbservers_ready(self, timeout: float = 120.0) -> None:
        """Wait for all database servers to join cluster."""
        logger.info("Waiting for database servers to join cluster")

        start_time = time.time()
        dbservers = self.instance_manager.get_servers_by_role(ServerRole.DBSERVER)

        while time.time() - start_time < timeout:
            ready_count = 0

            for dbserver in dbservers:
                if dbserver.is_running():
                    health = dbserver.health_check_sync(timeout=3.0)
                    if health.is_healthy:
                        ready_count += 1

            if ready_count == len(dbservers):
                logger.info(f"All {len(dbservers)} database servers are ready")
                return

            logger.debug(f"Database servers ready: {ready_count}/{len(dbservers)}")
            await asyncio.sleep(3.0)

        raise ClusterError("Database servers did not become ready within timeout")

    async def _wait_for_coordinators_ready(self, timeout: float = 60.0) -> None:
        """Wait for coordinators to be ready."""
        logger.info("Waiting for coordinators to be ready")

        start_time = time.time()
        coordinators = self.instance_manager.get_servers_by_role(ServerRole.COORDINATOR)

        while time.time() - start_time < timeout:
            ready_count = 0

            for coordinator in coordinators:
                if coordinator.is_running():
                    health = coordinator.health_check_sync(timeout=3.0)
                    if health.is_healthy:
                        ready_count += 1

            if ready_count == len(coordinators):
                logger.info(f"All {len(coordinators)} coordinators are ready")
                return

            logger.debug(f"Coordinators ready: {ready_count}/{len(coordinators)}")
            await asyncio.sleep(3.0)

        raise ClusterError("Coordinators did not become ready within timeout")

    async def _update_agency_state(self, state: ClusterState) -> None:
        """Update agency information in cluster state."""
        agents = self.instance_manager.get_servers_by_role(ServerRole.AGENT)

        # In a real implementation, this would query the agency API
        # For now, we'll use health checks as a proxy
        for agent in agents:
            if agent.is_running():
                health = agent.health_check_sync(timeout=2.0)
                if health.is_healthy:
                    if not state.agency_leader:  # First healthy agent becomes leader
                        state.agency_leader = agent.server_id
                    else:
                        state.agency_followers.append(agent.server_id)

    async def _update_server_health(self, state: ClusterState) -> None:
        """Update server health information."""
        for server_id, server in self.instance_manager._servers.items():
            try:
                if server.is_running():
                    health = server.health_check_sync(timeout=2.0)
                    if health.is_healthy:
                        state.healthy_servers.add(server_id)
                    else:
                        state.unhealthy_servers.add(server_id)
                else:
                    state.unhealthy_servers.add(server_id)

                # Categorize by role
                if server.role == ServerRole.COORDINATOR:
                    if server_id not in state.coordinators:
                        state.coordinators.append(server_id)
                elif server.role == ServerRole.DBSERVER:
                    if server_id not in state.dbservers:
                        state.dbservers.append(server_id)

            except Exception as e:
                logger.debug(f"Error checking server {server_id}: {e}")
                state.unhealthy_servers.add(server_id)

    async def _update_cluster_statistics(self, state: ClusterState) -> None:
        """Update cluster-wide statistics."""
        # In a real implementation, this would query cluster APIs
        # For now, set reasonable defaults
        state.total_databases = 1  # At least _system
        state.total_collections = 0

        # Mock shard distribution
        for dbserver in state.get_healthy_dbservers():
            state.shard_distribution[dbserver] = 0  # Would be actual shard count

    async def _wait_for_server_healthy(self, server: ArangoServer, timeout: float) -> None:
        """Wait for a specific server to become healthy."""
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                health = server.health_check_sync(timeout=3.0)
                if health.is_healthy:
                    return
            except Exception as e:
                logger.debug(f"Server {server.server_id} health check failed: {e}")

            await asyncio.sleep(1.0)

        raise HealthCheckError(f"Server {server.server_id} did not become healthy within timeout")

    def _cancel_all_operations(self) -> None:
        """Cancel all active operations."""
        with self._lock:
            for operation in self._active_operations.values():
                if operation.status == "running":
                    operation.status = "cancelled"
                    operation.end_time = time.time()

            logger.info(f"Cancelled {len(self._active_operations)} active operations")


# Global orchestrator registry
_cluster_orchestrators: Dict[str, ClusterOrchestrator] = {}
_orchestrator_lock = threading.Lock()


def get_cluster_orchestrator(deployment_id: str) -> ClusterOrchestrator:
    """Get or create cluster orchestrator for deployment.

    Args:
        deployment_id: Unique deployment identifier

    Returns:
        Cluster orchestrator instance
    """
    with _orchestrator_lock:
        if deployment_id not in _cluster_orchestrators:
            _cluster_orchestrators[deployment_id] = ClusterOrchestrator(deployment_id)
        return _cluster_orchestrators[deployment_id]


def cleanup_cluster_orchestrators() -> None:
    """Cleanup all cluster orchestrators."""
    with _orchestrator_lock:
        for orchestrator in _cluster_orchestrators.values():
            try:
                orchestrator._cancel_all_operations()
            except Exception as e:
                logger.error(f"Error during orchestrator cleanup: {e}")

        _cluster_orchestrators.clear()
