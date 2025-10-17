"""Configuration management with environment variable integration and validation."""

import os
import yaml
from pathlib import Path
from typing import Dict, Any, Optional, TypeVar, Protocol

from .types import ArmadilloConfig, ClusterConfig, TimeoutConfig, InfrastructureConfig
from .errors import ConfigurationError

T = TypeVar("T")


def load_env_overrides(prefix: str = "ARMADILLO_") -> Dict[str, Any]:
    """Load environment variables with the given prefix and convert to appropriate types."""
    overrides = {}

    for key, value in os.environ.items():
        if key.startswith(prefix):
            # Convert environment variable name to config field name
            field_name = key[len(prefix) :].lower()

            # Handle nested configuration (e.g., ARMADILLO_CLUSTER__AGENTS)
            if "__" in field_name:
                parts = field_name.split("__")
                if len(parts) == 2:
                    section, sub_field = parts
                    if section not in overrides:
                        overrides[section] = {}
                    overrides[section][sub_field] = _convert_env_value(value)
                continue

            # Convert the value to appropriate type
            overrides[field_name] = _convert_env_value(value)

    return overrides


def _convert_env_value(value: str) -> Any:
    """Convert string environment value to appropriate Python type."""
    if not value:
        return None

    # Try to convert to int first (before boolean check)
    try:
        return int(value)
    except ValueError:
        pass

    # Try to convert to float
    try:
        return float(value)
    except ValueError:
        pass

    # Handle boolean values (after numeric conversion)
    if value.lower() in ("true", "yes", "on"):
        return True
    elif value.lower() in ("false", "no", "off"):
        return False

    # Handle lists (comma-separated)
    if "," in value:
        return [item.strip() for item in value.split(",")]

    # Return as string
    return value


class ConfigProvider(Protocol):
    """Protocol for configuration providers to enable dependency injection."""

    @property
    def bin_dir(self) -> Optional[Path]:
        """ArangoDB binary directory path."""

    @property
    def work_dir(self) -> Optional[Path]:
        """Working directory for temporary files."""

    @property
    def cluster(self) -> ClusterConfig:
        """Cluster configuration."""

    @property
    def keep_instances_on_failure(self) -> bool:
        """Whether to keep instances running on failure."""

    @property
    def test_timeout(self) -> float:
        """Default test timeout in seconds."""

    @property
    def timeouts(self) -> TimeoutConfig:
        """Timeout configuration."""

    @property
    def infrastructure(self) -> InfrastructureConfig:
        """Infrastructure configuration."""


class ConfigManager:
    """Central configuration management."""

    def __init__(self) -> None:
        self._config: Optional[ArmadilloConfig] = None

    def load_config(
        self, config_file: Optional[Path] = None, **overrides: Any
    ) -> ArmadilloConfig:
        """Load configuration from file and environment with CLI overrides."""

        # Load configuration in the following order of precedence:
        # 1. CLI overrides (highest priority)
        # 2. Environment variables
        # 3. Config file data
        # 4. Model defaults (lowest priority)

        config_data = {}

        # Load from file if provided
        if config_file and config_file.exists():
            config_data.update(self._load_from_file(config_file))

        # Load environment variables
        env_overrides = load_env_overrides()
        config_data.update(env_overrides)

        # Apply CLI overrides (highest priority)
        config_data.update(overrides)

        # Create and validate configuration
        self._config = ArmadilloConfig(**config_data)

        return self._config

    def get_config(self) -> ArmadilloConfig:
        """Get current configuration."""
        if self._config is None:
            self._config = self.load_config()
        return self._config

    def derive_sub_tmp(self, subdir: str) -> Path:
        """Derive a subdirectory path within the configured temp directory."""
        config = self.get_config()
        if config.temp_dir is None:
            # This should not be reached due to validation, but as a fallback:
            config.temp_dir = Path("/tmp/armadillo")

        sub_path = config.temp_dir / subdir
        sub_path.mkdir(parents=True, exist_ok=True)
        return sub_path

    def _load_from_file(self, config_file: Path) -> Dict[str, Any]:
        """Load configuration from YAML file."""
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                if config_file.suffix.lower() in (".yml", ".yaml"):
                    return yaml.safe_load(f) or {}
                else:
                    raise ConfigurationError(
                        f"Unsupported config file format: {config_file.suffix}"
                    )
        except Exception as e:
            raise ConfigurationError(
                f"Failed to load config file {config_file}: {e}"
            ) from e


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
