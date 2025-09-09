"""Tests for configuration management."""

import pytest
import os
from pathlib import Path
from unittest.mock import patch, mock_open

from armadillo.core.config import ConfigLoader, ConfigManager, load_config, get_config
from armadillo.core.types import ArmadilloConfig, DeploymentMode, ClusterConfig, MonitoringConfig
from armadillo.core.errors import ConfigurationError, PathError


class TestConfigLoader:
    """Test ConfigLoader class."""

    def test_config_loader_creation(self):
        """Test ConfigLoader creation with custom prefix."""
        loader = ConfigLoader("TEST_")
        assert loader.env_prefix == "TEST_"

    def test_config_loader_default_prefix(self):
        """Test ConfigLoader with default prefix."""
        loader = ConfigLoader()
        assert loader.env_prefix == "ARMADILLO_"

    @patch.dict(os.environ, {
        'ARMADILLO_DEPLOYMENT_MODE': 'cluster',
        'ARMADILLO_TEST_TIMEOUT': '1200.0',
        'ARMADILLO_VERBOSE': '2'
    })
    def test_load_from_env(self):
        """Test loading configuration from environment variables."""
        loader = ConfigLoader()
        base_config = ArmadilloConfig(deployment_mode=DeploymentMode.SINGLE_SERVER)

        config = loader.load_from_env(ArmadilloConfig, base_config)

        assert config.deployment_mode == DeploymentMode.CLUSTER
        assert config.test_timeout == 1200.0
        assert config.verbose == 2

    @patch.dict(os.environ, {'ARMADILLO_INVALID_ENUM': 'invalid_value'})
    def test_load_from_env_invalid_enum(self):
        """Test loading invalid enum value from environment."""
        loader = ConfigLoader()
        base_config = ArmadilloConfig(deployment_mode=DeploymentMode.SINGLE_SERVER)

        with pytest.raises(ConfigurationError):
            loader.load_from_env(ArmadilloConfig, base_config)

    def test_convert_env_value_boolean(self):
        """Test boolean conversion from environment values."""
        loader = ConfigLoader()

        assert loader._convert_env_value("true", bool) is True
        assert loader._convert_env_value("false", bool) is False
        assert loader._convert_env_value("1", bool) is True
        assert loader._convert_env_value("0", bool) is False
        assert loader._convert_env_value("yes", bool) is True
        assert loader._convert_env_value("no", bool) is False

    def test_convert_env_value_numeric(self):
        """Test numeric conversion from environment values."""
        loader = ConfigLoader()

        assert loader._convert_env_value("42", int) == 42
        assert loader._convert_env_value("3.14", float) == 3.14

        with pytest.raises(ConfigurationError):
            loader._convert_env_value("not_a_number", int)

    def test_convert_env_value_path(self):
        """Test Path conversion from environment values."""
        loader = ConfigLoader()

        result = loader._convert_env_value("/tmp/test", Path)
        assert isinstance(result, Path)
        assert str(result) == "/tmp/test"

    def test_convert_env_value_list(self):
        """Test list conversion from environment values."""
        loader = ConfigLoader()

        # Mock list type
        from typing import List
        result = loader._convert_env_value("a,b,c", List[str])
        assert result == ["a", "b", "c"]


class TestConfigManager:
    """Test ConfigManager class."""

    def test_config_manager_creation(self):
        """Test ConfigManager creation."""
        manager = ConfigManager()
        assert manager._config is None

    def test_create_default_config(self):
        """Test default configuration creation."""
        manager = ConfigManager()
        config = manager._create_default_config()

        assert config.deployment_mode == DeploymentMode.SINGLE_SERVER
        assert config.test_timeout == 900.0
        assert config.result_formats == ["junit", "json"]
        assert config.keep_instances_on_failure is False
        assert config.verbose == 0

    def test_load_config_with_overrides(self):
        """Test configuration loading with CLI overrides."""
        manager = ConfigManager()

        overrides = {
            'deployment_mode': DeploymentMode.CLUSTER,
            'test_timeout': 600.0,
            'verbose': 1
        }

        config = manager.load_config(**overrides)

        assert config.deployment_mode == DeploymentMode.CLUSTER
        assert config.test_timeout == 600.0
        assert config.verbose == 1

    def test_load_config_from_yaml_file(self):
        """Test loading configuration from YAML file."""
        yaml_content = """
deployment_mode: cluster
test_timeout: 1800.0
cluster:
  agents: 5
  dbservers: 4
monitoring:
  enable_crash_analysis: false
"""

        with patch('builtins.open', mock_open(read_data=yaml_content)):
            with patch('pathlib.Path.exists', return_value=True):
                manager = ConfigManager()
                config = manager.load_config(config_file=Path("test.yaml"))

                assert config.deployment_mode == DeploymentMode.CLUSTER
                assert config.test_timeout == 1800.0
                assert config.cluster.agents == 5
                assert config.cluster.dbservers == 4
                assert config.monitoring.enable_crash_analysis is False

    def test_load_config_invalid_file_format(self):
        """Test loading configuration from unsupported file format."""
        manager = ConfigManager()

        with patch('pathlib.Path.exists', return_value=True):
            with pytest.raises(ConfigurationError, match="Unsupported config file format"):
                manager.load_config(config_file=Path("test.txt"))

    def test_validate_config_cluster_validation(self):
        """Test configuration validation for cluster settings."""
        manager = ConfigManager()

        # Invalid cluster configuration - no agents
        config = ArmadilloConfig(
            deployment_mode=DeploymentMode.CLUSTER,
            cluster=ClusterConfig(agents=0, dbservers=1, coordinators=1)
        )

        with pytest.raises(ConfigurationError, match="at least 1 agent"):
            manager._validate_config(config)

    def test_validate_config_timeout_validation(self):
        """Test configuration validation for timeout settings."""
        manager = ConfigManager()

        config = ArmadilloConfig(
            deployment_mode=DeploymentMode.SINGLE_SERVER,
            test_timeout=-10.0
        )

        with pytest.raises(ConfigurationError, match="timeout must be positive"):
            manager._validate_config(config)

    def test_validate_config_path_validation(self):
        """Test configuration validation for paths."""
        manager = ConfigManager()

        config = ArmadilloConfig(
            deployment_mode=DeploymentMode.SINGLE_SERVER,
            bin_dir=Path("/nonexistent/path")
        )

        with pytest.raises(PathError):
            manager._validate_config(config)

    def test_derive_sub_tmp(self):
        """Test temporary directory derivation."""
        manager = ConfigManager()

        # Set up a config with temp directory
        with patch('pathlib.Path.mkdir'):
            config = ArmadilloConfig(
                deployment_mode=DeploymentMode.SINGLE_SERVER,
                temp_dir=Path("/tmp/test_armadillo")
            )
            manager._config = config

            sub_dir = manager.derive_sub_tmp("test_subdir")
            assert sub_dir == Path("/tmp/test_armadillo/test_subdir")


class TestGlobalConfigFunctions:
    """Test global configuration functions."""

    def test_load_config_function(self):
        """Test global load_config function."""
        with patch('armadillo.core.config._config_manager') as mock_manager:
            mock_manager.load_config.return_value = ArmadilloConfig(
                deployment_mode=DeploymentMode.SINGLE_SERVER
            )

            config = load_config(verbose=1)
            mock_manager.load_config.assert_called_once_with(verbose=1)

    def test_get_config_function(self):
        """Test global get_config function."""
        with patch('armadillo.core.config._config_manager') as mock_manager:
            mock_manager.get_config.return_value = ArmadilloConfig(
                deployment_mode=DeploymentMode.CLUSTER
            )

            config = get_config()
            mock_manager.get_config.assert_called_once()

    def test_get_config_creates_default_if_none(self):
        """Test get_config creates default config if none exists."""
        from armadillo.core.config import _config_manager

        # Reset the config manager
        _config_manager._config = None

        with patch.object(_config_manager, 'load_config') as mock_load:
            mock_load.return_value = ArmadilloConfig(
                deployment_mode=DeploymentMode.SINGLE_SERVER
            )

            config = get_config()
            mock_load.assert_called_once()


class TestConfigurationEdgeCases:
    """Test configuration edge cases and error conditions."""

    def test_config_file_not_found(self):
        """Test handling of non-existent configuration file."""
        manager = ConfigManager()

        # Should not raise error if file doesn't exist
        config = manager.load_config(config_file=Path("/nonexistent/config.yaml"))
        assert config.deployment_mode == DeploymentMode.SINGLE_SERVER

    def test_config_file_invalid_yaml(self):
        """Test handling of invalid YAML file."""
        invalid_yaml = "invalid: yaml: content: ["

        with patch('builtins.open', mock_open(read_data=invalid_yaml)):
            with patch('pathlib.Path.exists', return_value=True):
                manager = ConfigManager()

                with pytest.raises(ConfigurationError):
                    manager.load_config(config_file=Path("invalid.yaml"))

    def test_merge_configs_with_nested_objects(self):
        """Test configuration merging with nested objects."""
        manager = ConfigManager()

        base_config = ArmadilloConfig(
            deployment_mode=DeploymentMode.SINGLE_SERVER,
            cluster=ClusterConfig(agents=3, dbservers=2)
        )

        overrides = {
            'cluster': {'agents': 5, 'coordinators': 3}
        }

        merged = manager._merge_configs(base_config, overrides)

        # Should have updated cluster config
        assert merged.cluster.agents == 5
        assert merged.cluster.coordinators == 3
        assert merged.cluster.dbservers == 2  # Should preserve original value
