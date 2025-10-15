"""Deployment plan data structures for ArangoDB deployments."""

from dataclasses import dataclass, field
from typing import List, Optional, Union

from ..core.types import ServerConfig, ServerRole
from ..utils.filesystem import server_dir


@dataclass
class SingleServerDeploymentPlan:
    """Plan for deploying a single ArangoDB server."""

    server: ServerConfig


@dataclass
class ClusterDeploymentPlan:
    """Plan for deploying an ArangoDB cluster with agents, dbservers, and coordinators."""

    servers: List[ServerConfig] = field(default_factory=list)
    agency_endpoints: List[str] = field(default_factory=list)
    coordination_endpoints: List[str] = field(default_factory=list)

    def get_agents(self) -> List[ServerConfig]:
        """Get agent server configurations."""
        return [s for s in self.servers if s.role == ServerRole.AGENT]

    def get_dbservers(self) -> List[ServerConfig]:
        """Get database server configurations."""
        return [s for s in self.servers if s.role == ServerRole.DBSERVER]

    def get_coordinators(self) -> List[ServerConfig]:
        """Get coordinator server configurations."""
        return [s for s in self.servers if s.role == ServerRole.COORDINATOR]


DeploymentPlan = Union[SingleServerDeploymentPlan, ClusterDeploymentPlan]


def create_single_server_plan(
    server_id: str, port: int, server_args: Optional[dict] = None
) -> SingleServerDeploymentPlan:
    """Create a single server deployment plan with default test configuration."""
    args = server_args or {}
    args["server.authentication"] = "false"

    server_config = ServerConfig(
        role=ServerRole.SINGLE,
        port=port,
        data_dir=server_dir(server_id) / "data",
        log_file=server_dir(server_id) / "arangod.log",
        args=args,
    )

    return SingleServerDeploymentPlan(server=server_config)
