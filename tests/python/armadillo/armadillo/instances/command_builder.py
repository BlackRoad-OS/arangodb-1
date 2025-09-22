"""ArangoDB server command line builder for different roles and configurations."""
from typing import List, Optional, Protocol
from pathlib import Path
from dataclasses import dataclass
from ..core.types import ServerRole, ServerConfig
from ..core.config import ConfigProvider
from ..core.log import Logger

@dataclass
class ServerCommandParams:
    """Parameters for building server commands."""
    server_id: str
    role: ServerRole
    port: int
    data_dir: Path
    app_dir: Path
    config: Optional[ServerConfig] = None

class CommandBuilder(Protocol):
    """Protocol for command builders to enable dependency injection."""

    def build_command(self, params: ServerCommandParams) -> List[str]:
        """Build command line arguments for server startup."""
        ...

    def get_repository_root(self) -> Path:
        """Get the ArangoDB repository root directory."""
        ...

class ServerCommandBuilder:
    """Builds ArangoDB server command lines based on role and configuration."""

    def __init__(self, config_provider: ConfigProvider, logger: Logger) -> None:
        self._config_provider = config_provider
        self._logger = logger

    def build_command(self, params: ServerCommandParams) -> List[str]:
        """Build ArangoDB command line arguments."""
        repository_root = self._get_repository_root()
        if self._config_provider.bin_dir:
            arangod_path = str(self._config_provider.bin_dir / 'arangod')
        else:
            arangod_path = 'arangod'
        command = [
            arangod_path,
            '--configuration', self._get_config_file_for_role(params.role),
            '--define', f'TOP_DIR={repository_root}',
            '--server.endpoint', f'tcp://0.0.0.0:{params.port}',
            '--database.directory', str(params.data_dir),
            '--javascript.app-path', str(params.app_dir)
        ]
        if params.role == ServerRole.SINGLE:
            command.extend(['--server.storage-engine', 'rocksdb'])
        elif params.role == ServerRole.AGENT:
            command.extend(['--agency.activate', 'true', '--agency.size', '3', '--agency.supervision', 'true'])
        elif params.role in [ServerRole.COORDINATOR, ServerRole.DBSERVER]:
            command.extend(['--cluster.create-waits-for-sync-replication', 'false', '--cluster.write-concern', '1'])
        if params.config and params.config.args:
            for key, value in params.config.args.items():
                if isinstance(value, list):
                    for item in value:
                        command.extend([f'--{key}', str(item)])
                else:
                    command.extend([f'--{key}', str(value)])
        self._logger.info('>>> ARANGOD COMMAND FOR %s <<<', params.server_id)
        self._logger.info('Command: %s', ' '.join(command))
        self._logger.info('>>> END ARANGOD COMMAND <<<')
        return command

    def get_repository_root(self) -> Path:
        """Get the ArangoDB repository root directory."""
        return self._get_repository_root()

    def _get_repository_root(self) -> Path:
        """Get the ArangoDB repository root directory."""
        if self._config_provider.bin_dir:
            bin_path = Path(self._config_provider.bin_dir)
            if bin_path.name == 'bin' and bin_path.parent.exists():
                repository_root = bin_path.parent.parent
            else:
                repository_root = bin_path.parent
            if (repository_root / 'js').exists() and (repository_root / 'etc').exists():
                return repository_root
        cwd = Path.cwd()
        if (cwd / 'js').exists() and (cwd / 'etc').exists():
            return cwd
        for parent in cwd.parents:
            if (parent / 'js').exists() and (parent / 'etc').exists():
                return parent
        return cwd

    def _get_config_file_for_role(self, role: ServerRole) -> str:
        """Get configuration file path for the server role."""
        if role == ServerRole.SINGLE:
            return 'etc/testing/arangod-single.conf'
        elif role == ServerRole.AGENT:
            return 'etc/testing/arangod-agent.conf'
        elif role == ServerRole.COORDINATOR:
            return 'etc/testing/arangod-coordinator.conf'
        elif role == ServerRole.DBSERVER:
            return 'etc/testing/arangod-dbserver.conf'
        else:
            return 'etc/testing/arangod.conf'