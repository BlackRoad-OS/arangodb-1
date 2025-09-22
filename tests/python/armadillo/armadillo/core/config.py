"""Configuration management with environment variable integration and validation."""

import os
import inspect
import yaml
from pathlib import Path
from typing import Dict, Any, Optional, Type, TypeVar, Protocol
from dataclasses import dataclass, fields

from .types import ArmadilloConfig, DeploymentMode, ClusterConfig, MonitoringConfig
from .errors import ConfigurationError, PathError
from .build_detection import detect_build_directory

T = TypeVar('T')


class ConfigProvider(Protocol):
    """Protocol for configuration providers to enable dependency injection."""

    @property
    def bin_dir(self) -> Optional[Path]:
        """ArangoDB binary directory path."""
        ...

    @property
    def work_dir(self) -> Optional[Path]:
        """Working directory for temporary files."""
        ...

    @property
    def cluster(self) -> ClusterConfig:
        """Cluster configuration."""
        ...

    @property
    def verbose(self) -> int:
        """Verbosity level."""
        ...

    @property
    def keep_instances_on_failure(self) -> bool:
        """Whether to keep instances running on failure."""
        ...

    @property
    def test_timeout(self) -> float:
        """Default test timeout in seconds."""
        ...


class ConfigLoader:
    """Configuration loader with environment variable override support."""

    def __init__(self, env_prefix: str = "ARMADILLO_") -> None:
        self.env_prefix = env_prefix

    def load_from_env(self, config_cls: Type[T], base_config: Optional[T] = None) -> T:
        """Load configuration from environment variables."""
        if base_config is None:
            base_config = config_cls()

        config_dict = {}

        # Process each field in the dataclass
        for field in fields(config_cls):
            env_key = f"{self.env_prefix}{field.name.upper()}"
            env_value = os.environ.get(env_key)

            if env_value is not None:
                # Convert string env values to appropriate types
                converted_value = self._convert_env_value(env_value, field.type)
                config_dict[field.name] = converted_value

        # Update base config with environment overrides
        if config_dict:
            if hasattr(base_config, '__dict__'):
                for key, value in config_dict.items():
                    setattr(base_config, key, value)
            else:
                # For immutable configs, create new instance
                current_dict = base_config.__dict__ if hasattr(base_config, '__dict__') else {}
                current_dict.update(config_dict)
                base_config = config_cls(**current_dict)

        return base_config

    def _convert_env_value(self, value: str, target_type: Type) -> Any:
        """Convert string environment value to target type."""
        # Handle None/empty values
        if not value or value.lower() in ('none', 'null', ''):
            return None

        # Handle boolean values
        if target_type == bool:
            return value.lower() in ('true', '1', 'yes', 'on')

        # Handle numeric types
        if target_type == int:
            try:
                return int(value)
            except ValueError:
                raise ConfigurationError(f"Invalid integer value: {value}")

        if target_type == float:
            try:
                return float(value)
            except ValueError:
                raise ConfigurationError(f"Invalid float value: {value}")

        # Handle Path types
        if target_type == Path or target_type == Optional[Path]:
            return Path(value)

        # Handle enums
        if hasattr(target_type, '__members__'):
            try:
                return target_type(value)
            except ValueError:
                valid_values = list(target_type.__members__.keys())
                raise ConfigurationError(f"Invalid enum value '{value}'. Valid values: {valid_values}")

        # Handle lists (comma-separated)
        if hasattr(target_type, '__origin__') and target_type.__origin__ == list:
            return [item.strip() for item in value.split(',')]

        # Default to string
        return value


class ConfigManager:
    """Central configuration management."""

    def __init__(self) -> None:
        self._config: Optional[ArmadilloConfig] = None
        self._loader = ConfigLoader()

    def load_config(self,
                   config_file: Optional[Path] = None,
                   **overrides: Any) -> ArmadilloConfig:
        """Load configuration from file and environment with CLI overrides."""
        base_config = self._create_default_config()

        # Load from file if provided
        if config_file and config_file.exists():
            file_config = self._load_from_file(config_file)
            base_config = self._merge_configs(base_config, file_config)

        # Apply environment variable overrides
        base_config = self._loader.load_from_env(ArmadilloConfig, base_config)

        # Apply CLI overrides
        if overrides:
            base_config = self._apply_overrides(base_config, overrides)

        # Validate and normalize
        base_config = self._validate_config(base_config)

        self._config = base_config
        return base_config

    def get_config(self) -> ArmadilloConfig:
        """Get current configuration."""
        if self._config is None:
            self._config = self.load_config()
        return self._config

    def derive_sub_tmp(self, subdir: str) -> Path:
        """Derive a subdirectory path within the configured temp directory."""
        config = self.get_config()
        if config.temp_dir is None:
            config.temp_dir = Path("/tmp/armadillo")

        sub_path = config.temp_dir / subdir
        sub_path.mkdir(parents=True, exist_ok=True)
        return sub_path

    def _create_default_config(self) -> ArmadilloConfig:
        """Create default configuration."""
        return ArmadilloConfig(
            deployment_mode=DeploymentMode.SINGLE_SERVER,
            cluster=ClusterConfig(),
            monitoring=MonitoringConfig(),
            test_timeout=900.0,
            result_formats=["junit", "json"],
            temp_dir=None,  # Will be set to /tmp/armadillo if not specified
            keep_instances_on_failure=False,
            bin_dir=None,
            work_dir=None,
            verbose=0,
            log_level="INFO",
            compact_mode=False
        )

    def _load_from_file(self, config_file: Path) -> Dict[str, Any]:
        """Load configuration from YAML file."""
        try:
            with open(config_file, 'r') as f:
                if config_file.suffix.lower() in ('.yml', '.yaml'):
                    return yaml.safe_load(f) or {}
                else:
                    raise ConfigurationError(f"Unsupported config file format: {config_file.suffix}")
        except Exception as e:
            raise ConfigurationError(f"Failed to load config file {config_file}: {e}")

    def _merge_configs(self, base: ArmadilloConfig, overrides: Dict[str, Any]) -> ArmadilloConfig:
        """Merge configuration dictionaries."""
        config_dict = {}

        # Convert base config to dict
        for field in fields(base):
            config_dict[field.name] = getattr(base, field.name)

        # Apply overrides recursively
        def merge_dict(base_dict: Dict, override_dict: Dict) -> Dict:
            result = base_dict.copy()
            for key, value in override_dict.items():
                if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                    result[key] = merge_dict(result[key], value)
                else:
                    result[key] = value
            return result

        merged_dict = merge_dict(config_dict, overrides)

        # Handle nested objects
        if 'cluster' in overrides and isinstance(overrides['cluster'], dict):
            cluster_config = ClusterConfig(**overrides['cluster'])
            merged_dict['cluster'] = cluster_config

        if 'monitoring' in overrides and isinstance(overrides['monitoring'], dict):
            monitoring_config = MonitoringConfig(**overrides['monitoring'])
            merged_dict['monitoring'] = monitoring_config

        return ArmadilloConfig(**merged_dict)

    def _apply_overrides(self, base: ArmadilloConfig, overrides: Dict[str, Any]) -> ArmadilloConfig:
        """Apply CLI overrides to configuration."""
        config_dict = {}

        for field in fields(base):
            value = overrides.get(field.name, getattr(base, field.name))
            config_dict[field.name] = value

        return ArmadilloConfig(**config_dict)

    def _validate_config(self, config: ArmadilloConfig) -> ArmadilloConfig:
        """Validate and normalize configuration."""
        # Set default temp directory if not specified
        if config.temp_dir is None:
            config.temp_dir = Path("/tmp/armadillo")

        # Create temp directory
        config.temp_dir.mkdir(parents=True, exist_ok=True)

        # Auto-detect build directory if not explicitly set
        # Skip build detection for unit tests to avoid expensive filesystem scanning
        if config.bin_dir is None and not self._is_unit_test_context():
            detected_build_dir = detect_build_directory()
            if detected_build_dir:
                config.bin_dir = detected_build_dir
                # Note: verbose info logged by detection function

        # Validate paths exist
        if config.bin_dir and not config.bin_dir.exists():
            raise PathError(f"Binary directory does not exist: {config.bin_dir}")

        if config.work_dir and not config.work_dir.exists():
            config.work_dir.mkdir(parents=True, exist_ok=True)

        # Validate cluster configuration
        if config.deployment_mode == DeploymentMode.CLUSTER:
            if config.cluster.agents < 1:
                raise ConfigurationError("Cluster must have at least 1 agent")
            if config.cluster.dbservers < 1:
                raise ConfigurationError("Cluster must have at least 1 dbserver")
            if config.cluster.coordinators < 1:
                raise ConfigurationError("Cluster must have at least 1 coordinator")

        # Validate timeouts
        if config.test_timeout <= 0:
            raise ConfigurationError("Test timeout must be positive")

        return config

    def _is_unit_test_context(self) -> bool:
        """Check if we're running in a unit test context where build detection should be skipped."""
        # Check call stack for unit test patterns - this is most reliable
        for frame_info in inspect.stack():
            if 'framework_tests/unit' in frame_info.filename or 'framework_tests\\unit' in frame_info.filename:
                return True

        return False


# Global config manager instance
_config_manager = ConfigManager()


def load_config(**kwargs) -> ArmadilloConfig:
    """Load global configuration."""
    return _config_manager.load_config(**kwargs)


def get_config() -> ArmadilloConfig:
    """Get current global configuration."""
    return _config_manager.get_config()


def derive_sub_tmp(subdir: str) -> Path:
    """Derive a subdirectory path within the configured temp directory."""
    return _config_manager.derive_sub_tmp(subdir)

