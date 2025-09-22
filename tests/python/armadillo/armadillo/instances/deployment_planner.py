"""Deployment planning for ArangoDB multi-server setups."""

from typing import Optional, List, Protocol

from ..core.types import DeploymentMode, ServerRole, ServerConfig, ClusterConfig
from ..core.log import Logger
from ..utils.ports import PortAllocator
from ..utils.filesystem import server_dir
from .deployment_plan import DeploymentPlan


class DeploymentPlanner(Protocol):
    """Protocol for deployment planners to enable dependency injection."""

    def create_deployment_plan(self,
                             deployment_id: str,
                             mode: DeploymentMode,
                             cluster_config: Optional[ClusterConfig] = None) -> 'DeploymentPlan':
        """Create a deployment plan for the specified mode."""
        ...


class StandardDeploymentPlanner:
    """Creates deployment plans for ArangoDB server configurations."""

    def __init__(self,
                 port_allocator: PortAllocator,
                 logger: Logger) -> None:
        self._port_allocator = port_allocator
        self._logger = logger

    def create_deployment_plan(self,
                             deployment_id: str,
                             mode: DeploymentMode,
                             cluster_config: Optional[ClusterConfig] = None) -> 'DeploymentPlan':
        """Create deployment plan for the specified mode.

        Args:
            deployment_id: Unique identifier for this deployment
            mode: Deployment mode
            cluster_config: Cluster configuration (for cluster mode)

        Returns:
            Deployment plan with server configurations

        Raises:
            ValueError: If deployment mode is not supported
        """
        plan = DeploymentPlan(deployment_mode=mode)

        if mode == DeploymentMode.SINGLE_SERVER:
            self._plan_single_server(plan, deployment_id)
        elif mode == DeploymentMode.CLUSTER:
            self._plan_cluster(plan, deployment_id, cluster_config)
        else:
            raise ValueError(f"Unsupported deployment mode: {mode}")

        self._logger.info(
            "Created deployment plan: %s with %s servers", mode.value, len(plan.servers)
        )
        return plan

    def _plan_single_server(self, plan: 'DeploymentPlan', deployment_id: str) -> None:
        """Plan single server deployment."""
        port = self._port_allocator.allocate_port()
        server_config = ServerConfig(
            role=ServerRole.SINGLE,
            port=port,
            data_dir=server_dir(deployment_id) / "single" / "data",
            log_file=server_dir(deployment_id) / "single" / "arangod.log"
        )
        plan.servers.append(server_config)
        plan.coordination_endpoints.append(f"http://127.0.0.1:{port}")

    def _plan_cluster(self, plan: 'DeploymentPlan', deployment_id: str, 
                    cluster_config: Optional[ClusterConfig]) -> None:
        """Plan cluster deployment with agents, dbservers, and coordinators."""
        if not cluster_config:
            # Use default cluster configuration
            cluster_config = ClusterConfig()

        # Create agents first
        agent_endpoints = self._create_agents(plan, deployment_id, cluster_config)
        plan.agency_endpoints = agent_endpoints

        # Add agency endpoints to all agents (all endpoints, like JS framework)
        for server in plan.get_agents():
            server.args["agency.endpoint"] = agent_endpoints.copy()

        # Create database servers
        self._create_dbservers(plan, deployment_id, cluster_config, agent_endpoints)

        # Create coordinators
        coordinator_endpoints = self._create_coordinators(
            plan, deployment_id, cluster_config, agent_endpoints
        )
        plan.coordination_endpoints = coordinator_endpoints

    def _create_agents(self, plan: 'DeploymentPlan', deployment_id: str, 
                     cluster_config: ClusterConfig) -> List[str]:
        """Create agent server configurations."""
        agent_endpoints = []
        for i in range(cluster_config.agents):
            port = self._port_allocator.allocate_port()
            agent_config = ServerConfig(
                role=ServerRole.AGENT,
                port=port,
                data_dir=server_dir(deployment_id) / f"agent_{i}" / "data",
                log_file=server_dir(deployment_id) / f"agent_{i}" / "arangod.log",
                args={
                    "agency.activate": "true",
                    "agency.size": str(cluster_config.agents),
                    "agency.supervision": "true",
                    "server.authentication": "false",  # Start with auth disabled
                    "agency.my-address": f"tcp://127.0.0.1:{port}",
                }
            )
            plan.servers.append(agent_config)
            agent_endpoints.append(f"tcp://127.0.0.1:{port}")
        return agent_endpoints

    def _create_dbservers(self, plan: 'DeploymentPlan', deployment_id: str,
                        cluster_config: ClusterConfig, agent_endpoints: List[str]) -> None:
        """Create database server configurations."""
        for i in range(cluster_config.dbservers):
            port = self._port_allocator.allocate_port()
            dbserver_config = ServerConfig(
                role=ServerRole.DBSERVER,
                port=port,
                data_dir=server_dir(deployment_id) / f"dbserver_{i}" / "data",
                log_file=server_dir(deployment_id) / f"dbserver_{i}" / "arangod.log",
                args={
                    "cluster.my-role": "PRIMARY",
                    "cluster.my-address": f"tcp://127.0.0.1:{port}",
                    "cluster.agency-endpoint": agent_endpoints[0],
                    "server.authentication": "false",
                }
            )
            plan.servers.append(dbserver_config)

    def _create_coordinators(self, plan: 'DeploymentPlan', deployment_id: str, 
                           cluster_config: ClusterConfig, agent_endpoints: List[str]) -> List[str]:
        """Create coordinator server configurations."""
        coordinator_endpoints = []
        for i in range(cluster_config.coordinators):
            port = self._port_allocator.allocate_port()
            coordinator_config = ServerConfig(
                role=ServerRole.COORDINATOR,
                port=port,
                data_dir=server_dir(deployment_id) / f"coordinator_{i}" / "data",
                log_file=server_dir(deployment_id) / f"coordinator_{i}" / "arangod.log",
                args={
                    "cluster.my-role": "COORDINATOR",
                    "cluster.my-address": f"tcp://127.0.0.1:{port}",
                    "cluster.agency-endpoint": agent_endpoints[0],
                    "server.authentication": "false",
                    "foxx.force-update-on-startup": "true",  # Wait for Foxx services to be ready
                    "cluster.default-replication-factor": "2",
                }
            )
            plan.servers.append(coordinator_config)
            coordinator_endpoints.append(f"http://127.0.0.1:{port}")
        return coordinator_endpoints
