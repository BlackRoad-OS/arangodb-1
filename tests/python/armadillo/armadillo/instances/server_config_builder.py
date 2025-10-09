"""Server configuration builder for creating consistent server arguments across the framework."""

from ..core.config import ConfigProvider
from ..core.log import Logger


class ServerConfigBuilder:
    """Builds server configuration arguments based on framework settings.

    This centralizes the server logging configuration logic to avoid duplication
    between the deployment planner and pytest plugin.
    """

    def __init__(self, config_provider: ConfigProvider, logger: Logger) -> None:
        self._config_provider = config_provider
        self._logger = logger

    def build_server_args(self) -> dict:
        """Build server arguments based on framework configuration.

        Logging configuration based on show_server_logs setting:
        - show_server_logs=True: log.output=- (all logs to stdout)
        - show_server_logs=False: log.output=-;all=error (only errors to stdout, quiet mode)

        Returns:
            Dictionary of server arguments to pass to ArangoDB server
        """
        show_logs = self._config_provider.show_server_logs
        args = {}

        if show_logs:
            # Show server logs: all logs to stdout
            args["log.output"] = "-"
            self._logger.debug("Configured server to show logs on stdout")
        else:
            # Quiet mode: only errors to stdout, reduce noise
            args["log.output"] = "-;all=error"  # Only error level to stdout
            args["log.level"] = "crash=info"  # Crash info to log file
            self._logger.debug("Configured server for quiet mode (errors only)")

        return args
