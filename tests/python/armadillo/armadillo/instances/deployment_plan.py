"""Deployment plan data structures for ArangoDB deployments."""

from dataclasses import dataclass, field
from typing import List, Optional, Union

from ..core.types import ServerConfig, ServerRole
from ..core.value_objects import ServerId
from ..utils.filesystem import FilesystemService


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
    server_id: ServerId,
    port: int,
    filesystem: FilesystemService,
    server_args: Optional[dict] = None,
) -> SingleServerDeploymentPlan:
    """Create a single server deployment plan with default test configuration.

    Args:
        server_id: Unique server identifier
        port: Port number for the server
        filesystem: Filesystem service for path derivation
        server_args: Optional additional server arguments
    """
    args = server_args or {}
    args["server.authentication"] = "false"

    base_dir = filesystem.server_dir(str(server_id))
    server_config = ServerConfig(
        role=ServerRole.SINGLE,
        port=port,
        data_dir=base_dir / "data",
        log_file=base_dir / "arangod.log",
        args=args,
    )

    return SingleServerDeploymentPlan(server=server_config)
