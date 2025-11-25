"""Factory for creating ArangoDB deployments.

Separates deployment creation logic from lifecycle management.
This factory handles server instantiation and configuration,
while DeploymentController manages lifecycle and health monitoring.
"""

from typing import Any, Dict, List, Optional, Union
from pathlib import Path

from ..core.types import ServerRole, ClusterConfig, ServerConfig
from ..core.context import ApplicationContext
from ..core.value_objects import ServerId, DeploymentId
from .server import ArangoServer
from .deployment import Deployment, SingleServerDeployment, ClusterDeployment
from .server_config_builder import ServerConfigBuilder


class DeploymentFactory:
    """Factory for creating ArangoDB deployments.

    Provides static methods for creating single server and cluster deployments.
    Handles all server instantiation, configuration, and topology setup.
    """

    @staticmethod
    def _build_server_args(
        app_context: ApplicationContext,
        custom_args: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Union[str, List[str], int, float, bool]]:
        """Build merged server arguments from defaults and custom args.

        Args:
            app_context: Application context with configuration
            custom_args: Optional custom arguments to merge

        Returns:
            Merged argument dictionary ready for ServerConfig
        """
        config_builder = ServerConfigBuilder(
            config_provider=app_context.config,
            logger=app_context.logger,
        )
        default_args = config_builder.build_server_args()

        # Add authentication default
        default_args["server.authentication"] = "false"

        # Merge with custom args (custom takes precedence)
        if custom_args:
            default_args.update(custom_args)

        return default_args

    @staticmethod
    def _create_server_config(
        role: ServerRole,
        port: int,
        data_dir: Path,
        args: Dict[str, Any],
    ) -> ServerConfig:
        """Create ServerConfig with the given parameters.

        Args:
            role: Server role
            port: Port number (0 for auto-allocation)
            data_dir: Data directory path
            args: Server arguments

        Returns:
            ServerConfig instance
        """
        return ServerConfig(
            role=role,
            port=port,
            data_dir=data_dir,
            log_file=data_dir.parent / "arangodb.log",
            args=args,
        )

    @staticmethod
    def _build_agent_args(
        base_args: Dict[str, Any],
        port: int,
        count: int,
        agency_endpoints: List[str],
    ) -> Dict[str, Any]:
        """Build agent-specific arguments from base args.

        Args:
            base_args: Base server arguments
            port: Agent port
            count: Total number of agents
            agency_endpoints: List of all agency endpoints

        Returns:
            Agent-specific arguments
        """
        args = dict(base_args)
        args["agency.activate"] = "true"
        args["agency.size"] = str(count)
        args["agency.supervision"] = "true"
        args["agency.my-address"] = f"tcp://127.0.0.1:{port}"
        args["agency.endpoint"] = agency_endpoints
        return args

    @staticmethod
    def _build_dbserver_args(
        base_args: Dict[str, Any],
        port: int,
        agency_endpoints: List[str],
    ) -> Dict[str, Any]:
        """Build dbserver-specific arguments from base args.

        Args:
            base_args: Base server arguments
            port: DBServer port
            agency_endpoints: Agency endpoints for cluster connection

        Returns:
            DBServer-specific arguments
        """
        args = dict(base_args)
        args["cluster.my-role"] = "PRIMARY"
        args["cluster.my-address"] = f"tcp://127.0.0.1:{port}"
        args["cluster.agency-endpoint"] = agency_endpoints[0]
        return args

    @staticmethod
    def _build_coordinator_args(
        base_args: Dict[str, Any],
        port: int,
        agency_endpoints: List[str],
    ) -> Dict[str, Any]:
        """Build coordinator-specific arguments from base args.

        Args:
            base_args: Base server arguments
            port: Coordinator port
            agency_endpoints: Agency endpoints for cluster connection

        Returns:
            Coordinator-specific arguments
        """
        args = dict(base_args)
        args["cluster.my-role"] = "COORDINATOR"
        args["cluster.my-address"] = f"tcp://127.0.0.1:{port}"
        args["cluster.agency-endpoint"] = agency_endpoints[0]
        args["foxx.force-update-on-startup"] = "true"
        args["cluster.default-replication-factor"] = "2"
        return args

    @staticmethod
    def _create_agents(
        deployment_id: DeploymentId,
        app_context: ApplicationContext,
        merged_args: Dict[str, Any],
        count: int,
    ) -> tuple[Dict[ServerId, ArangoServer], List[str]]:
        """Create agent servers and return servers dict with agency endpoints.

        Args:
            deployment_id: Deployment identifier
            app_context: Application context
            merged_args: Base server arguments
            count: Number of agents to create

        Returns:
            Tuple of (servers dict, agency endpoints list)
        """
        servers: Dict[ServerId, ArangoServer] = {}

        # Allocate ports for all agents first
        agent_ports = [app_context.port_allocator.allocate_port() for _ in range(count)]
        agency_endpoints = [f"tcp://127.0.0.1:{port}" for port in agent_ports]

        # Create agent servers
        for i, port in enumerate(agent_ports):
            server_id = ServerId(f"{deployment_id}-agent-{i}")
            agent_args = DeploymentFactory._build_agent_args(
                merged_args, port, count, agency_endpoints
            )

            config = DeploymentFactory._create_server_config(
                role=ServerRole.AGENT,
                port=port,
                data_dir=app_context.filesystem.server_dir(str(server_id)) / "data",
                args=agent_args,
            )
            server = ArangoServer.create_cluster_server(
                server_id, ServerRole.AGENT, port, app_context, config=config
            )
            servers[server_id] = server

        return servers, agency_endpoints

    @staticmethod
    def _create_dbservers(
        deployment_id: DeploymentId,
        app_context: ApplicationContext,
        merged_args: Dict[str, Any],
        count: int,
        agency_endpoints: List[str],
    ) -> Dict[ServerId, ArangoServer]:
        """Create database servers.

        Args:
            deployment_id: Deployment identifier
            app_context: Application context
            merged_args: Base server arguments
            count: Number of dbservers to create
            agency_endpoints: Agency endpoints for cluster connection

        Returns:
            Dictionary of dbserver instances
        """
        servers: Dict[ServerId, ArangoServer] = {}

        for i in range(count):
            server_id = ServerId(f"{deployment_id}-dbserver-{i}")
            port = app_context.port_allocator.allocate_port()
            dbserver_args = DeploymentFactory._build_dbserver_args(
                merged_args, port, agency_endpoints
            )

            config = DeploymentFactory._create_server_config(
                role=ServerRole.DBSERVER,
                port=port,
                data_dir=app_context.filesystem.server_dir(str(server_id)) / "data",
                args=dbserver_args,
            )
            server = ArangoServer.create_cluster_server(
                server_id, ServerRole.DBSERVER, port, app_context, config=config
            )
            servers[server_id] = server

        return servers

    @staticmethod
    def _create_coordinators(
        deployment_id: DeploymentId,
        app_context: ApplicationContext,
        merged_args: Dict[str, Any],
        count: int,
        agency_endpoints: List[str],
    ) -> Dict[ServerId, ArangoServer]:
        """Create coordinator servers.

        Args:
            deployment_id: Deployment identifier
            app_context: Application context
            merged_args: Base server arguments
            count: Number of coordinators to create
            agency_endpoints: Agency endpoints for cluster connection

        Returns:
            Dictionary of coordinator instances
        """
        servers: Dict[ServerId, ArangoServer] = {}

        for i in range(count):
            server_id = ServerId(f"{deployment_id}-coordinator-{i}")
            port = app_context.port_allocator.allocate_port()
            coordinator_args = DeploymentFactory._build_coordinator_args(
                merged_args, port, agency_endpoints
            )

            config = DeploymentFactory._create_server_config(
                role=ServerRole.COORDINATOR,
                port=port,
                data_dir=app_context.filesystem.server_dir(str(server_id)) / "data",
                args=coordinator_args,
            )
            server = ArangoServer.create_cluster_server(
                server_id, ServerRole.COORDINATOR, port, app_context, config=config
            )
            servers[server_id] = server

        return servers

    @staticmethod
    def create_single_server(
        deployment_id: DeploymentId,
        app_context: ApplicationContext,
        server_args: Optional[Dict[str, Any]] = None,
    ) -> Deployment:
        """Create single server deployment.

        Args:
            deployment_id: Unique identifier for this deployment
            app_context: Application context with dependencies
            server_args: Optional custom arguments to pass to ArangoDB server

        Returns:
            SingleServerDeployment ready to be controlled

        Example:
            >>> deployment = DeploymentFactory.create_single_server(
            ...     DeploymentId("test-pkg"), ctx
            ... )
        """
        merged_args = DeploymentFactory._build_server_args(app_context, server_args)
        config = DeploymentFactory._create_server_config(
            role=ServerRole.SINGLE,
            port=0,  # Will be auto-allocated
            data_dir=app_context.filesystem.server_dir(str(deployment_id)) / "data",
            args=merged_args,
        )

        server_id = ServerId(str(deployment_id))
        server = ArangoServer.create_single_server(
            server_id,
            app_context,
            config=config,
        )

        return SingleServerDeployment(deployment_id=deployment_id, server=server)

    @staticmethod
    def create_cluster(
        deployment_id: DeploymentId,
        app_context: ApplicationContext,
        cluster_config: ClusterConfig,
        server_args: Optional[Dict[str, Any]] = None,
    ) -> Deployment:
        """Create cluster deployment.

        Args:
            deployment_id: Unique identifier for this deployment
            app_context: Application context with dependencies
            cluster_config: Cluster topology (agents, dbservers, coordinators)
            server_args: Optional custom arguments to pass to all ArangoDB servers

        Returns:
            ClusterDeployment ready to be controlled

        Example:
            >>> config = ClusterConfig(agents=3, dbservers=2, coordinators=1)
            >>> deployment = DeploymentFactory.create_cluster(
            ...     DeploymentId("test-pkg"), ctx, config
            ... )
        """
        merged_args = DeploymentFactory._build_server_args(app_context, server_args)

        # Create agents and get agency endpoints
        agent_servers, agency_endpoints = DeploymentFactory._create_agents(
            deployment_id, app_context, merged_args, cluster_config.agents
        )

        dbserver_servers = DeploymentFactory._create_dbservers(
            deployment_id,
            app_context,
            merged_args,
            cluster_config.dbservers,
            agency_endpoints,
        )

        coordinator_servers = DeploymentFactory._create_coordinators(
            deployment_id,
            app_context,
            merged_args,
            cluster_config.coordinators,
            agency_endpoints,
        )

        # Combine all servers
        servers = {**agent_servers, **dbserver_servers, **coordinator_servers}

        return ClusterDeployment(deployment_id=deployment_id, servers=servers)
