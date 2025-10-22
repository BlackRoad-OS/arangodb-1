# Phase 2: ArangoServer Refactoring

## Current Problems

The current `ArangoServer.__init__()` accepts parameters in THREE different ways:

```python
def __init__(
    self,
    server_id: str,
    *,
    role: ServerRole = ServerRole.SINGLE,
    port: Optional[int] = None,
    dependencies: Optional[ServerDependencies] = None,  # Option 1
    config_provider=None,      # Option 2
    logger=None,
    port_allocator=None,
    command_builder=None,
    health_checker=None,
    config=None,               # Option 3
):
```

This creates:
- **Cognitive overload**: Which pattern should I use?
- **Testing confusion**: What needs to be mocked?
- **Maintenance burden**: Changes affect multiple code paths
- **Global getter calls**: Still calling `get_config()`, `get_logger()`, etc.

## Refactoring Strategy

### Step 1: Create New Constructor (Alongside Old)

```python
class ArangoServer:
    def __init__(
        self,
        server_id: str,
        role: ServerRole,
        port: int,
        paths: ServerPaths,
        app_context: ApplicationContext,
    ):
        """Clean constructor with required parameters only."""
        self.server_id = server_id
        self.role = role
        self.port = port
        self.paths = paths
        self._app_context = app_context
        self.endpoint = f"http://127.0.0.1:{self.port}"
        self._runtime = ServerRuntimeState()
```

### Step 2: Add Factory Methods

```python
@classmethod
def create_single_server(
    cls,
    server_id: str,
    app_context: ApplicationContext,
    port: Optional[int] = None,
) -> "ArangoServer":
    """Factory for single server with defaults."""
    actual_port = port or app_context.port_allocator.allocate_port()
    paths = ServerPaths.from_server_id(server_id, app_context.filesystem)
    return cls(server_id, ServerRole.SINGLE, actual_port, paths, app_context)

@classmethod  
def create_cluster_server(
    cls,
    server_id: str,
    role: ServerRole,
    port: int,
    app_context: ApplicationContext,
    config: Optional[ServerConfig] = None,
) -> "ArangoServer":
    """Factory for cluster servers."""
    paths = ServerPaths.from_config(server_id, config, app_context.filesystem)
    return cls(server_id, role, port, paths, app_context)
```

### Step 3: Update Internal Methods

Replace `self._deps.X` with `self._app_context.X`:

```python
# Before:
self._deps.logger.info(...)
self._deps.config_provider.timeouts.server_startup
self._deps.port_allocator.allocate_port()

# After:
self._app_context.logger.info(...)
self._app_context.config.timeouts.server_startup
self._app_context.port_allocator.allocate_port()
```

### Step 4: Gradual Migration

1. Keep old constructor with deprecation warning
2. Update all call sites to use factory methods
3. Remove old constructor after verification

## Implementation Status

- [ ] Create new constructor
- [ ] Add factory methods
- [ ] Update internal method implementations
- [ ] Add deprecation warnings to old constructor
- [ ] Update all call sites
- [ ] Remove old constructor
- [ ] Update tests

