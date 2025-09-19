"""Test execution CLI commands."""

import sys
import subprocess
from pathlib import Path
from typing import Optional, List

import typer
from rich.console import Console
from rich.table import Table

from ...core.config import get_config
from ...core.log import get_logger

console = Console()
logger = get_logger(__name__)

# Create test subcommand app
test_app = typer.Typer(help="Execute tests")


@test_app.command()
def run(
    test_paths: List[str] = typer.Argument(
        help="Test paths to execute"
    ),
    cluster: bool = typer.Option(
        False,
        "--cluster",
        help="Use cluster deployment"
    ),
    single_server: bool = typer.Option(
        True,
        "--single-server",
        help="Use single server deployment"
    ),
    timeout: Optional[float] = typer.Option(
        None,
        "--timeout",
        help="Test timeout in seconds"
    ),
    output_dir: Path = typer.Option(
        Path("./test-results"),
        "--output-dir",
        "-o",
        help="Output directory for results"
    ),
    formats: List[str] = typer.Option(
        ["junit", "json"],
        "--format",
        help="Result output formats"
    ),
    build_dir: Optional[Path] = typer.Option(
        None,
        "--build-dir",
        "-b",
        help="ArangoDB build directory (auto-detected if not specified)"
    ),
    keep_instances_on_failure: bool = typer.Option(
        False,
        "--keep-instances-on-failure",
        help="Keep instances running on test failure"
    ),
    parallel: bool = typer.Option(
        False,
        "--parallel",
        help="Run tests in parallel"
    ),
    max_workers: Optional[int] = typer.Option(
        None,
        "--max-workers",
        help="Maximum parallel workers"
    ),
    show_output: bool = typer.Option(
        False,
        "--show-output",
        "-s",
        help="Show ArangoDB server output during tests (disables pytest capture)"
    ),
    extra_args: Optional[List[str]] = typer.Option(
        None,
        "--pytest-arg",
        help="Additional arguments to pass to pytest"
    ),
    log_level: str = typer.Option(
        "WARNING",
        "--log-level",
        help="Framework logging level (DEBUG, INFO, WARNING, ERROR)"
    ),
    compact: bool = typer.Option(
        False,
        "--compact",
        "-c",
        help="Use compact pytest-style output instead of detailed verbose output"
    )
):
    """Run tests with ArangoDB instances."""

    try:
        config = get_config()

        # Configure framework logging level (independent of server output)
        import os
        from ...core.log import LogManager

        # Configure framework using centralized config system
        from armadillo.core.config import load_config
        from armadillo.core.types import DeploymentMode

        # Determine deployment mode
        deployment_mode = DeploymentMode.CLUSTER if cluster else DeploymentMode.SINGLE_SERVER

        # Load configuration with CLI overrides
        config = load_config(
            deployment_mode=deployment_mode,
            log_level=log_level.upper(),
            compact_mode=compact
        )

        log_manager = LogManager()
        log_manager.configure(level=log_level.upper(), enable_console=True)

        # Set build directory if provided
        if build_dir:
            config.bin_dir = build_dir.resolve()
            console.print(f"[green]Using ArangoDB build directory: {config.bin_dir}[/green]")

        # Use default test paths if none provided
        if not test_paths:
            test_paths = ["tests/"]

        # Build pytest command
        pytest_args = ["python", "-m", "pytest"]

        # Add minimal quiet flags to reduce pytest noise while preserving our reporter
        if not compact:
            pytest_args.extend(["-q", "--tb=no"])  # Single quiet to minimize pytest output

        # Add test paths
        for path in test_paths:
            pytest_args.append(str(path))

        # Armadillo plugin is automatically loaded via entry point in pyproject.toml

        # Add server output visibility option
        if show_output:
            pytest_args.append("-s")  # Disable pytest output capture

        # Add custom pytest arguments
        if extra_args:
            pytest_args.extend(extra_args)

        # Add output options
        output_dir.mkdir(parents=True, exist_ok=True)

        if "junit" in formats:
            pytest_args.extend([
                "--junitxml", str(output_dir / "junit.xml")
            ])

        # Add verbosity
        if config.verbose > 0:
            pytest_args.append("-" + "v" * min(config.verbose, 3))

        # Add parallel execution if requested
        if parallel:
            try:
                import pytest_xdist
                pytest_args.extend(["-n", str(max_workers or "auto")])
            except ImportError:
                console.print("[yellow]pytest-xdist not installed, running sequentially[/yellow]")

        console.print(f"[cyan]Running tests with command:[/cyan] {' '.join(pytest_args)}")

        # Execute pytest
        result = subprocess.run(pytest_args, cwd=Path.cwd())

        if result.returncode == 0:
            console.print("[green]✅ All tests passed![/green]")
        else:
            console.print(f"[red]❌ Tests failed (exit code: {result.returncode})[/red]")

        sys.exit(result.returncode)

    except Exception as e:
        logger.error(f"Test execution failed: {e}")
        console.print(f"[red]Test execution failed: {e}[/red]")
        raise typer.Exit(1)


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

    # List fixtures
    table = Table(title="Available Test Fixtures")
    table.add_column("Fixture", style="cyan")
    table.add_column("Scope", style="yellow")
    table.add_column("Description", style="green")

    fixtures = [
        ("arango_single_server", "session", "Single server for entire test session"),
        ("arango_single_server_function", "function", "Single server per test function"),
    ]

    for fixture, scope, description in fixtures:
        table.add_row(fixture, scope, description)

    console.print(table)
