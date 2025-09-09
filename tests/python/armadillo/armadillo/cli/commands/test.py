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
    )
):
    """Run tests with ArangoDB instances."""

    try:
        config = get_config()

        # Use default test paths if none provided
        if not test_paths:
            test_paths = ["tests/"]

        # Build pytest command
        pytest_args = ["python", "-m", "pytest"]

        # Add test paths
        for path in test_paths:
            pytest_args.append(str(path))

        # Add Armadillo plugin
        pytest_args.extend([
            "-p", "armadillo.pytest_plugin.plugin",
        ])

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
