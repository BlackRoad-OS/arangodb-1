"""Test execution CLI commands."""

import os
import sys
import signal
import subprocess
import threading
from pathlib import Path
from typing import Optional, List
import typer
from pydantic import BaseModel, Field, field_validator, ConfigDict
from rich.console import Console
from rich.table import Table
from ...core.config import load_config
from ...core.config_initializer import initialize_config
from ...core.log import get_logger
from ...core.types import DeploymentMode
from ...core.errors import ArmadilloError
from ..timeout_handler import TimeoutHandler, TimeoutType


# Centralized descriptions - single source of truth for CLI help and model documentation
_HELP = {
    "cluster": "Use cluster deployment instead of single server",
    "timeout": "Per-test timeout in seconds",
    "global_timeout": "Global timeout for entire test session in seconds (default: 900s)",
    "output_idle_timeout": "Kill pytest if no output for N seconds (detects hung tests, default: disabled)",
    "output_dir": "Output directory for results",
    "formats": "Result output formats",
    "build_dir": "ArangoDB build directory (auto-detected if not specified)",
    "keep_instances_on_failure": "Keep instances running on test failure for debugging",
    "keep_temp_dir": "Keep temp directory after successful test runs (default: cleanup on success)",
    "parallel": "Run tests in parallel",
    "max_workers": "Maximum parallel workers",
    "extra_args": "Additional arguments to pass to pytest",
    "show_server_logs": "Show ArangoDB server log output",
    "compact": "Use compact pytest-style output instead of detailed verbose output",
}


class TestRunOptions(BaseModel):
    """Pydantic model for test run command options."""

    test_paths: List[str] = Field(
        default_factory=lambda: ["tests/"], description="Test paths to execute"
    )
    cluster: bool = Field(False, description=_HELP["cluster"])
    timeout: Optional[float] = Field(None, description=_HELP["timeout"])
    global_timeout: Optional[float] = Field(None, description=_HELP["global_timeout"])
    output_idle_timeout: Optional[float] = Field(
        None, description=_HELP["output_idle_timeout"]
    )
    output_dir: Path = Field(Path("./test-results"), description=_HELP["output_dir"])
    formats: List[str] = Field(
        default_factory=lambda: ["junit", "json"], description=_HELP["formats"]
    )
    build_dir: Optional[Path] = Field(None, description=_HELP["build_dir"])
    keep_instances_on_failure: bool = Field(
        False, description=_HELP["keep_instances_on_failure"]
    )
    keep_temp_dir: bool = Field(False, description=_HELP["keep_temp_dir"])
    parallel: bool = Field(False, description=_HELP["parallel"])
    max_workers: Optional[int] = Field(None, description=_HELP["max_workers"])
    extra_args: Optional[List[str]] = Field(None, description=_HELP["extra_args"])
    log_level: str = Field(
        "WARNING", description="Framework logging level (DEBUG, INFO, WARNING, ERROR)"
    )
    show_server_logs: bool = Field(False, description=_HELP["show_server_logs"])
    compact: bool = Field(False, description=_HELP["compact"])

    @field_validator("formats")
    @classmethod
    def validate_formats(cls, v):
        """Validate that only supported formats are specified."""
        supported_formats = {"junit", "json", "yaml", "html"}
        for fmt in v:
            if fmt not in supported_formats:
                raise ValueError(
                    f"Unsupported format '{fmt}'. Supported: {supported_formats}"
                )
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v):
        """Validate log level is supported."""
        if v.upper() not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(
                f"Invalid log level '{v}'. Must be one of: DEBUG, INFO, WARNING, ERROR, CRITICAL"
            )
        return v.upper()

    @field_validator("max_workers")
    @classmethod
    def validate_max_workers(cls, v):
        """Validate max_workers is reasonable."""
        if v is not None and (v < 1 or v > 64):
            raise ValueError("max_workers must be between 1 and 64")
        return v

    model_config = ConfigDict(
        # Allow extra fields for future expansion
        extra="forbid",
        # Use enum values
        use_enum_values=True,
    )


console = Console()
logger = get_logger(__name__)
test_app = typer.Typer(help="Execute tests")


@test_app.command()
def run(
    ctx: typer.Context,
    test_paths: List[str] = typer.Argument(help="Test paths to execute"),
    cluster: bool = typer.Option(False, "--cluster", help=_HELP["cluster"]),
    timeout: Optional[float] = typer.Option(None, "--timeout", help=_HELP["timeout"]),
    global_timeout: Optional[float] = typer.Option(
        None, "--global-timeout", help=_HELP["global_timeout"]
    ),
    output_idle_timeout: Optional[float] = typer.Option(
        None, "--output-idle-timeout", help=_HELP["output_idle_timeout"]
    ),
    output_dir: Path = typer.Option(
        Path("./test-results"), "--output-dir", "-o", help=_HELP["output_dir"]
    ),
    formats: List[str] = typer.Option(
        ["junit", "json"], "--format", help=_HELP["formats"]
    ),
    build_dir: Optional[Path] = typer.Option(
        None, "--build-dir", "-b", help=_HELP["build_dir"]
    ),
    keep_instances_on_failure: bool = typer.Option(
        False, "--keep-instances-on-failure", help=_HELP["keep_instances_on_failure"]
    ),
    keep_temp_dir: bool = typer.Option(
        False, "--keep-temp-dir", help=_HELP["keep_temp_dir"]
    ),
    parallel: bool = typer.Option(False, "--parallel", help=_HELP["parallel"]),
    max_workers: Optional[int] = typer.Option(
        None, "--max-workers", help=_HELP["max_workers"]
    ),
    extra_args: Optional[List[str]] = typer.Option(
        None, "--pytest-arg", help=_HELP["extra_args"]
    ),
    show_server_logs: bool = typer.Option(
        False, "--show-server-logs", help=_HELP["show_server_logs"]
    ),
    compact: bool = typer.Option(False, "--compact", "-c", help=_HELP["compact"]),
):
    """Run tests with ArangoDB instances."""
    try:
        # Get global log level from CLI context (already resolved from verbose if needed)
        cli_options = ctx.obj.get("cli_options", {}) if ctx.obj else {}
        log_level = getattr(cli_options, "log_level", "WARNING")

        # Create and validate options using pydantic model
        # If no test paths provided, use default
        if not test_paths:
            test_paths = ["tests/"]

        options = TestRunOptions(
            test_paths=test_paths,
            cluster=cluster,
            timeout=timeout,
            global_timeout=global_timeout,
            output_idle_timeout=output_idle_timeout,
            output_dir=output_dir,
            formats=formats,
            build_dir=build_dir,
            keep_instances_on_failure=keep_instances_on_failure,
            keep_temp_dir=keep_temp_dir,
            parallel=parallel,
            max_workers=max_workers,
            extra_args=extra_args,
            log_level=log_level,
            show_server_logs=show_server_logs,
            compact=compact,
        )

        # Use the validated options for the rest of the function
        _execute_test_run(options)

    except ArmadilloError as e:
        # Expected framework errors - clean message, no stack trace
        logger.error("Test execution failed: %s", e.message)
        raise typer.Exit(1)
    except Exception as e:
        # Unexpected errors - full stack trace for debugging
        logger.exception("Unexpected error during test execution: %s", e)
        raise typer.Exit(1)


def _execute_test_run(options: TestRunOptions) -> None:
    """Execute test run with validated options."""
    # Load and configure the framework
    deployment_mode = (
        DeploymentMode.CLUSTER if options.cluster else DeploymentMode.SINGLE_SERVER
    )

    # Build config kwargs - pass bin_dir to load_config so validation happens first
    config_kwargs = {
        "deployment_mode": deployment_mode,
        "log_level": options.log_level,
        "show_server_logs": options.show_server_logs,
        "compact_mode": options.compact,
        "is_test_mode": False,  # Explicit: not in test mode
    }

    # Configure global timeout if specified (default is 900s in ArmadilloConfig)
    if options.global_timeout:
        config_kwargs["test_timeout"] = options.global_timeout

    if options.build_dir:
        bin_dir = options.build_dir.resolve()
        config_kwargs["bin_dir"] = bin_dir
        if bin_dir and bin_dir.exists():
            console.print(f"[green]Using ArangoDB build directory: {bin_dir}[/green]")

    # Step 1: Load config (pure validation)
    config = load_config(**config_kwargs)

    # Step 2: Initialize config (side effects: create dirs, detect builds)
    config = initialize_config(config)

    # Always propagate bin_dir to pytest subprocess (whether explicitly set or auto-detected)
    # This prevents duplicate build detection in the subprocess
    if config.bin_dir:
        os.environ["ARMADILLO_BIN_DIR"] = str(config.bin_dir)

    # Logging is configured once in the main CLI callback.

    # Build pytest arguments
    pytest_args = ["python", "-m", "pytest"]
    pytest_args.extend(["-p", "armadillo.pytest_plugin.plugin"])

    # Always disable output capture to allow our reporter to work without /dev/tty hacks
    pytest_args.append("-s")

    if options.compact:
        # Use pytest's default output format (shows filenames and dots)
        pytest_args.append("--tb=no")
    else:
        # In verbose mode with custom reporter, suppress pytest's filename output
        pytest_args.append("-q")

    for path in options.test_paths:
        pytest_args.append(str(path))

    # Configure timeout
    if options.timeout:
        pytest_args.extend(["--timeout", str(options.timeout)])

    # Configure deployment mode for pytest subprocess
    os.environ["ARMADILLO_DEPLOYMENT_MODE"] = deployment_mode.value
    console.print(f"[cyan]Using {deployment_mode.value} deployment mode[/cyan]")

    # Propagate log level to pytest subprocess
    os.environ["ARMADILLO_LOG_LEVEL"] = options.log_level

    # Configure server log visibility for pytest subprocess
    os.environ["ARMADILLO_SHOW_SERVER_LOGS"] = str(int(options.show_server_logs))

    # Configure compact mode for pytest subprocess
    os.environ["ARMADILLO_COMPACT_MODE"] = str(int(options.compact))

    # Configure instance retention on failure
    if options.keep_instances_on_failure:
        os.environ["ARMADILLO_KEEP_INSTANCES_ON_FAILURE"] = "1"
        console.print(
            "[yellow]🔧 Instances will be kept running on test failure for debugging[/yellow]"
        )
    else:
        os.environ.pop("ARMADILLO_KEEP_INSTANCES_ON_FAILURE", None)

    # Configure temp directory retention
    if options.keep_temp_dir:
        os.environ["ARMADILLO_KEEP_TEMP_DIR"] = "1"
        console.print(
            "[yellow]🔧 Temp directory will be preserved after successful test runs[/yellow]"
        )
    else:
        os.environ.pop("ARMADILLO_KEEP_TEMP_DIR", None)

    # Add extra arguments
    if options.extra_args:
        pytest_args.extend(options.extra_args)

    # Configure output directory and formats
    options.output_dir.mkdir(parents=True, exist_ok=True)
    if "junit" in options.formats:
        pytest_args.extend(["--junitxml", str(options.output_dir / "junit.xml")])

    # Configure parallel execution
    if options.parallel:
        try:
            pytest_args.extend(["-n", str(options.max_workers or "auto")])
        except ImportError:
            console.print(
                "[yellow]pytest-xdist not installed, running sequentially[/yellow]"
            )

    # Execute tests
    console.print(f"[cyan]Running tests with command:[/cyan] {' '.join(pytest_args)}")

    # Determine effective global timeout (use explicit value or default from config)
    effective_global_timeout = (
        options.global_timeout if options.global_timeout else config.test_timeout
    )
    console.print(f"[cyan]Global timeout: {effective_global_timeout}s[/cyan]")

    # Start pytest subprocess (with or without output monitoring)
    if options.output_idle_timeout:
        # Enable output idle timeout monitoring - requires stdout/stderr capture
        process = subprocess.Popen(
            pytest_args,
            cwd=Path.cwd(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,  # Line buffered
            universal_newlines=True,
        )
    else:
        # No idle timeout monitoring - simple execution
        process = subprocess.Popen(
            pytest_args,
            cwd=Path.cwd(),
        )

    # Create centralized timeout handler
    timeout_handler = TimeoutHandler(
        process=process,
        console=console,
        global_timeout=effective_global_timeout,
        output_idle_timeout=options.output_idle_timeout,
    )

    # Future extension point: diagnostic collection hook can be set here
    # See timeout_handler.set_pre_terminate_hook() for details

    # Start timeout monitoring
    timeout_handler.start_monitoring()

    # If output idle monitoring is enabled, stream output and update timestamp
    if options.output_idle_timeout:

        def output_reader():
            """Read and forward output line-by-line, updating timeout handler."""
            try:
                for line in process.stdout:
                    sys.stdout.write(line)
                    sys.stdout.flush()
                    timeout_handler.update_output_timestamp()
            except Exception as e:
                logger.error("Error reading process output: %s", e)

        reader_thread = threading.Thread(target=output_reader, daemon=True)
        reader_thread.start()

    # Track signal handling state
    signal_count = 0

    def signal_handler(signum, _frame):
        """Two-stage signal handling: graceful first, force kill on second signal."""
        nonlocal signal_count
        signal_count += 1

        if signal_count == 1:
            # First signal: forward to subprocess for graceful cleanup
            if process.poll() is None:  # Process still running
                console.print(
                    "\n[yellow]Initiating graceful shutdown (Ctrl-C again to force kill)...[/yellow]"
                )
                try:
                    process.send_signal(signum)
                except ProcessLookupError:
                    pass
        else:
            # Second signal: force kill everything
            console.print("\n[red]Force killing all processes...[/red]")
            if process.poll() is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            sys.exit(128 + signum)

    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Wait for subprocess to complete
    try:
        returncode = process.wait()
        timeout_handler.stop_monitoring()
    except KeyboardInterrupt:
        # First Ctrl-C: signal handler forwarded SIGINT to subprocess for graceful cleanup
        # Wait for it to finish
        try:
            returncode = process.wait()
            timeout_handler.stop_monitoring()
        except KeyboardInterrupt:
            # Second Ctrl-C while waiting: force kill
            if process.poll() is None:
                process.kill()
            timeout_handler.stop_monitoring()
            sys.exit(130)

    # Check if timeout was triggered and adjust exit message
    if timeout_handler.was_timeout_triggered():
        timeout_type = timeout_handler.get_timeout_type()
        if timeout_type == TimeoutType.GLOBAL:
            console.print(
                f"[red]❌ Tests killed due to global timeout ({effective_global_timeout}s)[/red]"
            )
        elif timeout_type == TimeoutType.OUTPUT_IDLE:
            console.print(
                f"[red]❌ Tests killed due to output idle timeout ({options.output_idle_timeout}s)[/red]"
            )
        sys.exit(124)  # timeout exit code

    if returncode == 0:
        console.print("[green]✅ All tests passed![/green]")
    else:
        console.print(f"[red]❌ Tests failed (exit code: {returncode})[/red]")
    sys.exit(returncode)


@test_app.command(name="list")
def list_markers():
    """List available test markers and fixtures."""
    table = Table(title="Available Test Markers")
    table.add_column("Marker", style="cyan")
    table.add_column("Description", style="green")
    markers = [
        ("arango_single", "Requires single ArangoDB server"),
        ("arango_cluster", "Requires ArangoDB cluster"),
        ("slow", "Long-running test"),
        ("crash_test", "Test involves crashes"),
        ("rta_suite", "RTA test suite marker"),
    ]
    for marker, description in markers:
        table.add_row(marker, description)
    console.print(table)
    table = Table(title="Available Test Fixtures")
    table.add_column("Fixture", style="cyan")
    table.add_column("Scope", style="yellow")
    table.add_column("Description", style="green")
    fixtures = [
        ("arango_single_server", "session", "Single server for entire test session"),
        (
            "arango_single_server_function",
            "function",
            "Single server per test function",
        ),
    ]
    for fixture, scope, description in fixtures:
        table.add_row(fixture, scope, description)
    console.print(table)
