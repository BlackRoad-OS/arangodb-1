"""Server health checking functionality for ArangoDB instances."""

import time
import asyncio
from typing import Protocol, Optional
import aiohttp
from ..core.log import Logger
from ..core.value_objects import ServerId
from ..core.process import is_process_running
from ..core.types import HealthStatus, TimeoutConfig
from ..core.errors import HealthCheckError, NetworkError
from ..utils.auth import AuthProvider


class HealthChecker(Protocol):
    """Protocol for server health checkers to enable dependency injection."""

    def check_readiness(self, server_id: ServerId, endpoint: str) -> bool:
        """Check if server is ready to accept connections during startup."""

    def check_health(self, endpoint: str, timeout: float = 5.0) -> HealthStatus:
        """Perform comprehensive health check with detailed status."""


class ServerHealthChecker:
    """Handles health checking for ArangoDB server instances."""

    def __init__(
        self,
        logger: Logger,
        auth_provider: AuthProvider,
        timeout_config: Optional[TimeoutConfig] = None,
    ) -> None:
        self._logger = logger
        self._auth_provider = auth_provider
        self._timeout_config = timeout_config or TimeoutConfig()

    def check_readiness(self, server_id: ServerId, endpoint: str) -> bool:
        """Check if server is ready to accept connections during startup."""
        try:
            if not is_process_running(server_id):
                self._logger.debug(
                    "Readiness check failed for %s: Process not running", str(server_id)
                )
                return False
            health = self.check_health(
                endpoint, timeout=self._timeout_config.health_check_quick
            )
            if not health.is_healthy:
                self._logger.debug(
                    "Readiness check failed for %s: %s",
                    str(server_id),
                    health.error_message,
                )
            return health.is_healthy
        except (
            HealthCheckError,
            NetworkError,
            aiohttp.ClientError,
            OSError,
            Exception,
        ) as e:
            self._logger.debug(
                "Readiness check exception for %s: %s", str(server_id), e
            )
            return False

    def check_health(self, endpoint: str, timeout: float = 5.0) -> HealthStatus:
        """Perform comprehensive health check with detailed status."""
        start_time = time.time()
        try:
            return asyncio.run(self._async_health_check(endpoint, timeout))
        except (
            HealthCheckError,
            NetworkError,
            aiohttp.ClientError,
            OSError,
            Exception,
        ) as e:
            response_time = time.time() - start_time
            return HealthStatus(
                is_healthy=False,
                response_time=response_time,
                error_message=f"Health check error: {e}",
            )

    async def _async_health_check(self, endpoint: str, timeout: float) -> HealthStatus:
        """Async health check implementation."""
        start_time = time.time()
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=timeout)
            ) as session:
                headers = self._auth_provider.get_auth_headers()
                async with session.get(
                    f"{endpoint}/_api/version", headers=headers
                ) as response:
                    response_time = time.time() - start_time
                    if response.status == 200:
                        details = await response.json()
                        return HealthStatus(
                            is_healthy=True,
                            response_time=response_time,
                            details=details,
                        )

                    return HealthStatus(
                        is_healthy=False,
                        response_time=response_time,
                        error_message=f"HTTP {response.status}: {response.reason}",
                    )
        except asyncio.TimeoutError:
            response_time = time.time() - start_time
            return HealthStatus(
                is_healthy=False,
                response_time=response_time,
                error_message="Connection timeout",
            )
        except (aiohttp.ClientError, OSError) as e:
            response_time = time.time() - start_time
            return HealthStatus(
                is_healthy=False,
                response_time=response_time,
                error_message=f"Connection error: {e}",
            )
