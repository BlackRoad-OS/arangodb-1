"""Application context for explicit dependency management.

This module provides the ApplicationContext - the single immutable container
for all framework dependencies. This eliminates global mutable singletons and
makes dependencies explicit.

Design Principle:
    ApplicationContext is the "primitive" that flows through the entire system.
    Any component that needs access to framework services receives this context.

Usage:
    # Create context from configuration
    config = ArmadilloConfig(deployment_mode=DeploymentMode.SINGLE_SERVER)
    config = initialize_config(config)  # Separate initialization step
    app_context = ApplicationContext.create(config)

    # Pass context explicitly to components
    server = ArangoServer.create_single_server("test-server", app_context)
    manager = InstanceManager("deployment-1", app_context)

    # For testing
    test_context = ApplicationContext.for_testing()
"""

from dataclasses import dataclass
from typing import Optional
from pathlib import Path

from .types import ArmadilloConfig
from .log import Logger
from ..utils.ports import PortAllocator
from ..utils.auth import AuthProvider
from ..utils.filesystem import FilesystemService
from .process import ProcessSupervisor


@dataclass(frozen=True)
class ApplicationContext:
    """Immutable application-wide context containing all dependencies.

    This is the single source of truth for framework dependencies.
    No global mutable state - everything is explicitly passed.

    Attributes:
        config: Framework configuration
        logger: Logging instance
        port_allocator: Port allocation service
        auth_provider: Authentication provider
        filesystem: Filesystem operations service
        process_supervisor: Process management service

    Example:
        >>> config = ArmadilloConfig(deployment_mode=DeploymentMode.SINGLE_SERVER)
        >>> ctx = ApplicationContext.create(config)
        >>> server = ArangoServer.create_single_server("srv1", ctx)
    """

    config: ArmadilloConfig
    logger: Logger
    port_allocator: PortAllocator
    auth_provider: AuthProvider
    filesystem: FilesystemService
    process_supervisor: ProcessSupervisor
    server_factory: "ServerFactory"
    deployment_planner: "DeploymentPlanner"

    @classmethod
    def create(
        cls,
        config: ArmadilloConfig,
        *,
        logger: Optional[Logger] = None,
        port_allocator: Optional[PortAllocator] = None,
        auth_provider: Optional[AuthProvider] = None,
        filesystem: Optional[FilesystemService] = None,
        process_supervisor: Optional[ProcessSupervisor] = None,
    ) -> "ApplicationContext":
        """Create application context with default implementations.

        This factory method creates an ApplicationContext with sensible defaults
        for any dependencies not explicitly provided. Use this for production code.

        Args:
            config: Framework configuration (required)
            logger: Optional custom logger (creates default if None)
            port_allocator: Optional custom port allocator
            auth_provider: Optional custom auth provider
            filesystem: Optional custom filesystem service
            process_supervisor: Optional custom process supervisor

        Returns:
            Immutable ApplicationContext with all dependencies initialized

        Example:
            >>> config = ArmadilloConfig(...)
            >>> ctx = ApplicationContext.create(config)
            >>> # Or with custom logger
            >>> ctx = ApplicationContext.create(config, logger=my_logger)
        """
        # Import here to avoid circular dependencies at module level
        from .log import configure_logging, get_logger
        from ..utils.ports import PortManager
        from ..utils.auth import AuthProvider as AuthProviderImpl
        from ..utils.filesystem import FilesystemService as FilesystemServiceImpl
        from ..utils.crypto import generate_secret
        from .process import ProcessSupervisor as ProcessSupervisorImpl

        # Create logger if not provided
        if logger is None:
            # Configure logging system
            configure_logging(
                level=config.log_level,
                enable_console=True,
                enable_json=True,
            )
            # Get the configured logger
            logger = get_logger("armadillo")

        # Create port allocator if not provided
        if port_allocator is None:
            port_allocator = PortManager(
                base_port=config.infrastructure.default_base_port,
                max_ports=config.infrastructure.max_port_range,
            )

        # Create auth provider if not provided
        if auth_provider is None:
            auth_provider = AuthProviderImpl(
                secret=generate_secret(),
                algorithm="HS256",
            )

        # Create filesystem service if not provided
        if filesystem is None:
            filesystem = FilesystemServiceImpl(config)

        # Create process supervisor if not provided
        if process_supervisor is None:
            process_supervisor = ProcessSupervisorImpl()

        # Import server-related dependencies here to avoid circular imports
        from ..instances.server_factory import StandardServerFactory
        from ..instances.deployment_planner import DeploymentPlanner

        # Create server factory
        server_factory = StandardServerFactory(
            app_context=None  # Will be set after context creation
        )

        # Create deployment planner
        deployment_planner = DeploymentPlanner(
            port_allocator=port_allocator,
            logger=logger,
            config_provider=config,
            filesystem=filesystem,
        )

        ctx = cls(
            config=config,
            logger=logger,
            port_allocator=port_allocator,
            auth_provider=auth_provider,
            filesystem=filesystem,
            process_supervisor=process_supervisor,
            server_factory=server_factory,
            deployment_planner=deployment_planner,
        )

        # Set circular reference
        server_factory._app_context = ctx

        return ctx

    @classmethod
    def for_testing(
        cls,
        config: Optional[ArmadilloConfig] = None,
        **overrides,
    ) -> "ApplicationContext":
        """Create application context for testing with sensible defaults.

        This factory method is specifically for tests. It creates a minimal
        configuration suitable for unit tests and allows easy mocking of
        individual dependencies.

        Args:
            config: Optional test configuration (creates minimal config if None)
            **overrides: Override specific dependencies for testing (e.g., logger=mock_logger)

        Returns:
            ApplicationContext configured for testing

        Example:
            >>> # Basic test context
            >>> ctx = ApplicationContext.for_testing()
            >>>
            >>> # Test context with mock logger
            >>> mock_logger = Mock(spec=Logger)
            >>> ctx = ApplicationContext.for_testing(logger=mock_logger)
            >>>
            >>> # Test context with custom config
            >>> test_config = ArmadilloConfig(temp_dir=tmp_path)
            >>> ctx = ApplicationContext.for_testing(config=test_config)
        """
        from .types import ArmadilloConfig, DeploymentMode

        # Create minimal test configuration if not provided
        if config is None:
            config = ArmadilloConfig(
                deployment_mode=DeploymentMode.SINGLE_SERVER,
                temp_dir=Path("/tmp/armadillo-test"),
                bin_dir=None,  # Will be auto-detected if needed
                test_timeout=60.0,
                is_test_mode=True,  # Mark as test mode
            )

        # Create context with any overrides
        return cls.create(config, **overrides)
