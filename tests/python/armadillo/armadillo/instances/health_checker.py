"""Server health checking functionality for ArangoDB instances."""

import time
import asyncio
from typing import Protocol

import aiohttp

from ..core.log import Logger
from ..core.process import is_process_running
from ..core.types import HealthStatus
from ..utils.auth import AuthProvider


class HealthChecker(Protocol):
    """Protocol for server health checkers to enable dependency injection."""

    def check_readiness(self, server_id: str, endpoint: str) -> bool:
        """Check if server is ready to accept connections during startup."""
        ...

    def check_health(self, endpoint: str, timeout: float = 5.0) -> HealthStatus:
        """Perform comprehensive health check with detailed status."""
        ...


class ServerHealthChecker:
    """Handles health checking for ArangoDB server instances."""

    def __init__(self,
                 logger: Logger,
                 auth_provider: AuthProvider) -> None:
        self._logger = logger
        self._auth_provider = auth_provider

    def check_readiness(self, server_id: str, endpoint: str) -> bool:
        """Check if server is ready to accept connections during startup."""
        try:
            # During startup, check if the process is running via supervisor
            # and test HTTP connection without circular dependencies
            if not is_process_running(server_id):
                self._logger.debug(f"Readiness check failed for {server_id}: Process not running")
                return False

            # Make direct HTTP health check with short timeout for startup
            health = self.check_health(endpoint, timeout=2.0)
            if not health.is_healthy:
                self._logger.debug(f"Readiness check failed for {server_id}: {health.error_message}")
            return health.is_healthy
        except Exception as e:
            self._logger.debug(f"Readiness check exception for {server_id}: {e}")
            return False

    def check_health(self, endpoint: str, timeout: float = 5.0) -> HealthStatus:
        """Perform comprehensive health check with detailed status."""
        start_time = time.time()

        try:
            # Use asyncio.run to make direct HTTP request
            return asyncio.run(self._async_health_check(endpoint, timeout))
        except Exception as e:
            response_time = time.time() - start_time
            return HealthStatus(
                is_healthy=False,
                response_time=response_time,
                error_message=f"Health check error: {e}"
            )

    async def _async_health_check(self, endpoint: str, timeout: float) -> HealthStatus:
        """Async health check implementation."""
        start_time = time.time()

        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
                headers = self._auth_provider.get_auth_headers()

                async with session.get(f"{endpoint}/_api/version", headers=headers) as response:
                    response_time = time.time() - start_time

                    if response.status == 200:
                        details = await response.json()
                        return HealthStatus(
                            is_healthy=True,
                            response_time=response_time,
                            details=details
                        )
                    else:
                        return HealthStatus(
                            is_healthy=False,
                            response_time=response_time,
                            error_message=f"HTTP {response.status}: {response.reason}"
                        )

        except asyncio.TimeoutError:
            response_time = time.time() - start_time
            return HealthStatus(
                is_healthy=False,
                response_time=response_time,
                error_message="Connection timeout"
            )
        except Exception as e:
            response_time = time.time() - start_time
            return HealthStatus(
                is_healthy=False,
                response_time=response_time,
                error_message=f"Connection error: {e}"
            )
