"""Cluster bootstrap and initialization logic for ArangoDB clusters."""

from typing import Dict, List, Tuple, Optional, Any
import time
import requests
from concurrent.futures import ThreadPoolExecutor
from ..core.types import ServerRole
from ..core.log import Logger
from ..core.errors import ServerStartupError, AgencyError, ClusterError
from .server import ArangoServer


class ClusterBootstrapper:
    """Handles cluster-specific bootstrap sequencing and agency initialization.
    
    This class encapsulates the complex logic required to:
    - Start cluster servers in correct order (agents -> dbservers -> coordinators)
    - Wait for agency consensus and leadership
    - Verify cluster readiness
    """

    def __init__(self, logger: Logger, executor: ThreadPoolExecutor) -> None:
        """Initialize cluster bootstrapper.
        
        Args:
            logger: Logger instance
            executor: Thread pool executor for parallel operations
        """
        self._logger = logger
        self._executor = executor

    def bootstrap_cluster(
        self,
        servers: Dict[str, ArangoServer],
        startup_order: List[str],
        timeout: float = 300.0,
    ) -> None:
        """Bootstrap a cluster deployment in proper sequence.
        
        This follows the required sequence:
        1. Start agents
        2. Wait for agency ready
        3. Start database servers
        4. Start coordinators
        5. Verify cluster ready
        
        Args:
            servers: Dictionary of server_id to ArangoServer instances
            startup_order: List to append server IDs in startup order
            timeout: Total timeout for bootstrap
            
        Raises:
            ServerStartupError: If server startup fails
            AgencyError: If agency doesn't become ready
            ClusterError: If cluster doesn't become ready
        """
        self._logger.info("Starting cluster bootstrap sequence")
        start_time = time.time()

        # 1. Start agents first
        self._start_servers_by_role(servers, ServerRole.AGENT, startup_order)

        # 2. Wait for agency to become ready
        elapsed = time.time() - start_time
        remaining = max(30.0, timeout - elapsed)
        self._logger.info("Waiting for agency to become ready...")
        self.wait_for_agency_ready(servers, timeout=remaining)
        self._logger.info("Agency is ready!")

        # 3. Start database servers
        elapsed = time.time() - start_time
        remaining = max(60.0, timeout - elapsed)
        self._start_servers_by_role(servers, ServerRole.DBSERVER, startup_order, timeout=remaining)

        # 4. Start coordinators
        elapsed = time.time() - start_time
        remaining = max(60.0, timeout - elapsed)
        self._start_servers_by_role(servers, ServerRole.COORDINATOR, startup_order, timeout=remaining)

        self._logger.info("All cluster servers started successfully")

        # 5. Final readiness check
        elapsed = time.time() - start_time
        remaining = max(60.0, timeout - elapsed)
        self._logger.info("Performing final cluster readiness check...")
        self.wait_for_cluster_ready(servers, timeout=remaining)
        self._logger.info("Cluster is fully ready!")

    def _start_servers_by_role(
        self,
        servers: Dict[str, ArangoServer],
        role: ServerRole,
        startup_order: List[str],
        timeout: float = 60.0,
    ) -> None:
        """Start all servers of a specific role in parallel.
        
        Args:
            servers: Dictionary of all servers
            role: Server role to start
            startup_order: List to append server IDs as they start
            timeout: Timeout for each server startup
            
        Raises:
            ServerStartupError: If any server fails to start
        """
        role_name = role.value
        servers_to_start = [
            (server_id, server)
            for server_id, server in servers.items()
            if server.role == role
        ]

        if not servers_to_start:
            self._logger.debug("No %s servers to start", role_name)
            return

        self._logger.info("Starting %d %s server(s)...", len(servers_to_start), role_name)

        # Start all servers of this role in parallel
        futures = []
        for server_id, server in servers_to_start:
            self._logger.info("Starting %s %s", role_name, server_id)
            future = self._executor.submit(server.start, timeout)
            futures.append((server_id, future))

        # Wait for all servers to complete startup
        for server_id, future in futures:
            try:
                future.result(timeout=timeout)
                startup_order.append(server_id)
                self._logger.info("%s %s started successfully", role_name.title(), server_id)
            except Exception as e:
                raise ServerStartupError(
                    f"Failed to start {role_name} {server_id}: {e}"
                ) from e

    def wait_for_agency_ready(
        self, servers: Dict[str, ArangoServer], timeout: float = 30.0
    ) -> None:
        """Wait for agency to achieve consensus and elect a leader.
        
        This implements the agency readiness detection similar to the JavaScript
        framework's detectAgencyAlive logic.
        
        Args:
            servers: Dictionary of all servers
            timeout: Maximum time to wait
            
        Raises:
            AgencyError: If agency doesn't become ready within timeout
        """
        agents = self._get_agents(servers)
        if not agents:
            raise AgencyError("No agent servers found")

        self._logger.info("Waiting for agency consensus among %d agents", len(agents))
        start_time = time.time()
        last_log_time = start_time

        while time.time() - start_time < timeout:
            have_leader, have_config, consensus_valid = self._analyze_agency_status(agents)

            # Log progress periodically
            if time.time() - last_log_time > 5.0:
                self._logger.debug(
                    "Agency status: leader=%d, config=%d, consensus=%s",
                    have_leader,
                    have_config,
                    consensus_valid,
                )
                last_log_time = time.time()

            # Check if agency is ready (like JS framework)
            if consensus_valid and have_leader >= len(agents) // 2 + 1:
                self._logger.info("Agency has elected a leader with consensus")
                return

            time.sleep(0.5)

        raise AgencyError(
            f"Agency did not become ready within {timeout}s. "
            f"Leader: {have_leader}/{len(agents)}, Config: {have_config}/{len(agents)}"
        )

    def wait_for_cluster_ready(
        self, servers: Dict[str, ArangoServer], timeout: float = 60.0
    ) -> None:
        """Wait for all cluster servers to be ready and responding.
        
        Args:
            servers: Dictionary of all servers
            timeout: Maximum time to wait
            
        Raises:
            ClusterError: If cluster doesn't become ready within timeout
        """
        self._logger.info("Waiting for cluster readiness")
        start_time = time.time()
        
        # Get coordinators for health checking
        coordinators = [
            (server_id, server)
            for server_id, server in servers.items()
            if server.role == ServerRole.COORDINATOR
        ]
        
        if not coordinators:
            raise ClusterError("No coordinator servers found")

        while time.time() - start_time < timeout:
            all_ready = True
            
            for server_id, server in coordinators:
                try:
                    # Check if coordinator can access cluster state
                    response = requests.get(
                        f"{server.endpoint}/_api/version",
                        timeout=5.0,
                    )
                    if response.status_code != 200:
                        all_ready = False
                        break
                except (requests.RequestException, OSError) as e:
                    self._logger.debug("Coordinator %s not ready: %s", server_id, e)
                    all_ready = False
                    break
            
            if all_ready:
                self._logger.info("All coordinators are ready")
                return
                
            time.sleep(1.0)
        
        raise ClusterError(f"Cluster did not become ready within {timeout}s")

    def _get_agents(
        self, servers: Dict[str, ArangoServer]
    ) -> List[Tuple[str, ArangoServer]]:
        """Get list of agent servers.
        
        Args:
            servers: Dictionary of all servers
            
        Returns:
            List of (server_id, server) tuples for agents
        """
        return [
            (server_id, server)
            for server_id, server in servers.items()
            if server.role == ServerRole.AGENT
        ]

    def _check_agent_config(
        self, server_id: str, server: ArangoServer
    ) -> Optional[Dict[str, Any]]:
        """Check configuration of a single agent.
        
        Args:
            server_id: Agent server ID
            server: Agent server instance
            
        Returns:
            Agent config dict if successful, None if agent not ready
        """
        try:
            self._logger.debug("Checking agent %s at %s", server_id, server.endpoint)
            response = requests.get(
                f"{server.endpoint}/_api/agency/config", timeout=2.0
            )
            self._logger.debug("Agent %s response: %s", server_id, response.status_code)

            if response.status_code == 200:
                config = response.json()
                self._logger.debug("Agent %s config keys: %s", server_id, list(config.keys()))
                return config

            self._logger.debug("Agent %s not ready: %s", server_id, response.status_code)
            return None
        except (requests.RequestException, OSError) as e:
            self._logger.debug("Agent %s not responding: %s", server_id, e)
            return None

    def _analyze_agency_status(
        self, agents: List[Tuple[str, ArangoServer]]
    ) -> Tuple[int, int, bool]:
        """Analyze agency status across all agents.
        
        Args:
            agents: List of (server_id, server) tuples for agents
            
        Returns:
            Tuple of (have_leader, have_config, consensus_valid)
        """
        have_config = 0
        have_leader = 0
        leader_id = None
        consensus_valid = True

        for server_id, server in agents:
            config = self._check_agent_config(server_id, server)
            if not config:
                continue

            # Check for leadership (like JS lastAcked check)
            if "lastAcked" in config:
                have_leader += 1
                self._logger.debug("Agent %s has leadership", server_id)

            # Check for configuration (like JS leaderId check)
            if "leaderId" in config and config["leaderId"] != "":
                have_config += 1
                self._logger.debug("Agent %s has leaderId: %s", server_id, config["leaderId"])

                if leader_id is None:
                    leader_id = config["leaderId"]
                elif leader_id != config["leaderId"]:
                    # Agents disagree on leader - reset
                    self._logger.debug(
                        "Agent %s disagrees on leader: %s vs %s",
                        server_id,
                        config["leaderId"],
                        leader_id,
                    )
                    consensus_valid = False
                    break

        return have_leader, have_config, consensus_valid

