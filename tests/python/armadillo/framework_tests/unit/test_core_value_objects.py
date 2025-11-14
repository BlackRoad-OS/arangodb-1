"""Unit tests for core value objects (ServerId, ServerContext, DeploymentId)."""

import pytest

from armadillo.core.value_objects import ServerId, ServerContext, DeploymentId
from armadillo.core.types import ServerRole


class TestServerId:
    """Tests for ServerId value object."""

    def test_create_valid_server_id(self) -> None:
        """Test creating valid server IDs."""
        server_id = ServerId("agent_0")
        assert server_id.value == "agent_0"
        assert str(server_id) == "agent_0"

    def test_create_server_id_with_hyphen(self) -> None:
        """Test server ID with hyphens."""
        server_id = ServerId("test-server-1")
        assert server_id.value == "test-server-1"

    def test_create_server_id_with_underscore(self) -> None:
        """Test server ID with underscores."""
        server_id = ServerId("dbserver_12")
        assert server_id.value == "dbserver_12"

    def test_server_id_empty_raises_error(self) -> None:
        """Test that empty server ID raises ValueError."""
        with pytest.raises(ValueError, match="ServerId cannot be empty"):
            ServerId("")

    def test_server_id_whitespace_only_raises_error(self) -> None:
        """Test that whitespace-only server ID raises ValueError."""
        with pytest.raises(ValueError, match="ServerId cannot be empty"):
            ServerId("   ")

    def test_server_id_invalid_characters_raises_error(self) -> None:
        """Test that invalid characters raise ValueError."""
        with pytest.raises(ValueError, match="ServerId must be alphanumeric"):
            ServerId("agent@0")

        with pytest.raises(ValueError, match="ServerId must be alphanumeric"):
            ServerId("server.test")

        with pytest.raises(ValueError, match="ServerId must be alphanumeric"):
            ServerId("test/server")

    def test_server_id_equality(self) -> None:
        """Test ServerId equality comparison."""
        id1 = ServerId("agent_0")
        id2 = ServerId("agent_0")
        id3 = ServerId("agent_1")

        assert id1 == id2
        assert id1 != id3
        assert id1 != "agent_0"  # Should not equal strings


class TestServerContext:
    """Tests for ServerContext value object."""

    def test_create_context_with_pid(self) -> None:
        """Test creating server context with PID."""
        server_id = ServerId("agent_0")
        context = ServerContext(
            server_id=server_id, role=ServerRole.AGENT, pid=12345, port=8529
        )

        assert context.server_id == server_id
        assert context.role == ServerRole.AGENT
        assert context.pid == 12345
        assert context.port == 8529

    def test_create_context_without_pid(self) -> None:
        """Test creating server context without PID (not running)."""
        server_id = ServerId("dbserver_1")
        context = ServerContext(
            server_id=server_id, role=ServerRole.DBSERVER, pid=None, port=8530
        )

        assert context.server_id == server_id
        assert context.role == ServerRole.DBSERVER
        assert context.pid is None
        assert context.port == 8530

    def test_context_str_with_pid(self) -> None:
        """Test string representation with PID."""
        context = ServerContext(
            server_id=ServerId("agent_0"),
            role=ServerRole.AGENT,
            pid=12345,
        )

        assert str(context) == "agent_0[pid:12345]"

    def test_context_str_without_pid(self) -> None:
        """Test string representation without PID."""
        context = ServerContext(
            server_id=ServerId("coordinator_2"),
            role=ServerRole.COORDINATOR,
            pid=None,
        )

        assert str(context) == "coordinator_2[not running]"

    def test_context_is_running_with_pid(self) -> None:
        """Test is_running() returns True when PID present."""
        context = ServerContext(
            server_id=ServerId("agent_0"),
            role=ServerRole.AGENT,
            pid=12345,
        )

        assert context.is_running() is True

    def test_context_is_running_without_pid(self) -> None:
        """Test is_running() returns False when no PID."""
        context = ServerContext(
            server_id=ServerId("agent_0"),
            role=ServerRole.AGENT,
            pid=None,
        )

        assert context.is_running() is False

    def test_context_role_helpers(self) -> None:
        """Test role helper methods."""
        agent_context = ServerContext(
            server_id=ServerId("agent_0"),
            role=ServerRole.AGENT,
        )
        assert agent_context.is_agent() is True
        assert agent_context.is_coordinator() is False
        assert agent_context.is_dbserver() is False
        assert agent_context.is_single() is False

        coordinator_context = ServerContext(
            server_id=ServerId("coordinator_0"),
            role=ServerRole.COORDINATOR,
        )
        assert coordinator_context.is_agent() is False
        assert coordinator_context.is_coordinator() is True
        assert coordinator_context.is_dbserver() is False
        assert coordinator_context.is_single() is False

        dbserver_context = ServerContext(
            server_id=ServerId("dbserver_1"),
            role=ServerRole.DBSERVER,
        )
        assert dbserver_context.is_agent() is False
        assert dbserver_context.is_coordinator() is False
        assert dbserver_context.is_dbserver() is True
        assert dbserver_context.is_single() is False

        single_context = ServerContext(
            server_id=ServerId("server_0"),
            role=ServerRole.SINGLE,
        )
        assert single_context.is_agent() is False
        assert single_context.is_coordinator() is False
        assert single_context.is_dbserver() is False
        assert single_context.is_single() is True


class TestServerIdIntegration:
    """Integration tests for ServerId usage patterns."""

    def test_server_context_in_log_message(self) -> None:
        """Test how ServerContext would be used in log messages."""
        context = ServerContext(
            server_id=ServerId("agent_0"),
            role=ServerRole.AGENT,
            pid=12345,
            port=8529,
        )

        # Simulate log message formatting
        log_msg = f"Server {context} started successfully"
        assert log_msg == "Server agent_0[pid:12345] started successfully"

        # Simulate crash log
        crash_msg = f"Server {context} crashed with exit code 139"
        assert crash_msg == "Server agent_0[pid:12345] crashed with exit code 139"


class TestDeploymentId:
    """Tests for DeploymentId value object."""

    def test_create_valid_deployment_id(self) -> None:
        """Test creating valid deployment IDs."""
        deployment_id = DeploymentId("test_deployment")
        assert deployment_id.value == "test_deployment"
        assert str(deployment_id) == "test_deployment"

    def test_create_deployment_id_with_hyphen(self) -> None:
        """Test deployment ID with hyphens."""
        deployment_id = DeploymentId("test-deployment-1")
        assert deployment_id.value == "test-deployment-1"

    def test_create_deployment_id_with_underscore(self) -> None:
        """Test deployment ID with underscores."""
        deployment_id = DeploymentId("cluster_func_abc123")
        assert deployment_id.value == "cluster_func_abc123"

    def test_deployment_id_empty_raises_error(self) -> None:
        """Test that empty deployment ID raises ValueError."""
        with pytest.raises(ValueError, match="DeploymentId cannot be empty"):
            DeploymentId("")

    def test_deployment_id_whitespace_only_raises_error(self) -> None:
        """Test that whitespace-only deployment ID raises ValueError."""
        with pytest.raises(ValueError, match="DeploymentId cannot be empty"):
            DeploymentId("   ")

    def test_deployment_id_invalid_characters_raises_error(self) -> None:
        """Test that invalid characters raise ValueError."""
        with pytest.raises(ValueError, match="DeploymentId must be alphanumeric"):
            DeploymentId("deployment@test")

        with pytest.raises(ValueError, match="DeploymentId must be alphanumeric"):
            DeploymentId("test.deployment")

        with pytest.raises(ValueError, match="DeploymentId must be alphanumeric"):
            DeploymentId("deploy/ment")

    def test_deployment_id_equality(self) -> None:
        """Test DeploymentId equality comparison."""
        id1 = DeploymentId("cluster_session")
        id2 = DeploymentId("cluster_session")
        id3 = DeploymentId("cluster_func")

        assert id1 == id2
        assert id1 != id3
        assert id1 != "cluster_session"  # Should not equal strings
