# Error Handling Guidelines

This document establishes consistent error handling patterns for the Armadillo framework.

## Core Principles

### 1. **Library Code: Let Errors Propagate**

Library code (core modules, utilities, instance management) should:
- Catch only specific exceptions you can handle
- Let errors propagate up with preserved context
- Add context when re-raising: always use `from e`

```python
# ❌ BAD: Catching Exception in library code
def start_server():
    try:
        # ... server logic ...
    except Exception as e:
        logger.error("Error: %s", e)
        return False

# ✅ GOOD: Let specific errors propagate with context
def start_server():
    try:
        # ... server logic ...
    except (OSError, ConnectionError) as e:
        raise ServerStartupError(f"Failed to start server: {e}") from e
```

### 2. **Boundary Code: Convert to User Messages**

Boundary code (CLI commands, pytest plugin entry points) should:
- Catch and convert errors to user-friendly messages
- Log full error details for debugging
- Exit gracefully with appropriate status codes

```python
# ✅ GOOD: Boundary handling in CLI
def cli_command():
    try:
        # ... operation ...
    except ServerError as e:
        logger.error("Server error: %s", e, exc_info=True)
        console.print(f"[red]Error: {e.message}[/red]")
        raise typer.Exit(code=1)
    except ArmadilloError as e:
        logger.error("Framework error: %s", e, exc_info=True)
        console.print(f"[red]Unexpected error: {e.message}[/red]")
        raise typer.Exit(code=1)
```

### 3. **Never Catch Bare Exception**

Never use `except Exception:` in library code. Always catch specific exceptions.

```python
# ❌ BAD: Catching everything
try:
    operation()
except Exception:
    pass

# ✅ GOOD: Catch what you expect
try:
    operation()
except (OSError, IOError) as e:
    logger.warning("I/O operation failed: %s", e)
```

**Exception:** In boundary code where you need to catch all Armadillo errors:

```python
# ✅ ACCEPTABLE: At boundaries only
try:
    framework_operation()
except ArmadilloError as e:
    # Handle all framework errors uniformly
    handle_error(e)
```

### 4. **Always Use `from e` When Re-raising**

Preserve exception chains to maintain debugging context.

```python
# ❌ BAD: Lost context
try:
    load_config()
except JSONDecodeError as e:
    raise ConfigurationError("Invalid config")

# ✅ GOOD: Preserved context
try:
    load_config()
except JSONDecodeError as e:
    raise ConfigurationError(f"Invalid config: {e}") from e
```

### 5. **Silent Failures Require Justification**

If you catch and suppress an exception, add a comment explaining why.

```python
# ✅ GOOD: Justified silent failure
try:
    proc.kill()
except (ProcessLookupError, PermissionError):
    # Process already dead or not owned by us - this is fine during cleanup
    pass

# ❌ BAD: Unexplained suppression
try:
    important_operation()
except Exception:
    pass
```

## Exception Categories

### Use Specific Exceptions

The framework provides a comprehensive error hierarchy. Use the most specific exception type:

- **Process Errors:** `ProcessStartupError`, `ProcessTimeoutError`, `ProcessCrashError`
- **Server Errors:** `ServerStartupError`, `ServerShutdownError`, `HealthCheckError`
- **Configuration:** `ConfigurationError`, `PathError`
- **Filesystem:** `FilesystemError`, `AtomicWriteError`
- **Network:** `NetworkError`, `ServerConnectionError`
- **Test Execution:** `SetupError`, `TeardownError`, `ExecutionTimeoutError`
- **Cluster:** `ClusterError`, `AgencyError`
- **Results:** `ResultProcessingError`, `AnalysisError`

See `armadillo/core/errors.py` for the complete hierarchy.

## Common Patterns

### Pattern 1: Resource Cleanup on Failure

```python
# ✅ GOOD: Proper cleanup with context preservation
def start_with_cleanup():
    resource = None
    try:
        resource = acquire_resource()
        return start_operation(resource)
    except (IOError, OSError) as e:
        if resource:
            try:
                resource.cleanup()
            except Exception:
                # Cleanup failure shouldn't mask original error
                logger.warning("Cleanup failed during error handling")
        raise ServerStartupError(f"Failed to start: {e}") from e
```

### Pattern 2: Best-Effort Operations

```python
# ✅ GOOD: Best-effort with logging
def try_get_error_output(proc):
    """Try to get error output, but don't fail if we can't."""
    try:
        stdout, stderr = proc.communicate(timeout=1.0)
        return stdout
    except (subprocess.TimeoutExpired, OSError):
        # Can't get output - that's okay, we tried
        logger.debug("Could not retrieve process output")
        return ""
```

### Pattern 3: Error Context Enrichment

```python
# ✅ GOOD: Add context at each layer
def high_level_operation(server_id):
    try:
        return low_level_operation(server_id)
    except ProcessError as e:
        # Add high-level context
        raise ServerError(
            f"Server {server_id} operation failed: {e}",
            details={"server_id": server_id, "original_error": str(e)}
        ) from e
```

### Pattern 4: Boundary Error Handling

```python
# ✅ GOOD: CLI boundary handler
def handle_command_errors(func):
    """Decorator for consistent CLI error handling."""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except ConfigurationError as e:
            logger.error("Configuration error: %s", e)
            console.print(f"[red]Configuration error: {e.message}[/red]")
            raise typer.Exit(code=2)
        except ServerError as e:
            logger.error("Server error: %s", e, exc_info=True)
            console.print(f"[red]Server error: {e.message}[/red]")
            raise typer.Exit(code=1)
        except ArmadilloError as e:
            logger.error("Framework error: %s", e, exc_info=True)
            console.print(f"[red]Error: {e.message}[/red]")
            raise typer.Exit(code=1)
        except Exception as e:
            logger.error("Unexpected error: %s", e, exc_info=True)
            console.print(f"[red]Unexpected error: {str(e)}[/red]")
            raise typer.Exit(code=1)
    return wrapper
```

## Testing Error Handling

When testing error conditions:

```python
# ✅ GOOD: Test specific exceptions
def test_server_start_failure():
    with pytest.raises(ServerStartupError, match="Failed to start"):
        server.start()

# ✅ GOOD: Verify exception chaining
def test_error_chain_preserved():
    with pytest.raises(ServerStartupError) as exc_info:
        server.start()
    assert exc_info.value.__cause__ is not None
```

## Migration Checklist

When refactoring error handling:

1. ✅ Replace `except Exception` with specific exceptions
2. ✅ Add `from e` to all re-raises
3. ✅ Document any silent failures with comments
4. ✅ Convert boundary code to use error handlers
5. ✅ Use framework-specific exception types
6. ✅ Preserve error context (details dict)
7. ✅ Test error paths explicitly

## Summary

| Context | Rule | Example |
|---------|------|---------|
| **Library Code** | Catch specific, re-raise with `from e` | `except OSError as e: raise ServerError(...) from e` |
| **Boundary Code** | Catch `ArmadilloError`, convert to UI | `except ArmadilloError as e: show_error(e)` |
| **Cleanup** | Best-effort, don't mask original | `try: cleanup() except: logger.warning(...)` |
| **Testing** | Use framework errors in tests too | Tests can catch `Exception` for verification |
| **Silent Failures** | Must have justifying comment | `except ProcessLookupError: # Process already dead` |

---

**Remember:** Good error handling makes debugging easier. Always preserve context and be explicit about what can go wrong.

