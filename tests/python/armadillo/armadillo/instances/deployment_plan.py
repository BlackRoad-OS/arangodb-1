"""Deployment plan data structures for ArangoDB deployments."""

from dataclasses import dataclass, field
from typing import List

from ..core.types import DeploymentMode, ServerRole, ServerConfig


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
