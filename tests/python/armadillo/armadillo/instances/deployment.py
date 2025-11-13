"""Deployment domain types representing complete deployments."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from ..core.value_objects import ServerId
from ..core.types import ServerRole
from .server import ArangoServer
from .deployment_plan import (
    DeploymentPlan,
    SingleServerDeploymentPlan,
    ClusterDeploymentPlan,
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
class Deployment(ABC):
    """Base class for deployments.

    Provides common fields and methods that work for both single server and cluster.
    The abstract get_servers() method provides a unified interface, eliminating
    the need for special cases in calling code.
    """

    @abstractmethod
    def get_servers(self) -> Dict[ServerId, ArangoServer]:
        """Get all servers as a dictionary.

        This method provides a unified interface - all calling code can use
        .values(), .items(), .keys(), etc. without special cases.

        Returns:
            Dictionary mapping server IDs to server instances
        """
        pass

    def get_server(self, server_id: ServerId) -> Optional[ArangoServer]:
        """Get a single server by ID."""
        return self.get_servers().get(server_id)

    def get_servers_by_role(self, role: ServerRole) -> List[ArangoServer]:
        """Get all servers with the specified role."""
        return [s for s in self.get_servers().values() if s.role == role]

    def get_server_count(self) -> int:
        """Get total number of servers."""
        return len(self.get_servers())

    def is_empty(self) -> bool:
        """Check if deployment has no servers."""
        return self.get_server_count() == 0

    @abstractmethod
    def mark_deployed(self, startup_time: float) -> None:
        """Mark deployment as deployed with startup time.

        Args:
            startup_time: Timestamp when deployment completed
        """
        pass

    @abstractmethod
    def mark_shutdown(self, shutdown_time: float) -> None:
        """Mark deployment as shut down with shutdown time.

        Args:
            shutdown_time: Timestamp when shutdown completed
        """
        pass

    @abstractmethod
    def mark_healthy(self, is_healthy: bool) -> None:
        """Update deployment health status.

        Args:
            is_healthy: Whether deployment is healthy
        """
        pass

    @abstractmethod
    def get_status(self) -> "DeploymentStatus":
        """Get deployment status.

        Returns:
            DeploymentStatus object
        """
        pass

    @abstractmethod
    def get_timing(self) -> "DeploymentTiming":
        """Get deployment timing information.

        Returns:
            DeploymentTiming object
        """
        pass

    def is_deployed(self) -> bool:
        """Check if deployment is currently deployed.

        Returns:
            True if deployment is active, False otherwise
        """
        return self.get_status().is_deployed

    def is_healthy(self) -> bool:
        """Check if deployment is healthy.

        Returns:
            True if deployment is healthy, False otherwise
        """
        return self.get_status().is_healthy

    @abstractmethod
    def get_deployment_mode(self) -> str:
        """Get deployment mode identifier.

        Returns:
            Deployment mode string ("single_server" or "cluster")
        """
        pass

    @abstractmethod
    def get_agency_endpoints(self) -> List[str]:
        """Get agency endpoints.

        Returns:
            List of agency endpoints (empty for single server deployments)
        """
        pass

    @abstractmethod
    def get_coordination_endpoints(self) -> List[str]:
        """Get coordination endpoints (coordinators or single server).

        Returns:
            List of coordination endpoints
        """
        pass

    @abstractmethod
    def get_plan(self) -> DeploymentPlan:
        """Get the deployment plan used to create this deployment.

        Returns:
            The deployment plan (SingleServerDeploymentPlan or ClusterDeploymentPlan)
        """
        pass


@dataclass
class SingleServerDeployment(Deployment):
    """Single server deployment.

    Enforces that only one server can exist - stored as a single object, not a dict.
    This provides type safety: you cannot accidentally have multiple servers.
    """

    plan: SingleServerDeploymentPlan
    server: ArangoServer  # Single server object, not dict - enforces constraint
    status: DeploymentStatus = field(default_factory=DeploymentStatus)
    timing: DeploymentTiming = field(default_factory=DeploymentTiming)

    def get_servers(self) -> Dict[ServerId, ArangoServer]:
        """Get servers as dict (wraps single server for unified interface)."""
        return {self.server.server_id: self.server}

    def get_coordination_endpoints(self) -> List[str]:
        """Get coordination endpoint (single server endpoint)."""
        return [self.server.endpoint]

    def get_deployment_mode(self) -> str:
        """Get deployment mode identifier."""
        return "single_server"

    def get_agency_endpoints(self) -> List[str]:
        """Get agency endpoints (empty for single server)."""
        return []

    def get_plan(self) -> SingleServerDeploymentPlan:
        """Get the deployment plan."""
        return self.plan

    def mark_deployed(self, startup_time: float) -> None:
        """Mark deployment as deployed with startup time."""
        self.status.is_deployed = True
        self.timing.startup_time = startup_time

    def mark_shutdown(self, shutdown_time: float) -> None:
        """Mark deployment as shut down with shutdown time."""
        self.status.is_deployed = False
        self.status.is_healthy = False
        self.timing.shutdown_time = shutdown_time

    def mark_healthy(self, is_healthy: bool) -> None:
        """Update deployment health status."""
        self.status.is_healthy = is_healthy

    def get_status(self) -> "DeploymentStatus":
        """Get deployment status."""
        return self.status

    def get_timing(self) -> "DeploymentTiming":
        """Get deployment timing information."""
        return self.timing


@dataclass
class ClusterDeployment(Deployment):
    """Cluster deployment with multiple servers."""

    plan: ClusterDeploymentPlan
    servers: Dict[ServerId, ArangoServer] = field(default_factory=dict)
    status: DeploymentStatus = field(default_factory=DeploymentStatus)
    timing: DeploymentTiming = field(default_factory=DeploymentTiming)

    def get_servers(self) -> Dict[ServerId, ArangoServer]:
        """Get all servers."""
        return self.servers

    def get_coordination_endpoints(self) -> List[str]:
        """Get coordinator endpoints."""
        return self.plan.coordination_endpoints

    def get_deployment_mode(self) -> str:
        """Get deployment mode identifier."""
        return "cluster"

    def get_agency_endpoints(self) -> List[str]:
        """Get agency endpoints."""
        return self.plan.agency_endpoints

    def get_plan(self) -> ClusterDeploymentPlan:
        """Get the deployment plan."""
        return self.plan

    def mark_deployed(self, startup_time: float) -> None:
        """Mark deployment as deployed with startup time."""
        self.status.is_deployed = True
        self.timing.startup_time = startup_time

    def mark_shutdown(self, shutdown_time: float) -> None:
        """Mark deployment as shut down with shutdown time."""
        self.status.is_deployed = False
        self.status.is_healthy = False
        self.timing.shutdown_time = shutdown_time

    def mark_healthy(self, is_healthy: bool) -> None:
        """Update deployment health status."""
        self.status.is_healthy = is_healthy

    def get_status(self) -> "DeploymentStatus":
        """Get deployment status."""
        return self.status

    def get_timing(self) -> "DeploymentTiming":
        """Get deployment timing information."""
        return self.timing
