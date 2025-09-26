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
        """Build server arguments based on framework verbose mode.

        Logging configuration:
        - verbose >= 2: log.level=debug + log.output=- (full debug logs to stdout)
        - verbose >= 1: log.output=- (all logs to stdout, default level)
        - verbose == 0: log.output=-;all=error + log.level=crash=info (quiet mode)

        Returns:
            Dictionary of server arguments to pass to ArangoDB server
        """
        verbose = self._config_provider.verbose
        args = {}

        if verbose >= 2:
            # Very verbose: enable debug logging with full stdout output
            args["log.level"] = "debug"
            args["log.output"] = "-"  # All debug logs to stdout
            self._logger.debug("Configured server for debug logging (verbose >= 2)")
        elif verbose >= 1:
            # Verbose: all logs to stdout but default log level
            args["log.output"] = "-"  # All logs to stdout
            self._logger.debug("Configured server for verbose logging (verbose >= 1)")
        else:
            # Normal mode (quiet): only errors to stdout, reduce noise
            args["log.output"] = "-;all=error"  # Only error level to stdout
            args["log.level"] = "crash=info"  # Crash info to log file
            self._logger.debug("Configured server for quiet logging (verbose == 0)")

        return args
