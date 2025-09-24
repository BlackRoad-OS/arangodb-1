"""Test execution CLI commands."""

import os
import sys
import subprocess
from pathlib import Path
from typing import Optional, List
import typer
from pydantic import BaseModel, Field, field_validator, ConfigDict
from rich.console import Console
from rich.table import Table
from ...core.config import get_config, load_config
from ...core.log import get_logger, LogManager
from ...core.types import DeploymentMode


class TestRunOptions(BaseModel):
    """Pydantic model for test run command options."""

    test_paths: List[str] = Field(
        default_factory=lambda: ["tests/"], description="Test paths to execute"
    )
    cluster: bool = Field(
        False, description="Use cluster deployment instead of single server"
    )
    timeout: Optional[float] = Field(
        None, description="Test timeout in seconds per test"
    )
    output_dir: Path = Field(
        Path("./test-results"), description="Output directory for results"
    )
    formats: List[str] = Field(
        default_factory=lambda: ["junit", "json"], description="Result output formats"
    )
    build_dir: Optional[Path] = Field(
        None, description="ArangoDB build directory (auto-detected if not specified)"
    )
    keep_instances_on_failure: bool = Field(
        False, description="Keep instances running on test failure for debugging"
    )
    parallel: bool = Field(False, description="Run tests in parallel")
    max_workers: Optional[int] = Field(None, description="Maximum parallel workers")
    show_output: bool = Field(
        False,
        description="Show ArangoDB server output during tests (disables pytest capture)",
    )
    extra_args: Optional[List[str]] = Field(
        None, description="Additional arguments to pass to pytest"
    )
    log_level: str = Field(
        "WARNING", description="Framework logging level (DEBUG, INFO, WARNING, ERROR)"
    )
    compact: bool = Field(
        False,
        description="Use compact pytest-style output instead of detailed verbose output",
    )

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
    test_paths: List[str] = typer.Argument(help="Test paths to execute"),
    cluster: bool = typer.Option(
        False, "--cluster", help="Use cluster deployment instead of single server"
    ),
    timeout: Optional[float] = typer.Option(
        None, "--timeout", help="Test timeout in seconds per test"
    ),
    output_dir: Path = typer.Option(
        Path("./test-results"),
        "--output-dir",
        "-o",
        help="Output directory for results",
    ),
    formats: List[str] = typer.Option(
        ["junit", "json"], "--format", help="Result output formats"
    ),
    build_dir: Optional[Path] = typer.Option(
        None,
        "--build-dir",
        "-b",
        help="ArangoDB build directory (auto-detected if not specified)",
    ),
    keep_instances_on_failure: bool = typer.Option(
        False,
        "--keep-instances-on-failure",
        help="Keep instances running on test failure for debugging",
    ),
    parallel: bool = typer.Option(False, "--parallel", help="Run tests in parallel"),
    max_workers: Optional[int] = typer.Option(
        None, "--max-workers", help="Maximum parallel workers"
    ),
    show_output: bool = typer.Option(
        False,
        "--show-output",
        "-s",
        help="Show ArangoDB server output during tests (disables pytest capture)",
    ),
    extra_args: Optional[List[str]] = typer.Option(
        None, "--pytest-arg", help="Additional arguments to pass to pytest"
    ),
    log_level: str = typer.Option(
        "WARNING",
        "--log-level",
        help="Framework logging level (DEBUG, INFO, WARNING, ERROR)",
    ),
    compact: bool = typer.Option(
        False,
        "--compact",
        "-c",
        help="Use compact pytest-style output instead of detailed verbose output",
    ),
):
    """Run tests with ArangoDB instances."""
    try:
        # Create and validate options using pydantic model
        # If no test paths provided, use default
        if not test_paths:
            test_paths = ["tests/"]

        options = TestRunOptions(
            test_paths=test_paths,
            cluster=cluster,
            timeout=timeout,
            output_dir=output_dir,
            formats=formats,
            build_dir=build_dir,
            keep_instances_on_failure=keep_instances_on_failure,
            parallel=parallel,
            max_workers=max_workers,
            show_output=show_output,
            extra_args=extra_args,
            log_level=log_level,
            compact=compact,
        )

        # Use the validated options for the rest of the function
        _execute_test_run(options)

    except Exception as e:
        logger.error("Test execution failed: %s", e)
        console.print(f"[red]Test execution failed: {e}[/red]")
        raise typer.Exit(1)


def _execute_test_run(options: TestRunOptions) -> None:
    """Execute test run with validated options."""
    # Load and configure the framework
    deployment_mode = (
        DeploymentMode.CLUSTER if options.cluster else DeploymentMode.SINGLE_SERVER
    )
    config = load_config(
        deployment_mode=deployment_mode,
        log_level=options.log_level,
        compact_mode=options.compact,
    )

    log_manager = LogManager()
    log_manager.configure(level=options.log_level, enable_console=True)

    if options.build_dir:
        config.bin_dir = options.build_dir.resolve()
        console.print(
            f"[green]Using ArangoDB build directory: {config.bin_dir}[/green]"
        )

    # Build pytest arguments
    pytest_args = ["python", "-m", "pytest"]
    pytest_args.extend(["-p", "armadillo.pytest_plugin.plugin"])

    if not options.compact:
        pytest_args.extend(["-q", "--tb=no"])

    for path in options.test_paths:
        pytest_args.append(str(path))

    if options.show_output:
        pytest_args.append("-s")

    # Configure timeout
    if options.timeout:
        pytest_args.extend(["--timeout", str(options.timeout)])

    # Configure instance retention on failure
    if options.keep_instances_on_failure:
        os.environ["ARMADILLO_KEEP_INSTANCES_ON_FAILURE"] = "1"
        console.print(
            "[yellow]🔧 Instances will be kept running on test failure for debugging[/yellow]"
        )
    else:
        os.environ.pop("ARMADILLO_KEEP_INSTANCES_ON_FAILURE", None)

    # Add extra arguments
    if options.extra_args:
        pytest_args.extend(options.extra_args)

    # Configure output directory and formats
    options.output_dir.mkdir(parents=True, exist_ok=True)
    if "junit" in options.formats:
        pytest_args.extend(["--junitxml", str(options.output_dir / "junit.xml")])

    # Configure verbosity
    if config.verbose > 0:
        pytest_args.append("-" + "v" * min(config.verbose, 3))

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
    result = subprocess.run(pytest_args, cwd=Path.cwd())

    if result.returncode == 0:
        console.print("[green]✅ All tests passed![/green]")
    else:
        console.print(f"[red]❌ Tests failed (exit code: {result.returncode})[/red]")
    sys.exit(result.returncode)


@test_app.command()
def list():
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
