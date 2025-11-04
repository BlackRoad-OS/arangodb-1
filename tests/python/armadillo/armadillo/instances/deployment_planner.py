"""Deployment planning for ArangoDB single server and cluster setups."""

from typing import Optional, List

from ..core.types import ServerRole, ServerConfig, ClusterConfig
from ..core.value_objects import ServerId, DeploymentId
from ..core.log import Logger
from ..core.config import ConfigProvider
from ..utils.ports import PortAllocator
from ..utils.filesystem import FilesystemService
from .deployment_plan import SingleServerDeploymentPlan, ClusterDeploymentPlan
from .server_config_builder import ServerConfigBuilder


class DeploymentPlanner:
    """Creates deployment plans for both single server and cluster configurations."""

    def __init__(
        self,
        port_allocator: PortAllocator,
        logger: Logger,
        config_provider: ConfigProvider,
        filesystem: FilesystemService,
    ) -> None:
        self._port_allocator = port_allocator
        self._logger = logger
        self._config_provider = config_provider
        self._filesystem = filesystem
        self._server_config_builder = ServerConfigBuilder(config_provider, logger)

    def create_single_server_plan(
        self, server_id: ServerId, server_args: Optional[dict] = None
    ) -> SingleServerDeploymentPlan:
        """Create a deployment plan for a single server."""
        args = server_args or {}

        # Use server config builder for consistent configuration
        server_config_args = self._server_config_builder.build_server_args()
        args.update(server_config_args)
        args["server.authentication"] = "false"

        port = self._port_allocator.allocate_port()

        server_config = ServerConfig(
            role=ServerRole.SINGLE,
            port=port,
            data_dir=self._filesystem.server_dir(str(server_id)) / "data",
            log_file=self._filesystem.server_dir(str(server_id)) / "arangod.log",
            args=args,
        )

        self._logger.info("Created single server plan on port %d", port)
        return SingleServerDeploymentPlan(server=server_config)

    def create_cluster_plan(
        self,
        deployment_id: DeploymentId,
        cluster_config: Optional[ClusterConfig] = None,
    ) -> ClusterDeploymentPlan:
        """Create deployment plan for cluster mode."""
        plan = ClusterDeploymentPlan()
        self._plan_cluster(plan, deployment_id, cluster_config)

        self._logger.info(
            "Created cluster plan: %d agents, %d dbservers, %d coordinators",
            len(plan.get_agents()),
            len(plan.get_dbservers()),
            len(plan.get_coordinators()),
        )

        return plan

    def _configure_server_logging(self, args: dict) -> None:
        """Configure server logging arguments based on framework verbose mode."""
        server_args = self._server_config_builder.build_server_args()
        args.update(server_args)

    def _plan_cluster(
        self,
        plan: ClusterDeploymentPlan,
        deployment_id: DeploymentId,
        cluster_config: Optional[ClusterConfig],
    ) -> None:
        """Plan cluster deployment with agents, dbservers, and coordinators."""
        if not cluster_config:
            # Use default cluster configuration
            cluster_config = ClusterConfig()

        # Create agents first
        agent_endpoints = self._create_agents(plan, deployment_id, cluster_config)
        plan.agency_endpoints = agent_endpoints

        # Add agency endpoints to all agents (all endpoints, like JS framework)
        for server in plan.servers:
            if server.role == ServerRole.AGENT:
                server.args["agency.endpoint"] = agent_endpoints.copy()

        # Create database servers
        self._create_dbservers(plan, deployment_id, cluster_config, agent_endpoints)

        # Create coordinators
        coordinator_endpoints = self._create_coordinators(
            plan, deployment_id, cluster_config, agent_endpoints
        )
        plan.coordination_endpoints = coordinator_endpoints

    def _create_agents(
        self,
        plan: ClusterDeploymentPlan,
        deployment_id: DeploymentId,
        cluster_config: ClusterConfig,
    ) -> List[str]:
        """Create agent server configurations."""
        agent_endpoints = []
        for i in range(cluster_config.agents):
            port = self._port_allocator.allocate_port()

            # Configure server arguments including logging
            args = {
                "agency.activate": "true",
                "agency.size": str(cluster_config.agents),
                "agency.supervision": "true",
                "server.authentication": "false",  # Start with auth disabled
                "agency.my-address": f"tcp://127.0.0.1:{port}",
            }
            self._configure_server_logging(args)

            agent_config = ServerConfig(
                role=ServerRole.AGENT,
                port=port,
                data_dir=self._filesystem.server_dir(str(deployment_id))
                / f"agent_{i}"
                / "data",
                log_file=self._filesystem.server_dir(str(deployment_id))
                / f"agent_{i}"
                / "arangod.log",
                args=args,
            )
            plan.servers.append(agent_config)
            agent_endpoints.append(f"tcp://127.0.0.1:{port}")
        return agent_endpoints

    def _create_dbservers(
        self,
        plan: ClusterDeploymentPlan,
        deployment_id: DeploymentId,
        cluster_config: ClusterConfig,
        agent_endpoints: List[str],
    ) -> None:
        """Create database server configurations."""
        for i in range(cluster_config.dbservers):
            port = self._port_allocator.allocate_port()

            # Configure server arguments including logging
            args = {
                "cluster.my-role": "PRIMARY",
                "cluster.my-address": f"tcp://127.0.0.1:{port}",
                "cluster.agency-endpoint": agent_endpoints[0],
                "server.authentication": "false",
            }
            self._configure_server_logging(args)

            dbserver_config = ServerConfig(
                role=ServerRole.DBSERVER,
                port=port,
                data_dir=self._filesystem.server_dir(str(deployment_id))
                / f"dbserver_{i}"
                / "data",
                log_file=self._filesystem.server_dir(str(deployment_id))
                / f"dbserver_{i}"
                / "arangod.log",
                args=args,
            )
            plan.servers.append(dbserver_config)

    def _create_coordinators(
        self,
        plan: ClusterDeploymentPlan,
        deployment_id: DeploymentId,
        cluster_config: ClusterConfig,
        agent_endpoints: List[str],
    ) -> List[str]:
        """Create coordinator server configurations."""
        coordinator_endpoints = []
        for i in range(cluster_config.coordinators):
            port = self._port_allocator.allocate_port()

            # Configure server arguments including logging
            args = {
                "cluster.my-role": "COORDINATOR",
                "cluster.my-address": f"tcp://127.0.0.1:{port}",
                "cluster.agency-endpoint": agent_endpoints[0],
                "server.authentication": "false",
                "foxx.force-update-on-startup": "true",  # Wait for Foxx services to be ready
                "cluster.default-replication-factor": "2",
            }
            self._configure_server_logging(args)

            coordinator_config = ServerConfig(
                role=ServerRole.COORDINATOR,
                port=port,
                data_dir=self._filesystem.server_dir(str(deployment_id))
                / f"coordinator_{i}"
                / "data",
                log_file=self._filesystem.server_dir(str(deployment_id))
                / f"coordinator_{i}"
                / "arangod.log",
                args=args,
            )
            plan.servers.append(coordinator_config)
            coordinator_endpoints.append(f"http://127.0.0.1:{port}")
        return coordinator_endpoints
