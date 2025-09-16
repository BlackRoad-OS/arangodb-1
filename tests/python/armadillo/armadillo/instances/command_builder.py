"""ArangoDB server command line builder for different roles and configurations."""

from typing import List, Optional, Dict, Any, Protocol
from pathlib import Path

from ..core.types import ServerRole, ServerConfig
from ..core.config import ConfigProvider
from ..core.log import Logger


class CommandBuilder(Protocol):
    """Protocol for command builders to enable dependency injection."""
    
    def build_command(self,
                     server_id: str,
                     role: ServerRole,
                     port: int,
                     data_dir: Path,
                     app_dir: Path,
                     config: Optional[ServerConfig] = None) -> List[str]:
        """Build command line arguments for server startup."""
        ...
    
    def get_repository_root(self) -> Path:
        """Get the ArangoDB repository root directory."""
        ...


class ServerCommandBuilder:
    """Builds ArangoDB server command lines based on role and configuration."""
    
    def __init__(self,
                 config_provider: ConfigProvider,
                 logger: Logger) -> None:
        self._config_provider = config_provider
        self._logger = logger
    
    def build_command(self,
                     server_id: str,
                     role: ServerRole,
                     port: int,
                     data_dir: Path,
                     app_dir: Path,
                     config: Optional[ServerConfig] = None) -> List[str]:
        """Build ArangoDB command line arguments."""
        repository_root = self._get_repository_root()

        # Get arangod binary path
        if self._config_provider.bin_dir:
            arangod_path = str(self._config_provider.bin_dir / "arangod")
        else:
            # Fallback to arangod in PATH (likely to fail, but maintains compatibility)
            arangod_path = "arangod"

        # Build command following old framework approach
        command = [
            arangod_path,
            # Use config file and define TOP_DIR (like old framework)
            "--configuration", self._get_config_file_for_role(role),
            "--define", f"TOP_DIR={repository_root}",
            # Server-specific parameters
            "--server.endpoint", f"tcp://0.0.0.0:{port}",
            "--database.directory", str(data_dir),
            "--javascript.app-path", str(app_dir)
        ]

        # Add role-specific arguments
        if role == ServerRole.SINGLE:
            command.extend([
                "--server.storage-engine", "rocksdb"
            ])
        elif role == ServerRole.AGENT:
            command.extend([
                "--agency.activate", "true",
                "--agency.size", "3",
                "--agency.supervision", "true"
            ])
        elif role in [ServerRole.COORDINATOR, ServerRole.DBSERVER]:
            command.extend([
                "--cluster.create-waits-for-sync-replication", "false",
                "--cluster.write-concern", "1"
            ])

        # Add custom arguments from config
        if config and config.args:
            for key, value in config.args.items():
                command.extend([f"--{key}", str(value)])

        # Log the complete command for debugging
        self._logger.info(f">>> ARANGOD COMMAND FOR {server_id} <<<")
        self._logger.info(f"Command: {' '.join(command)}")
        self._logger.info(f">>> END ARANGOD COMMAND <<<")
        
        return command
    
    def get_repository_root(self) -> Path:
        """Get the ArangoDB repository root directory."""
        return self._get_repository_root()

    def _get_repository_root(self) -> Path:
        """Get the ArangoDB repository root directory."""
        if self._config_provider.bin_dir:
            # Derive repository root from build directory
            # Examples: build-clang/bin -> repository root is ../..
            #           build/bin -> repository root is ../..
            #           bin -> repository root is ..
            bin_path = Path(self._config_provider.bin_dir)
            if bin_path.name == "bin" and bin_path.parent.exists():
                # build-clang/bin -> build-clang -> repository_root
                repository_root = bin_path.parent.parent
            else:
                # build-clang -> repository_root
                repository_root = bin_path.parent

            # Validate by checking for expected directories
            if (repository_root / "js").exists() and (repository_root / "etc").exists():
                return repository_root

        # Fallback: use current working directory and check if it looks like repository root
        cwd = Path.cwd()
        if (cwd / "js").exists() and (cwd / "etc").exists():
            return cwd

        # Last resort: try parent directories
        for parent in cwd.parents:
            if (parent / "js").exists() and (parent / "etc").exists():
                return parent

        # Give up and use cwd
        return cwd

    def _get_config_file_for_role(self, role: ServerRole) -> str:
        """Get configuration file path for the server role."""
        if role == ServerRole.SINGLE:
            return "etc/testing/arangod-single.conf"
        elif role == ServerRole.AGENT:
            return "etc/testing/arangod-agent.conf"
        elif role == ServerRole.COORDINATOR:
            return "etc/testing/arangod-coordinator.conf"
        elif role == ServerRole.DBSERVER:
            return "etc/testing/arangod-dbserver.conf"
        else:
            # Default fallback
            return "etc/testing/arangod.conf"
