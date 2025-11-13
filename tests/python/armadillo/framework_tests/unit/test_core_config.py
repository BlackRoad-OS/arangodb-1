"""Tests for configuration management."""

import pytest
import os
from pathlib import Path
from unittest.mock import patch, mock_open

from armadillo.core.config import (
    ConfigManager,
    load_config,
    get_config,
    load_env_overrides,
    _convert_env_value,
)
from armadillo.core.types import (
    ArmadilloConfig,
    DeploymentMode,
    ClusterConfig,
    TimeoutConfig,
)
from armadillo.core.errors import ConfigurationError, PathError


class TestEnvironmentLoading:
    """Test environment variable loading functions."""

    @patch.dict(
        os.environ,
        {
            "ARMADILLO_DEPLOYMENT_MODE": "cluster",
            "ARMADILLO_TEST_TIMEOUT": "1200.0",
            "ARMADILLO_VERBOSE": "2",
            "ARMADILLO_CLUSTER__AGENTS": "5",
        },
        clear=True,
    )
    def test_load_env_overrides(self) -> None:
        """Test loading environment variable overrides."""
        overrides = load_env_overrides()

        assert overrides["deployment_mode"] == "cluster"
        assert overrides["test_timeout"] == 1200.0
        assert overrides["verbose"] == 2
        assert overrides["cluster"]["agents"] == 5

    def test_convert_env_value_boolean(self) -> None:
        """Test boolean conversion from environment values."""
        assert _convert_env_value("true") is True
        assert _convert_env_value("false") is False
        assert _convert_env_value("yes") is True
        assert _convert_env_value("no") is False

    def test_convert_env_value_integer(self) -> None:
        """Test integer conversion from environment values."""
        assert _convert_env_value("1") == 1
        assert _convert_env_value("0") == 0
        assert _convert_env_value("42") == 42

    def test_convert_env_value_numeric(self) -> None:
        """Test numeric conversion from environment values."""
        assert _convert_env_value("42") == 42
        assert _convert_env_value("3.14") == 3.14

    def test_convert_env_value_list(self) -> None:
        """Test list conversion from environment values."""
        result = _convert_env_value("a,b,c")
        assert result == ["a", "b", "c"]

    def test_convert_env_value_string(self) -> None:
        """Test string values are returned as-is."""
        assert _convert_env_value("test_string") == "test_string"


class TestConfigManager:
    """Test ConfigManager class."""

    def test_config_manager_creation(self) -> None:
        """Test ConfigManager creation."""
        manager = ConfigManager()
        assert manager._config is None

    def test_load_config_with_overrides(self) -> None:
        """Test configuration loading with CLI overrides."""
        manager = ConfigManager()

        overrides = {
            "deployment_mode": DeploymentMode.CLUSTER,
            "test_timeout": 600.0,
            "verbose": 1,
        }

        with patch("armadillo.core.config.load_env_overrides", return_value={}):
            config = manager.load_config(config_file=None, **overrides)

        assert config.deployment_mode == DeploymentMode.CLUSTER
        assert config.test_timeout == 600.0
        assert config.verbose == 1

    def test_load_config_from_yaml_file(self) -> None:
        """Test loading configuration from YAML file."""
        yaml_content = """
deployment_mode: cluster
test_timeout: 1800.0
cluster:
  agents: 5
  dbservers: 4
timeouts:
  health_check_default: 3.0
"""

        with patch("builtins.open", mock_open(read_data=yaml_content)):
            with patch("pathlib.Path.exists", return_value=True):
                with patch("armadillo.core.config.load_env_overrides", return_value={}):
                    manager = ConfigManager()
                    config = manager.load_config(config_file=Path("test.yaml"))

                    assert config.deployment_mode == DeploymentMode.CLUSTER
                    assert config.test_timeout == 1800.0
                    assert config.cluster.agents == 5
                    assert config.cluster.dbservers == 4
                    assert config.timeouts.health_check_default == 3.0

    def test_load_config_invalid_file_format(self) -> None:
        """Test loading configuration from unsupported file format."""
        manager = ConfigManager()

        with patch("builtins.open", mock_open(read_data="invalid content")):
            with patch("pathlib.Path.exists", return_value=True):
                with patch("armadillo.core.config.load_env_overrides", return_value={}):
                    with pytest.raises(
                        ConfigurationError,
                        match="Failed to load config file|Unsupported config file format",
                    ):
                        manager.load_config(config_file=Path("test.txt"))

    def test_config_validation_cluster_settings(self) -> None:
        """Test pydantic validation for cluster settings."""
        # Invalid cluster configuration - no agents
        with pytest.raises(ConfigurationError, match="at least 1 agent"):
            ArmadilloConfig(
                deployment_mode=DeploymentMode.CLUSTER,
                cluster=ClusterConfig(agents=0, dbservers=1, coordinators=1),
            )

    def test_config_validation_timeout_settings(self) -> None:
        """Test pydantic validation for timeout settings."""
        with pytest.raises(ConfigurationError, match="timeout must be positive"):
            ArmadilloConfig(
                deployment_mode=DeploymentMode.SINGLE_SERVER, test_timeout=-10.0
            )

    def test_derive_sub_tmp(self) -> None:
        """Test temporary directory derivation."""
        manager = ConfigManager()

        # Set up a config with temp directory
        with patch("pathlib.Path.mkdir"):
            config = ArmadilloConfig(
                deployment_mode=DeploymentMode.SINGLE_SERVER,
                temp_dir=Path("/tmp/test_armadillo"),
            )
            manager._config = config

            sub_dir = manager.derive_sub_tmp("test_subdir")
            assert sub_dir == Path("/tmp/test_armadillo/test_subdir")


class TestGlobalConfigFunctions:
    """Test global configuration functions."""

    def test_load_config_function(self) -> None:
        """Test global load_config function."""
        with patch("armadillo.core.config._config_manager") as mock_manager:
            mock_manager.load_config.return_value = ArmadilloConfig(
                deployment_mode=DeploymentMode.SINGLE_SERVER
            )

            config = load_config(verbose=1)
            mock_manager.load_config.assert_called_once_with(verbose=1)

    def test_get_config_function(self) -> None:
        """Test global get_config function."""
        with patch("armadillo.core.config._config_manager") as mock_manager:
            mock_manager.get_config.return_value = ArmadilloConfig(
                deployment_mode=DeploymentMode.CLUSTER
            )

            config = get_config()
            mock_manager.get_config.assert_called_once()

    def test_get_config_creates_default_if_none(self) -> None:
        """Test get_config creates default config if none exists."""
        from armadillo.core.config import _config_manager

        # Reset the config manager
        _config_manager._config = None

        with patch.object(_config_manager, "load_config") as mock_load:
            mock_load.return_value = ArmadilloConfig(
                deployment_mode=DeploymentMode.SINGLE_SERVER
            )

            config = get_config()
            mock_load.assert_called_once()


class TestConfigurationEdgeCases:
    """Test configuration edge cases and error conditions."""

    def test_config_file_not_found(self) -> None:
        """Test handling of non-existent configuration file."""
        manager = ConfigManager()

        # Should not raise error if file doesn't exist
        config = manager.load_config(config_file=Path("/nonexistent/config.yaml"))
        assert config.deployment_mode == DeploymentMode.SINGLE_SERVER

    def test_config_file_invalid_yaml(self) -> None:
        """Test handling of invalid YAML file."""
        invalid_yaml = "invalid: yaml: content: ["

        with patch("builtins.open", mock_open(read_data=invalid_yaml)):
            with patch("pathlib.Path.exists", return_value=True):
                manager = ConfigManager()

                with pytest.raises(ConfigurationError):
                    manager.load_config(config_file=Path("invalid.yaml"))

    def test_load_config_with_environment_and_overrides(self) -> None:
        """Test configuration loading with environment variables and CLI overrides."""
        manager = ConfigManager()

        # Mock environment loading to return some values
        env_overrides = {
            "deployment_mode": "cluster",
            "test_timeout": 1200.0,
        }

        # CLI overrides should take precedence
        cli_overrides = {
            "test_timeout": 600.0,  # Should override env value
            "verbose": 1,
        }

        with patch(
            "armadillo.core.config.load_env_overrides", return_value=env_overrides
        ):
            config = manager.load_config(config_file=None, **cli_overrides)

        assert config.deployment_mode == DeploymentMode.CLUSTER  # From env
        assert config.test_timeout == 600.0  # CLI override wins
        assert config.verbose == 1  # From CLI
