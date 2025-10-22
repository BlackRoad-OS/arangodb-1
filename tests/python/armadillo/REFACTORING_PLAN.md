# Armadillo Refactoring Plan

## Executive Summary

This plan addresses critical architectural issues identified in the Armadillo codebase review. The refactoring is structured in phases to minimize risk while delivering incremental improvements.

**Timeline**: 4-6 weeks  
**Risk Level**: Medium (with proper testing and incremental approach)  
**Expected Impact**: Major improvement in maintainability, testability, and code clarity

---

## Phase 1: Foundation - Application Context (Week 1)

### Goal
Eliminate global mutable singletons by introducing a single, immutable ApplicationContext that explicitly manages all dependencies.

### Why This First?
- **Highest impact**: Touches nearly every module
- **Foundation for other refactorings**: Other improvements depend on explicit dependency management
- **Clear black-box boundary**: Establishes what the "primitives" of the system are

### Tasks

#### 1.1 Create ApplicationContext (Day 1)
**File**: `armadillo/core/context.py` (NEW)

```python
"""Application context for explicit dependency management."""

from dataclasses import dataclass
from typing import Optional
from pathlib import Path

from .types import ArmadilloConfig
from .log import Logger, configure_logging
from ..utils.ports import PortAllocator, PortManager
from ..utils.auth import AuthProvider
from ..utils.filesystem import FilesystemService
from .process import ProcessSupervisor


@dataclass(frozen=True)
class ApplicationContext:
    """Immutable application-wide context containing all dependencies.
    
    This is the single source of truth for framework dependencies.
    No global mutable state - everything is explicitly passed.
    
    Design Principle: This is the "primitive" that flows through the entire system.
    Any component that needs access to framework services receives this context.
    """
    
    config: ArmadilloConfig
    logger: Logger
    port_allocator: PortAllocator
    auth_provider: AuthProvider
    filesystem: FilesystemService
    process_supervisor: ProcessSupervisor
    
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
        
        Args:
            config: Framework configuration (required)
            logger: Optional custom logger (creates default if None)
            port_allocator: Optional custom port allocator
            auth_provider: Optional custom auth provider
            filesystem: Optional custom filesystem service
            process_supervisor: Optional custom process supervisor
        
        Returns:
            Immutable ApplicationContext
        """
        from .log import get_logger
        from ..utils.crypto import generate_secret
        
        # Create defaults only if not provided
        final_logger = logger or configure_logging(
            level=config.log_level,
            enable_console=True,
            enable_json=True,
        )
        
        final_port_allocator = port_allocator or PortManager(
            base_port=config.infrastructure.default_base_port,
            max_ports=config.infrastructure.max_port_range,
        )
        
        final_auth_provider = auth_provider or AuthProvider(
            secret=generate_secret(),
            algorithm="HS256",
        )
        
        final_filesystem = filesystem or FilesystemService(config)
        
        final_process_supervisor = process_supervisor or ProcessSupervisor()
        
        return cls(
            config=config,
            logger=final_logger,
            port_allocator=final_port_allocator,
            auth_provider=final_auth_provider,
            filesystem=final_filesystem,
            process_supervisor=final_process_supervisor,
        )
    
    @classmethod
    def for_testing(
        cls,
        config: Optional[ArmadilloConfig] = None,
        **overrides,
    ) -> "ApplicationContext":
        """Create application context for testing with sensible defaults.
        
        Args:
            config: Optional test configuration
            **overrides: Override specific dependencies for testing
        
        Returns:
            ApplicationContext configured for testing
        """
        from .types import ArmadilloConfig, DeploymentMode
        
        test_config = config or ArmadilloConfig(
            deployment_mode=DeploymentMode.SINGLE_SERVER,
            temp_dir=Path("/tmp/armadillo-test"),
            bin_dir=None,  # Will be auto-detected if needed
            test_timeout=60.0,
        )
        
        return cls.create(test_config, **overrides)
```

**Testing Strategy**:
```python
# framework_tests/unit/test_core_context.py
def test_context_is_immutable():
    """ApplicationContext should be immutable."""
    ctx = ApplicationContext.for_testing()
    with pytest.raises(FrozenInstanceError):
        ctx.config = ArmadilloConfig()

def test_context_create_with_defaults():
    """Should create valid context with all defaults."""
    config = ArmadilloConfig(deployment_mode=DeploymentMode.SINGLE_SERVER)
    ctx = ApplicationContext.create(config)
    assert ctx.config is config
    assert ctx.logger is not None
    assert ctx.port_allocator is not None
    assert ctx.auth_provider is not None
    assert ctx.filesystem is not None
    assert ctx.process_supervisor is not None

def test_context_create_with_overrides():
    """Should accept custom implementations."""
    config = ArmadilloConfig(deployment_mode=DeploymentMode.SINGLE_SERVER)
    mock_logger = Mock(spec=Logger)
    ctx = ApplicationContext.create(config, logger=mock_logger)
    assert ctx.logger is mock_logger
```

#### 1.2 Separate Config Validation from Initialization (Day 2)
**File**: `armadillo/core/types.py`

**Changes**:
```python
class ArmadilloConfig(BaseModel):
    """Pure configuration with validation only - NO SIDE EFFECTS."""
    
    # Remove is_test_mode detection
    is_test_mode: bool = False  # Explicit flag instead of stack inspection
    
    @model_validator(mode="after")
    def validate_config(self) -> "ArmadilloConfig":
        """Pure validation - no filesystem operations, no auto-detection.
        
        This method ONLY validates that the configuration is internally consistent.
        It does NOT create directories, detect builds, or perform any I/O.
        """
        # Validate cluster configuration
        if self.deployment_mode == DeploymentMode.CLUSTER:
            if self.cluster.agents < 1:
                raise ConfigurationError("Cluster must have at least 1 agent")
            if self.cluster.dbservers < 1:
                raise ConfigurationError("Cluster must have at least 1 dbserver")
            if self.cluster.coordinators < 1:
                raise ConfigurationError("Cluster must have at least 1 coordinator")
        
        # Validate timeouts
        if self.test_timeout <= 0:
            raise ConfigurationError("Test timeout must be positive")
        
        return self
    
    # REMOVE: _is_unit_test_context() - use explicit is_test_mode flag instead
```

**New File**: `armadillo/core/config_initializer.py`

```python
"""Configuration initialization with side effects separated from validation."""

from pathlib import Path
from .types import ArmadilloConfig
from .build_detection import detect_build_directory, normalize_build_directory
from .errors import PathError


def initialize_config(config: ArmadilloConfig) -> ArmadilloConfig:
    """Initialize configuration with side effects.
    
    This is called AFTER validation and performs:
    - Directory creation
    - Build detection
    - Path normalization
    
    Args:
        config: Validated configuration
    
    Returns:
        Initialized configuration (may have modified fields)
    
    Raises:
        PathError: If required paths cannot be created or detected
    """
    # Set default temp directory if not specified
    if config.temp_dir is None:
        config.temp_dir = Path("/tmp/armadillo")
    
    # Create temp directory
    config.temp_dir.mkdir(parents=True, exist_ok=True)
    
    # Handle bin_dir: normalize or auto-detect (only if not in test mode)
    if config.bin_dir is not None:
        # User explicitly provided a build directory - normalize it
        normalized_bin_dir = normalize_build_directory(config.bin_dir)
        if normalized_bin_dir is None:
            raise PathError(
                f"Could not find arangod binary in build directory: {config.bin_dir}\n"
                f"Looked in:\n"
                f"  - {config.bin_dir}/arangod\n"
                f"  - {config.bin_dir}/bin/arangod\n"
                f"Please ensure the build directory contains a compiled arangod executable."
            )
        config.bin_dir = normalized_bin_dir
    elif not config.is_test_mode:
        # No explicit bin_dir and not in test mode - try auto-detection
        detected_build_dir = detect_build_directory()
        if detected_build_dir:
            config.bin_dir = detected_build_dir
    
    # Create work directory if specified
    if config.work_dir and not config.work_dir.exists():
        config.work_dir.mkdir(parents=True, exist_ok=True)
    
    return config
```

**Migration Path**:
1. Create new `config_initializer.py` with `initialize_config()`
2. Update CLI to call `initialize_config()` explicitly
3. Update tests to use `is_test_mode=True` flag
4. Remove initialization from `validate_config()`
5. Remove `_is_unit_test_context()` method

**Testing**:
```python
def test_config_validation_has_no_side_effects(tmp_path):
    """Config validation should not create directories."""
    non_existent = tmp_path / "does_not_exist"
    config = ArmadilloConfig(temp_dir=non_existent)
    # Directory should NOT be created by validation
    assert not non_existent.exists()

def test_config_initialization_creates_directories(tmp_path):
    """Config initialization should create required directories."""
    temp_dir = tmp_path / "armadillo_temp"
    config = ArmadilloConfig(temp_dir=temp_dir)
    initialized = initialize_config(config)
    # Directory SHOULD be created by initialization
    assert initialized.temp_dir.exists()
```

#### 1.3 Update FilesystemService to Accept Config (Day 3)
**File**: `armadillo/utils/filesystem.py`

**Changes**:
```python
class FilesystemService:
    """Provides safe filesystem operations with atomic writes and path management."""
    
    def __init__(self, config: ArmadilloConfig) -> None:
        """Initialize with explicit configuration.
        
        Args:
            config: Framework configuration
        """
        self._config = config
        self._work_dir: Optional[Path] = None
        self._test_session_id: Optional[str] = None
    
    def set_test_session_id(self, session_id: str) -> None:
        """Set test session ID for directory isolation.
        
        Args:
            session_id: Unique test session identifier
        """
        self._test_session_id = session_id
        self._work_dir = None  # Reset to force recalculation
    
    def work_dir(self) -> Path:
        """Get the main working directory."""
        if self._work_dir is None:
            if self._config.work_dir:
                base_work_dir = self._config.work_dir
            else:
                base_work_dir = self._config.temp_dir / "work"
            
            if self._test_session_id:
                self._work_dir = base_work_dir / f"session_{self._test_session_id}"
            else:
                self._work_dir = base_work_dir
            
            self._work_dir.mkdir(parents=True, exist_ok=True)
        
        return self._work_dir
    
    # ... rest of methods remain the same ...

# REMOVE: Module-level singleton
# REMOVE: Module-level functions that use singleton
```

#### 1.4 Update CLI to Use ApplicationContext (Day 4)
**File**: `armadillo/cli/main.py`

**Changes**:
```python
import typer
from pathlib import Path
from ..core.types import ArmadilloConfig, DeploymentMode
from ..core.config_initializer import initialize_config
from ..core.context import ApplicationContext
from ..core.errors import ArmadilloError


app = typer.Typer(name="armadillo", help="Modern ArangoDB Testing Framework")


@app.command()
def test(
    test_path: Path = typer.Argument(..., help="Path to test directory or file"),
    cluster: bool = typer.Option(False, "--cluster", help="Run in cluster mode"),
    bin_dir: Optional[Path] = typer.Option(None, "--bin-dir", help="ArangoDB binary directory"),
    timeout: float = typer.Option(900.0, "--timeout", help="Test timeout in seconds"),
    output_dir: Path = typer.Option(Path("./test-results"), "--output-dir", help="Output directory"),
    verbose: int = typer.Option(0, "-v", "--verbose", count=True, help="Increase verbosity"),
    compact: bool = typer.Option(False, "--compact", help="Compact output mode"),
    show_server_logs: bool = typer.Option(False, "--show-server-logs", help="Show server logs"),
) -> None:
    """Run tests with ArangoDB infrastructure."""
    
    try:
        # 1. Create configuration (pure validation only)
        config = ArmadilloConfig(
            deployment_mode=DeploymentMode.CLUSTER if cluster else DeploymentMode.SINGLE_SERVER,
            bin_dir=bin_dir,
            test_timeout=timeout,
            verbose=verbose,
            compact_mode=compact,
            show_server_logs=show_server_logs,
            is_test_mode=False,  # Explicit: not in test mode
        )
        
        # 2. Initialize configuration (side effects: create dirs, detect builds)
        config = initialize_config(config)
        
        # 3. Create application context (dependency injection root)
        app_context = ApplicationContext.create(config)
        
        # 4. Run tests with context
        _run_tests_with_context(app_context, test_path, output_dir)
        
    except ArmadilloError as e:
        app_context.logger.error("Test execution failed: %s", e)
        raise typer.Exit(code=1)
    except Exception as e:
        typer.echo(f"Unexpected error: {e}", err=True)
        raise typer.Exit(code=2)


def _run_tests_with_context(
    app_context: ApplicationContext,
    test_path: Path,
    output_dir: Path,
) -> None:
    """Run tests with application context."""
    # Implementation delegates to pytest with context
    ...
```

#### 1.5 Update Pytest Plugin to Use ApplicationContext (Day 5)
**File**: `armadillo/pytest_plugin/plugin.py`

**Key Changes**:
```python
class ArmadilloPlugin:
    """Main pytest plugin for Armadillo framework."""
    
    def __init__(self) -> None:
        self._app_context: Optional[ApplicationContext] = None
        self._session_deployments: Dict[str, InstanceManager] = {}
        self._deployment_failed: bool = False
        self._deployment_failure_reason: Optional[str] = None
    
    def pytest_configure(self, config: pytest.Config) -> None:
        """Configure pytest for Armadillo."""
        # Load configuration
        framework_config = load_config_from_env()  # Loads from env vars set by CLI
        framework_config = initialize_config(framework_config)
        
        # Create application context
        self._app_context = ApplicationContext.create(framework_config)
        
        # Rest of setup uses self._app_context instead of global getters
        ...
```

### Deliverables (Phase 1)
- [ ] `ApplicationContext` created and tested
- [ ] Config validation separated from initialization
- [ ] All global singletons eliminated
- [ ] CLI updated to use ApplicationContext
- [ ] Pytest plugin updated to use ApplicationContext
- [ ] All unit tests passing
- [ ] Integration tests passing

### Success Metrics
- Zero global mutable singletons in codebase
- All dependencies explicitly passed via ApplicationContext
- Tests can instantiate multiple independent contexts
- No stack inspection for test detection

---

## Phase 2: Dependency Injection Standardization (Week 2)

### Goal
Standardize on a single, clear dependency injection pattern across all classes.

### Principle
**Constructor Injection with Required Dependencies**

Every class constructor should:
1. Accept all required dependencies as explicit parameters
2. Store dependencies in private fields
3. NOT have "either/or" parameter patterns
4. NOT call global getters internally

Convenience factory methods are fine, but separate from constructors.

### Tasks

#### 2.1 Refactor ArangoServer (Days 1-2)
**File**: `armadillo/instances/server.py`

**Before** (confusing):
```python
class ArangoServer:
    def __init__(
        self,
        server_id: str,
        *,
        role: ServerRole = ServerRole.SINGLE,
        port: Optional[int] = None,
        dependencies: Optional[ServerDependencies] = None,  # Option 1
        config_provider=None,  # Option 2
        logger=None,  # Option 2
        port_allocator=None,  # Option 2
        command_builder=None,  # Option 2
        health_checker=None,  # Option 2
        config=None,  # Option 3
    ):
        # Complex logic choosing between options...
```

**After** (clear):
```python
class ArangoServer:
    """ArangoDB server instance with lifecycle management.
    
    This class follows strict dependency injection - all dependencies
    must be provided explicitly at construction time.
    """
    
    def __init__(
        self,
        server_id: str,
        role: ServerRole,
        port: int,
        paths: ServerPaths,
        app_context: ApplicationContext,
    ) -> None:
        """Initialize server with explicit dependencies.
        
        Args:
            server_id: Unique server identifier
            role: Server role (SINGLE, AGENT, DBSERVER, COORDINATOR)
            port: Port number (must be pre-allocated)
            paths: Server filesystem paths
            app_context: Application context with all framework dependencies
        """
        self.server_id = server_id
        self.role = role
        self.port = port
        self.paths = paths
        self._app_context = app_context
        self.endpoint = f"http://127.0.0.1:{self.port}"
        
        # Runtime state
        self._runtime = ServerRuntimeState()
        
        self._app_context.logger.info(
            "Created server: id=%s, role=%s, port=%d",
            server_id, role.value, port
        )
    
    @classmethod
    def create_single_server(
        cls,
        server_id: str,
        app_context: ApplicationContext,
        port: Optional[int] = None,
    ) -> "ArangoServer":
        """Factory method for single server with sensible defaults.
        
        Args:
            server_id: Unique server identifier
            app_context: Application context
            port: Optional preferred port (allocated if None)
        
        Returns:
            Configured single server instance
        """
        # Allocate port
        actual_port = port or app_context.port_allocator.allocate_port()
        
        # Create paths
        paths = ServerPaths.from_server_id(server_id, app_context.filesystem)
        
        return cls(
            server_id=server_id,
            role=ServerRole.SINGLE,
            port=actual_port,
            paths=paths,
            app_context=app_context,
        )
    
    @classmethod
    def create_cluster_server(
        cls,
        server_id: str,
        role: ServerRole,
        port: int,
        app_context: ApplicationContext,
        config: Optional[ServerConfig] = None,
    ) -> "ArangoServer":
        """Factory method for cluster server.
        
        Args:
            server_id: Unique server identifier
            role: Server role (AGENT, DBSERVER, or COORDINATOR)
            port: Allocated port number
            app_context: Application context
            config: Optional server-specific configuration
        
        Returns:
            Configured cluster server instance
        """
        if role == ServerRole.SINGLE:
            raise ValueError("Use create_single_server() for single servers")
        
        paths = ServerPaths.from_config(server_id, config, app_context.filesystem)
        
        return cls(
            server_id=server_id,
            role=role,
            port=port,
            paths=paths,
            app_context=app_context,
        )
```

**Migration Strategy**:
1. Add new constructors alongside old ones (with deprecation warnings)
2. Update all internal code to use new constructors
3. Update tests to use new constructors
4. Remove old constructors after one release cycle

#### 2.2 Refactor InstanceManager (Days 3-4)
**File**: `armadillo/instances/manager.py`

**After**:
```python
class InstanceManager:
    """Manages lifecycle of multiple ArangoDB server instances.
    
    This is a pure facade over specialized components. It maintains
    NO duplicate state - all queries delegate to the appropriate component.
    """
    
    def __init__(
        self,
        deployment_id: str,
        app_context: ApplicationContext,
        server_factory: Optional[ServerFactory] = None,
    ) -> None:
        """Initialize instance manager with explicit dependencies.
        
        Args:
            deployment_id: Unique deployment identifier
            app_context: Application context with all framework dependencies
            server_factory: Optional custom server factory (creates default if None)
        """
        self.deployment_id = deployment_id
        self._app_context = app_context
        
        # Initialize specialized components
        self._server_registry = ServerRegistry()
        self._health_monitor = HealthMonitor(
            app_context.logger,
            app_context.config.timeouts
        )
        self._cluster_bootstrapper = ClusterBootstrapper(
            app_context.logger,
            app_context.config.timeouts
        )
        
        # Use provided factory or create default
        self._server_factory = server_factory or StandardServerFactory(app_context)
        
        self._deployment_orchestrator = DeploymentOrchestrator(
            logger=app_context.logger,
            server_factory=self._server_factory,
            server_registry=self._server_registry,
            cluster_bootstrapper=self._cluster_bootstrapper,
            health_monitor=self._health_monitor,
        )
        
        # Minimal state - only what's not in specialized components
        self._deployment_plan: Optional[DeploymentPlan] = None
        self._is_deployed: bool = False
    
    # REMOVE: DeploymentState with duplicate servers/startup_order
    # REMOVE: _sync_state_from_registry() - delegate directly instead
    
    def get_all_servers(self) -> Dict[str, ArangoServer]:
        """Get all servers - delegates to registry."""
        return self._server_registry.get_all_servers()
    
    def get_startup_order(self) -> List[str]:
        """Get startup order - delegates to orchestrator."""
        return self._deployment_orchestrator.get_startup_order()
```

#### 2.3 Remove ServerDependencies Wrapper (Day 5)
Since we now have ApplicationContext, the `ServerDependencies` wrapper is redundant.

**Remove**:
- `armadillo/instances/server.py:ServerDependencies` class
- `armadillo/instances/manager.py:ManagerDependencies` class

**Replace** with direct ApplicationContext usage.

### Deliverables (Phase 2)
- [ ] ArangoServer uses standard DI pattern
- [ ] InstanceManager uses standard DI pattern
- [ ] All components accept ApplicationContext
- [ ] Factory methods provide convenience
- [ ] Old constructors removed or deprecated
- [ ] All tests updated and passing

### Success Metrics
- Single clear pattern for dependency injection
- No "either/or" constructor parameters
- No global getter calls in class bodies
- Factory methods separate from constructors

---

## Phase 3: Error Handling Standardization (Week 3)

### Goal
Establish and enforce consistent error handling patterns across the codebase.

### Principles

1. **Library Code**: Let errors propagate (don't catch unless you can handle)
2. **Boundary Code** (CLI, Plugin): Catch and convert to user-friendly messages
3. **Never Catch `Exception`**: Always be specific
4. **Log Before Raising**: Context is important
5. **Always Use `from e`**: Preserve stack traces

### Tasks

#### 3.1 Create Error Handling Guidelines (Day 1)
**File**: `armadillo/core/error_handling.py` (NEW)

```python
"""Error handling guidelines and utilities for Armadillo framework.

GUIDELINES:

1. Library Code (utils/, core/, instances/):
   - Let errors propagate naturally
   - Only catch if you can meaningfully handle or add context
   - Always use 'from e' when re-raising

2. Boundary Code (CLI, pytest plugin):
   - Catch ArmadilloError and convert to user messages
   - Catch unexpected errors and log full traces
   - Set appropriate exit codes

3. Never catch Exception:
   - Always be specific about what you expect
   - Document what exceptions each function can raise

4. Resource Cleanup:
   - Use try/finally for cleanup
   - Use context managers where possible
   - Never silently swallow exceptions in cleanup

EXAMPLE - Library Code:
    def risky_operation() -> Result:
        '''Raises: ServerError if server fails to start'''
        try:
            server.start()
        except OSError as e:
            raise ServerError(f"Failed to start server: {e}") from e
        # Don't catch here - let caller decide how to handle ServerError

EXAMPLE - Boundary Code:
    def cli_command():
        try:
            risky_operation()
        except ArmadilloError as e:
            logger.error("Operation failed: %s", e)
            sys.exit(1)
        except Exception as e:
            logger.exception("Unexpected error")
            sys.exit(2)
"""

from typing import TypeVar, Callable, Any
from functools import wraps
import sys

from .errors import ArmadilloError
from .log import get_logger

logger = get_logger(__name__)

T = TypeVar('T')


def handle_cli_errors(func: Callable[..., T]) -> Callable[..., T]:
    """Decorator for CLI commands to handle errors consistently.
    
    Usage:
        @handle_cli_errors
        def my_command():
            ...  # Any ArmadilloError will be caught and converted
    """
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> T:
        try:
            return func(*args, **kwargs)
        except ArmadilloError as e:
            logger.error("Command failed: %s", e)
            if e.details:
                for key, value in e.details.items():
                    logger.error("  %s: %s", key, value)
            sys.exit(1)
        except KeyboardInterrupt:
            logger.warning("Command interrupted by user")
            sys.exit(130)  # Standard exit code for Ctrl+C
        except Exception as e:
            logger.exception("Unexpected error in command")
            sys.exit(2)
    
    return wrapper
```

#### 3.2 Audit and Fix Error Handling (Days 2-5)

**Systematic Audit**:
1. Search for `except Exception` → replace with specific exceptions
2. Search for `except: pass` → add logging or justification
3. Search for `raise ... Exception` → ensure `from e` is used
4. Search for cleanup code → convert to context managers

**Files to Review** (priority order):
1. `armadillo/core/process.py` - 915 lines, lots of error handling
2. `armadillo/instances/server.py` - Server lifecycle errors
3. `armadillo/instances/manager.py` - Deployment errors
4. `armadillo/pytest_plugin/plugin.py` - Boundary error handling
5. All other instance management files

**Pattern to Fix**:
```python
# BEFORE (Bad):
try:
    server.stop()
except Exception:  # Too broad!
    pass  # Silent swallow!

# AFTER (Good):
try:
    server.stop()
except (ServerShutdownError, ProcessError) as e:
    logger.error("Failed to stop server %s: %s", server_id, e)
    # Re-raise if caller needs to know
    raise
```

### Deliverables (Phase 3)
- [ ] Error handling guidelines documented
- [ ] All `except Exception` replaced with specific exceptions
- [ ] All silent exception swallowing justified or removed
- [ ] All re-raises use `from e`
- [ ] CLI commands use error handling decorator
- [ ] All tests passing

### Success Metrics
- Zero bare `except:` clauses
- Zero `except Exception` in library code
- All errors documented in docstrings
- Consistent error handling at boundaries

---

## Phase 4: Async/Sync Consistency (Week 4)

### Goal
Choose one paradigm (async) and apply consistently, with explicit sync adapters where needed.

### Decision: Go Full Async

**Rationale**:
- Pytest supports async tests natively (`@pytest.mark.asyncio`)
- Modern Python ecosystem favors async
- Better for I/O-bound operations (network, processes)
- Can always wrap async in sync, but not vice versa

### Tasks

#### 4.1 Identify Sync/Async Boundary (Day 1)

**Audit**: Mark each module as:
- **Pure Async**: All methods are async
- **Pure Sync**: All methods are sync (allowed for pure computation)
- **Mixed**: Has both (needs fixing)

**Expected Results**:
- `core/` - Mixed → needs fixing
- `instances/` - Mixed → needs fixing
- `utils/` - Mostly sync (OK for pure operations)
- `pytest_plugin/` - Mixed → needs fixing

#### 4.2 Convert Core Classes to Async (Days 2-3)

**Files**:
- `armadillo/instances/server.py`
- `armadillo/instances/manager.py`
- `armadillo/instances/health_checker.py`

**Example**:
```python
# BEFORE:
class ArangoServer:
    def start(self, timeout: Optional[float] = None) -> None:
        """Sync start."""
        ...
    
    def health_check_sync(self, timeout: float = 5.0) -> HealthStatus:
        """Sync health check."""
        ...
    
    async def get_stats(self) -> Optional[ServerStats]:
        """Async stats - inconsistent!"""
        ...

# AFTER:
class ArangoServer:
    async def start(self, timeout: Optional[float] = None) -> None:
        """Async start - consistent."""
        ...
    
    async def check_health(self, timeout: float = 5.0) -> HealthStatus:
        """Async health check - consistent."""
        ...
    
    async def get_stats(self) -> Optional[ServerStats]:
        """Async stats - consistent."""
        ...
```

#### 4.3 Create Sync Adapters Module (Day 4)
**File**: `armadillo/sync_adapters.py` (NEW)

```python
"""Synchronous adapters for async operations.

This module provides sync wrappers around async operations for cases
where async/await cannot be used (e.g., pytest fixtures that aren't async).

WARNING: These adapters create new event loops and should be used sparingly.
Prefer async operations where possible.
"""

import asyncio
from typing import Optional

from .instances.server import ArangoServer
from .core.types import HealthStatus, ServerStats


def start_server_sync(server: ArangoServer, timeout: Optional[float] = None) -> None:
    """Synchronous adapter for server.start().
    
    Args:
        server: Server instance
        timeout: Optional timeout
    
    Warning: Creates new event loop - use sparingly!
    """
    asyncio.run(server.start(timeout))


def check_health_sync(server: ArangoServer, timeout: float = 5.0) -> HealthStatus:
    """Synchronous adapter for server.check_health().
    
    Args:
        server: Server instance
        timeout: Health check timeout
    
    Returns:
        Health status
    
    Warning: Creates new event loop - use sparingly!
    """
    return asyncio.run(server.check_health(timeout))
```

#### 4.4 Update Tests to Use Async (Day 5)

```python
# BEFORE:
def test_server_starts():
    server = create_server()
    server.start()
    assert server.is_running()

# AFTER:
@pytest.mark.asyncio
async def test_server_starts():
    server = create_server()
    await server.start()
    assert await server.is_running()
```

### Deliverables (Phase 4)
- [ ] All core classes use async consistently
- [ ] Sync adapters module created
- [ ] Tests updated to use async
- [ ] Documentation updated
- [ ] All tests passing

### Success Metrics
- No `asyncio.run()` calls in class methods
- Clear async/sync boundary
- All I/O operations are async
- Sync adapters isolated in one module

---

## Phase 5: Final Cleanup & Documentation (Weeks 5-6)

### Tasks

#### 5.1 Introduce Value Objects (Week 5)
- Create `ServerId`, `Port`, `DeploymentId` value objects
- Replace primitive types with value objects
- Update type hints throughout

#### 5.2 Centralize Magic Constants (Week 5)
- Audit codebase for hardcoded values
- Move all to `InfrastructureConfig` or appropriate config class
- Document why each value was chosen

#### 5.3 Fix Naming Consistency (Week 5)
- Audit `_private_method` usage
- Ensure private methods aren't called externally
- Fix public API naming

#### 5.4 Update Documentation (Week 6)
- Update README with new patterns
- Create architecture decision records (ADRs)
- Update developer guide
- Create migration guide for external code

#### 5.5 Performance Testing (Week 6)
- Benchmark refactored code vs original
- Ensure no performance regressions
- Profile hot paths

---

## Risk Mitigation

### Testing Strategy
1. **Before Each Phase**: Run full test suite, note any flaky tests
2. **During Refactoring**: Run affected tests continuously
3. **After Each Task**: Run full test suite
4. **Before Next Phase**: Full integration test run

### Rollback Plan
- Each phase is independent - can roll back one phase without affecting others
- Use feature flags for major changes
- Keep old interfaces with deprecation warnings for one release

### Communication
- Create GitHub issues for each phase
- Weekly progress updates
- Code review for each major change
- Pair programming for risky refactorings

---

## Success Criteria

### Technical Metrics
- [ ] Zero global mutable singletons
- [ ] Single dependency injection pattern throughout
- [ ] All config validation is pure (no side effects)
- [ ] Consistent error handling across codebase
- [ ] Single async/sync paradigm
- [ ] All magic constants centralized
- [ ] 100% test pass rate maintained

### Quality Metrics
- [ ] Code complexity reduced (measure cyclomatic complexity)
- [ ] Test execution time not increased >10%
- [ ] Lines of code reduced or stayed same
- [ ] Number of public APIs reduced

### Documentation Metrics
- [ ] Architecture decision records created
- [ ] Developer guide updated
- [ ] Migration guide created
- [ ] All public APIs documented

---

## Post-Refactoring Benefits

### For Developers
- **Clearer code**: Single way to do things
- **Easier testing**: Mock dependencies easily
- **Faster onboarding**: Consistent patterns
- **Better IDE support**: Explicit dependencies mean better autocomplete

### For Maintainers
- **Easier debugging**: Explicit data flow
- **Safer changes**: Changes are localized
- **Better reliability**: Fewer hidden dependencies
- **Easier refactoring**: Black-box modules can be replaced

### For the Project
- **Higher quality**: Consistent standards
- **Lower technical debt**: Issues systematically addressed
- **Better architecture**: Follows proven principles
- **Future-proof**: Easy to extend and modify

---

**Next Steps**: Review this plan, adjust priorities, and get team buy-in before starting Phase 1.

