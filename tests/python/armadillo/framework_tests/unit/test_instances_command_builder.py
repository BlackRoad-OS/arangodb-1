"""Unit tests for ServerCommandBuilder."""

import pytest
from pathlib import Path
from unittest.mock import Mock

from armadillo.core.types import ServerRole, ServerConfig
from armadillo.instances.command_builder import (
    ServerCommandBuilder,
    ServerCommandParams,
)


class TestServerCommandBuilder:
    """Test command building functionality."""

    def setup_method(self):
        """Set up test environment."""
        # Create mock config provider
        self.mock_config = Mock()
        self.mock_config.bin_dir = Path("/fake/build/bin")
        self.mock_config.work_dir = Path("/fake/work")

        # Create mock logger
        self.mock_logger = Mock()

        self.builder = ServerCommandBuilder(
            config_provider=self.mock_config, logger=self.mock_logger
        )

    @pytest.fixture
    def setup_repo_structure(self, tmp_path):
        """Set up fake repository structure for testing."""
        # Create fake repository structure
        repo_root = tmp_path / "fake_repo"
        repo_root.mkdir()

        # Create expected directories
        (repo_root / "js").mkdir()
        (repo_root / "etc").mkdir()

        # Update mock config to point to build directory
        build_dir = repo_root / "build"
        build_dir.mkdir()
        bin_dir = build_dir / "bin"
        bin_dir.mkdir()

        self.mock_config.bin_dir = bin_dir
        return repo_root

    def test_build_command_single_server(self, setup_repo_structure):
        """Test building command for single server."""
        params = ServerCommandParams(
            server_id="test_single",
            role=ServerRole.SINGLE,
            port=8529,
            data_dir=Path("/fake/data"),
            app_dir=Path("/fake/apps"),
        )
        command = self.builder.build_command(params)

        assert isinstance(command, list)
        assert len(command) > 0

        # Should contain arangod executable
        assert command[0].endswith("arangod")

        # Should contain configuration
        assert "--configuration" in command
        assert "etc/testing/arangod-single.conf" in command

        # Should contain TOP_DIR
        assert "--define" in command
        top_dir_idx = command.index("--define") + 1
        assert command[top_dir_idx].startswith("TOP_DIR=")

        # Should contain endpoint
        assert "--server.endpoint" in command
        endpoint_idx = command.index("--server.endpoint") + 1
        assert "8529" in command[endpoint_idx]

        # Should contain directories
        assert "--database.directory" in command
        assert "--javascript.app-path" in command

        # Single server specific
        assert "--server.storage-engine" in command
        assert "rocksdb" in command

    def test_build_command_agent_server(self, setup_repo_structure):
        """Test building command for agent server."""
        params = ServerCommandParams(
            server_id="test_agent",
            role=ServerRole.AGENT,
            port=8531,
            data_dir=Path("/fake/data"),
            app_dir=Path("/fake/apps"),
        )
        command = self.builder.build_command(params)

        # Should contain agent configuration
        assert "etc/testing/arangod-agent.conf" in command

        # Agent specific parameters
        assert "--agency.activate" in command
        assert "true" in command
        assert "--agency.size" in command
        assert "3" in command
        assert "--agency.supervision" in command

    def test_build_command_coordinator_server(self, setup_repo_structure):
        """Test building command for coordinator server."""
        params = ServerCommandParams(
            server_id="test_coord",
            role=ServerRole.COORDINATOR,
            port=8530,
            data_dir=Path("/fake/data"),
            app_dir=Path("/fake/apps"),
        )
        command = self.builder.build_command(params)

        # Should contain coordinator configuration
        assert "etc/testing/arangod-coordinator.conf" in command

        # Cluster specific parameters
        assert "--cluster.create-waits-for-sync-replication" in command
        assert "false" in command
        assert "--cluster.write-concern" in command
        assert "1" in command

    def test_build_command_dbserver(self, setup_repo_structure):
        """Test building command for dbserver."""
        params = ServerCommandParams(
            server_id="test_db",
            role=ServerRole.DBSERVER,
            port=8532,
            data_dir=Path("/fake/data"),
            app_dir=Path("/fake/apps"),
        )
        command = self.builder.build_command(params)

        # Should contain dbserver configuration
        assert "etc/testing/arangod-dbserver.conf" in command

        # Cluster specific parameters
        assert "--cluster.create-waits-for-sync-replication" in command
        assert "--cluster.write-concern" in command

    def test_build_command_with_custom_config(self, setup_repo_structure):
        """Test building command with custom server configuration."""
        custom_config = ServerConfig(
            role=ServerRole.SINGLE,
            port=8529,
            data_dir=Path("/fake/data"),
            log_file=Path("/fake/logs/arangod.log"),
            args={"log.level": "debug", "server.authentication": "false"},
        )

        params = ServerCommandParams(
            server_id="test_custom",
            role=ServerRole.SINGLE,
            port=8529,
            data_dir=Path("/fake/data"),
            app_dir=Path("/fake/apps"),
            config=custom_config,
        )
        command = self.builder.build_command(params)

        command_str = " ".join(command)

        # Should contain custom arguments
        assert "--log.level" in command_str
        assert "debug" in command_str
        assert "--server.authentication" in command_str
        assert "false" in command_str

    def test_get_repository_root_from_build_bin(self, setup_repo_structure):
        """Test repository root detection from build/bin directory."""
        repo_root = setup_repo_structure

        detected_root = self.builder.get_repository_root()
        assert detected_root == repo_root

    def test_get_repository_root_fallback_to_cwd(self, tmp_path):
        """Test repository root detection fallback to current directory."""
        # Mock config with non-existent bin_dir
        self.mock_config.bin_dir = None

        # Create fake repo structure in temp dir and change to it
        repo_dir = tmp_path / "repo_cwd_test"
        repo_dir.mkdir()
        (repo_dir / "js").mkdir()
        (repo_dir / "etc").mkdir()

        import os

        original_cwd = os.getcwd()
        try:
            os.chdir(str(repo_dir))
            detected_root = self.builder.get_repository_root()
            assert detected_root == repo_dir
        finally:
            os.chdir(original_cwd)

    def test_get_repository_root_search_parents(self, tmp_path):
        """Test repository root detection by searching parent directories."""
        # Mock config with non-existent bin_dir
        self.mock_config.bin_dir = None

        # Create nested structure: repo/deep/nested/current
        repo_dir = tmp_path / "repo_parent_test"
        repo_dir.mkdir()
        (repo_dir / "js").mkdir()
        (repo_dir / "etc").mkdir()

        nested_dir = repo_dir / "deep" / "nested" / "current"
        nested_dir.mkdir(parents=True)

        import os

        original_cwd = os.getcwd()
        try:
            os.chdir(str(nested_dir))
            detected_root = self.builder.get_repository_root()
            assert detected_root == repo_dir
        finally:
            os.chdir(original_cwd)

    def test_config_file_for_different_roles(self):
        """Test configuration file selection for different server roles."""
        assert (
            self.builder._get_config_file_for_role(ServerRole.SINGLE)
            == "etc/testing/arangod-single.conf"
        )
        assert (
            self.builder._get_config_file_for_role(ServerRole.AGENT)
            == "etc/testing/arangod-agent.conf"
        )
        assert (
            self.builder._get_config_file_for_role(ServerRole.COORDINATOR)
            == "etc/testing/arangod-coordinator.conf"
        )
        assert (
            self.builder._get_config_file_for_role(ServerRole.DBSERVER)
            == "etc/testing/arangod-dbserver.conf"
        )

    def test_logs_command_for_debugging(self, setup_repo_structure):
        """Test that command building logs the command for debugging."""
        params = ServerCommandParams(
            server_id="test_logging",
            role=ServerRole.SINGLE,
            port=8529,
            data_dir=Path("/fake/data"),
            app_dir=Path("/fake/apps"),
        )
        self.builder.build_command(params)

        # Should have called logger with command information
        self.mock_logger.info.assert_called()

        # Check specific log messages (now with lazy formatting)
        log_calls = self.mock_logger.info.call_args_list
        # Check for format string and args separately
        command_header_found = any(
            ">>> ARANGOD COMMAND FOR %s <<<" == call.args[0]
            and len(call.args) > 1
            and call.args[1] == "test_logging"
            for call in log_calls
        )
        command_footer_found = any(
            ">>> END ARANGOD COMMAND <<<" in call.args[0] for call in log_calls
        )
        command_line_found = any("Command: %s" == call.args[0] for call in log_calls)

        assert (
            command_header_found
        ), f"Expected command header not found in log calls: {[call.args for call in log_calls]}"
        assert (
            command_footer_found
        ), f"Expected command footer not found in log calls: {[call.args for call in log_calls]}"
        assert (
            command_line_found
        ), f"Expected command line not found in log calls: {[call.args for call in log_calls]}"

    def test_binary_path_fallback_when_no_bin_dir(self, setup_repo_structure):
        """Test fallback to 'arangod' in PATH when no bin_dir configured."""
        self.mock_config.bin_dir = None

        params = ServerCommandParams(
            server_id="test_fallback",
            role=ServerRole.SINGLE,
            port=8529,
            data_dir=Path("/fake/data"),
            app_dir=Path("/fake/apps"),
        )
        command = self.builder.build_command(params)

        # Should use 'arangod' directly (will likely fail in real usage)
        assert command[0] == "arangod"
