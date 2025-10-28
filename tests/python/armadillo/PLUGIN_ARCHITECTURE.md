# Armadillo Pytest Plugin Architecture

## Overview
The Armadillo pytest plugin follows a **hybrid lifecycle management** approach that balances fixture autonomy with centralized safety net cleanup.

## Architecture Principles

### 1. **Fixture-Driven Startup**
- Individual fixtures (`arango_single_server`, `arango_cluster`, etc.) are responsible for creating and starting their own resources
- Fixtures know best when they need resources and what configuration to use
- On-demand resource creation minimizes overhead for tests that don't need servers

### 2. **Plugin Safety Net Cleanup**
- Plugin tracks all session-scoped resources in centralized dictionaries:
  - `_session_deployments`: All deployments (single server and clusters)
- Plugin cleanup only activates if fixtures fail to clean up properly
- Prevents resource leaks when tests are interrupted or fixtures fail

### 3. **Coordinated Lifecycle Management**

#### Startup Flow:
```
pytest_configure()
  ↓
Configure logging, timeouts, markers
  ↓
_maybe_start_session_servers() [Future: could pre-analyze and start]
  ↓
Individual fixtures start resources on-demand
  ↓
Fixtures register resources with plugin for tracking
```

#### Cleanup Flow:
```
Fixture cleanup (normal case)
  ↓
Remove from plugin tracking
  ↓
pytest_unconfigure() [Safety net - only cleans up remaining resources]
  ↓
Clear all tracking dictionaries
  ↓
Stop timeout watchdog
```

## Key Improvements Made

### Before (Broken):
- ❌ Plugin cleaned up resources it never created
- ❌ Double cleanup between fixtures and plugin
- ❌ Race conditions in cleanup order
- ❌ Unclear resource ownership

### After (Fixed):
- ✅ Plugin provides safety net cleanup for resources that fixtures failed to clean
- ✅ Fixtures properly register/deregister from plugin tracking
- ✅ Robust cleanup with state checking (`is_deployed()`, `is_running()`)
- ✅ Clear logging distinguishes fixture cleanup vs plugin safety cleanup
- ✅ Exception handling prevents cleanup failures from cascading

## Usage Examples

### Session-Scoped Server (using InstanceManager)
```python
@pytest.fixture(scope="session")
def arango_single_server():
    from ..instances.manager import get_instance_manager

    deployment_id = "test_single_server_session"
    manager = get_instance_manager(deployment_id)
    try:
        plan = manager.create_single_server_plan()
        manager.deploy_servers(plan, timeout=60.0)
        _plugin._session_deployments[deployment_id] = manager
        servers = manager.get_all_servers()
        yield next(iter(servers.values()))
    finally:
        manager.shutdown_deployment(timeout=30.0)
        _plugin._session_deployments.pop(deployment_id, None)
```

### Plugin Safety Net
```python
def pytest_unconfigure(self, config):
    """Only cleans up resources that fixtures failed to clean."""
    for deployment_id, manager in self._session_deployments.items():
        if manager.is_deployed():
            logger.info("Plugin safety cleanup: shutting down deployment %s", deployment_id)
            manager.shutdown_deployment()
```

## Future Enhancements

### Planned:
- **Smart Pre-starting**: Analyze test collection to pre-start commonly used servers
- **Resource Pooling**: Reuse servers across test sessions when possible
- **Health Monitoring**: Continuously monitor server health during test execution
- **Resource Limits**: Prevent tests from consuming excessive system resources

### Extensibility:
- Plugin architecture supports adding new resource types
- Tracking dictionaries can be extended for new deployment patterns
- Cleanup logic is generic and works with any resource that has lifecycle methods

## Debugging

### Logging Levels:
- `INFO`: Major lifecycle events (start/stop servers, deployments)
- `DEBUG`: Detailed tracking events (register/deregister, safety checks)
- `ERROR`: Cleanup failures and resource leaks

### Key Log Messages:
- `"Plugin safety cleanup: ..."` - Plugin is cleaning up resources that fixtures left behind
- `"...removed from plugin tracking"` - Fixture properly cleaned up and deregistered
- `"Session server pre-start analysis complete"` - Plugin startup phase completed

### Output Modes
- Verbose reporter (default): rich, file-structured output + JSON export
- Compact mode: pytest-style minimal output when `--compact` is used
