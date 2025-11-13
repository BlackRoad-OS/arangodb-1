"""Health monitoring for ArangoDB server instances."""

from typing import Dict, List, Tuple, Optional
import time
import requests
from ..core.types import HealthStatus, ServerStats, ServerRole, TimeoutConfig
from ..core.value_objects import ServerId
from ..core.log import Logger
from ..core.errors import HealthCheckError, NetworkError
from .server import ArangoServer


class HealthMonitor:
    """Monitors health and collects statistics from ArangoDB servers.

    This class is responsible for:
    - Checking individual server health
    - Aggregating deployment health
    - Collecting server statistics
    - Verifying server readiness
    """

    def __init__(
        self, logger: Logger, timeout_config: Optional[TimeoutConfig] = None
    ) -> None:
        """Initialize health monitor.

        Args:
            logger: Logger instance for health monitoring events
            timeout_config: Timeout configuration (uses defaults if None)
        """
        self._logger = logger
        self._timeouts = timeout_config or TimeoutConfig()

    def check_server_health(
        self, server: ArangoServer, timeout: Optional[float] = None
    ) -> HealthStatus:
        """Check health of a single server.

        Args:
            server: ArangoServer instance to check
            timeout: Timeout for health check in seconds (uses config default if None)

        Returns:
            HealthStatus with health information
        """
        actual_timeout = timeout or self._timeouts.health_check_default
        try:
            health = server.health_check_sync(timeout=actual_timeout)
            return health
        except (HealthCheckError, NetworkError, OSError, TimeoutError) as e:
            # Health checks should not crash monitoring - log and return unhealthy
            self._logger.warning(
                "Health check failed for server %s: %s", server.server_id, e
            )
            return HealthStatus(
                is_healthy=False,
                response_time=0.0,
                error_message=f"Health check failed: {e}",
            )
        except Exception as e:
            # Defensive catch-all for monitoring - unexpected errors should not crash
            self._logger.warning(
                "Unexpected error checking health for server %s: %s",
                server.server_id,
                e,
                exc_info=True,
            )
            return HealthStatus(
                is_healthy=False,
                response_time=0.0,
                error_message=f"Health check failed: {e}",
            )

    def check_deployment_health(
        self, servers: Dict[ServerId, ArangoServer], timeout: Optional[float] = None
    ) -> HealthStatus:
        """Check health of entire deployment.

        Args:
            servers: Dictionary of ServerId to ArangoServer instances
            timeout: Total timeout for all health checks (uses config default if None)

        Returns:
            Aggregated HealthStatus for the deployment
        """
        if not servers:
            return HealthStatus(
                is_healthy=False,
                response_time=0.0,
                error_message="No servers in deployment",
            )

        actual_timeout = timeout or (
            self._timeouts.health_check_extended * len(servers)
        )
        start_time = time.time()
        unhealthy_servers: List[ServerId] = []
        health_errors: List[str] = []
        per_server_timeout = actual_timeout / len(servers)

        for server_id, server in servers.items():
            elapsed = time.time() - start_time
            remaining_timeout = max(1.0, actual_timeout - elapsed)
            server_timeout = min(per_server_timeout, remaining_timeout)

            try:
                health = self.check_server_health(server, timeout=server_timeout)
                if not health.is_healthy:
                    unhealthy_servers.append(server_id)
                    if health.error_message:
                        health_errors.append(f"{server_id}: {health.error_message}")
            except (HealthCheckError, NetworkError, OSError, TimeoutError) as e:
                # Monitoring loop should continue even if individual checks fail
                unhealthy_servers.append(server_id)
                health_errors.append(f"{server_id}: {e}")
                self._logger.error("Health check error for server %s: %s", server_id, e)
            except Exception as e:
                # Defensive catch-all for monitoring loop
                unhealthy_servers.append(server_id)
                health_errors.append(f"{server_id}: {e}")
                self._logger.error(
                    "Unexpected health check error for server %s: %s",
                    server_id,
                    e,
                    exc_info=True,
                )

        elapsed_time = time.time() - start_time
        is_healthy = len(unhealthy_servers) == 0

        if is_healthy:
            return HealthStatus(
                is_healthy=True,
                response_time=elapsed_time,
            )

        error_msg = (
            f"{len(unhealthy_servers)}/{len(servers)} servers unhealthy: "
            f"{', '.join(str(sid) for sid in unhealthy_servers)}"
        )
        if health_errors:
            error_msg += f". Errors: {'; '.join(health_errors[:3])}"
        return HealthStatus(
            is_healthy=False,
            error_message=error_msg,
            response_time=elapsed_time,
        )

    def collect_server_stats(self, server: ArangoServer) -> Optional[ServerStats]:
        """Collect statistics from a single server.

        Args:
            server: ArangoServer instance

        Returns:
            ServerStats or None if collection failed
        """
        try:
            return server.get_stats_sync()
        except (OSError, RuntimeError, ValueError) as e:
            # Stats collection should not crash monitoring - log and return None
            self._logger.warning(
                "Failed to collect stats for server %s: %s", server.server_id, e
            )
            return None
        except Exception as e:
            # Defensive catch-all for stats collection
            self._logger.warning(
                "Unexpected error collecting stats for server %s: %s",
                server.server_id,
                e,
                exc_info=True,
            )
            return None

    def collect_deployment_stats(
        self, servers: Dict[ServerId, ArangoServer]
    ) -> Dict[ServerId, ServerStats]:
        """Collect statistics from all servers in deployment.

        Args:
            servers: Dictionary of ServerId to ArangoServer instances

        Returns:
            Dictionary mapping ServerId to their stats
        """
        stats: Dict[ServerId, ServerStats] = {}
        for server_id, server in servers.items():
            server_stats = self.collect_server_stats(server)
            if server_stats:
                stats[server_id] = server_stats
        return stats

    def check_server_readiness(
        self, server: ArangoServer, timeout: Optional[float] = None
    ) -> Tuple[bool, Optional[str]]:
        """Check if a server is ready to accept requests.

        This checks the appropriate readiness endpoint based on server role.

        Args:
            server: ArangoServer instance
            timeout: Timeout for readiness check (uses config default if None)

        Returns:
            Tuple of (is_ready, error_message)
        """
        actual_timeout = timeout or self._timeouts.health_check_default
        endpoint, path = self._get_readiness_endpoint(server)

        try:
            response = requests.get(
                f"{endpoint}{path}",
                timeout=actual_timeout,
                auth=server.auth if hasattr(server, "auth") else None,
            )

            if response.status_code == 200:
                return True, None
            if self._is_service_api_disabled_error(response):
                # Service API disabled but server is running - consider it ready
                self._logger.debug(
                    "Server %s has service API disabled, checking health instead",
                    server.server_id,
                )
                health = self.check_server_health(server, timeout=actual_timeout)
                return health.is_healthy, health.error_message

            return False, f"Unexpected status code: {response.status_code}"

        except requests.RequestException as e:
            return False, f"Request failed: {e}"
        except (OSError, TimeoutError, ValueError) as e:
            # Readiness check should not crash - return failure status
            return False, f"Readiness check failed: {e}"

    def _get_readiness_endpoint(self, server: ArangoServer) -> Tuple[str, str]:
        """Get the appropriate readiness check endpoint for a server.

        Args:
            server: ArangoServer instance

        Returns:
            Tuple of (base_endpoint, path)
        """
        endpoint = server.get_endpoint()

        # Use role-appropriate endpoints
        if server.role in (ServerRole.COORDINATOR, ServerRole.SINGLE):
            # Coordinators and single servers: check version endpoint
            return endpoint, "/_api/version"
        if server.role == ServerRole.AGENT:
            # Agents: check agency store
            return endpoint, "/_api/agency/read"

        # DBServers: check admin status
        return endpoint, "/_admin/status"

    def _is_service_api_disabled_error(self, response: requests.Response) -> bool:
        """Check if response indicates service API is disabled.

        Args:
            response: HTTP response object

        Returns:
            True if service API is disabled, False otherwise
        """
        if response.status_code != 403:
            return False

        try:
            data = response.json()
            return (
                data.get("errorNum") == 11
                and "service api" in data.get("errorMessage", "").lower()
            )
        except (ValueError, KeyError):
            return False

    def verify_deployment_ready(
        self, servers: Dict[ServerId, ArangoServer], timeout: Optional[float] = None
    ) -> None:
        """Verify all servers in deployment are ready.

        Args:
            servers: Dictionary of ServerId to ArangoServer instances
            timeout: Total timeout for verification (uses config default if None)

        Raises:
            HealthCheckError: If servers are not ready within timeout
        """
        actual_timeout = timeout or (
            self._timeouts.health_check_extended * len(servers)
        )
        start_time = time.time()
        not_ready: List[str] = []

        for server_id, server in servers.items():
            elapsed = time.time() - start_time
            remaining = max(5.0, actual_timeout - elapsed)

            is_ready, error = self.check_server_readiness(server, timeout=remaining)
            if not is_ready:
                not_ready.append(f"{server_id}: {error or 'unknown'}")

        if not_ready:
            raise HealthCheckError(f"Servers not ready: {', '.join(not_ready)}")

        self._logger.info("All %d servers verified ready", len(servers))
