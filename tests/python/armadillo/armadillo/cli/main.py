"""Main CLI entry point for Armadillo framework."""

import sys
from pathlib import Path
from typing import Optional, List

import typer
from rich.console import Console
from rich.table import Table

from ..core.config import load_config
from ..core.log import configure_logging, get_logger
from ..core.types import DeploymentMode
from .commands.test import test_app
from .commands.analyze import analyze_app

# Create the main app
app = typer.Typer(
    name="armadillo",
    help="Modern ArangoDB Testing Framework",
    no_args_is_help=True,
    rich_markup_mode="markdown"
)

# Add subcommands
app.add_typer(test_app, name="test", help="Run tests")
app.add_typer(analyze_app, name="analyze", help="Analyze test results")

console = Console()
logger = get_logger(__name__)


@app.callback()
def main(
    verbose: int = typer.Option(
        0,
        "--verbose",
        "-v",
        count=True,
        help="Increase verbosity level"
    ),
    config_file: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="Configuration file path"
    )
):
    """Armadillo: Modern ArangoDB Testing Framework."""

    # Configure logging early
    log_level = "INFO"
    if verbose >= 2:
        log_level = "DEBUG"
    elif verbose == 1:
        log_level = "INFO"

    configure_logging(
        level=log_level,
        enable_console=True,
        enable_json=False  # Console mode doesn't need JSON
    )

    # Load configuration
    try:
        load_config(
            config_file=config_file,
            verbose=verbose
        )
    except Exception as e:
        console.print(f"[red]Configuration error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def version():
    """Show version information."""
    from .. import __version__

    table = Table(title="Armadillo Version Information")
    table.add_column("Component", style="cyan")
    table.add_column("Version", style="green")

    table.add_row("Armadillo Framework", __version__)

    try:
        import pytest
        table.add_row("pytest", pytest.__version__)
    except ImportError:
        table.add_row("pytest", "[red]Not installed[/red]")

    try:
        import aiohttp
        table.add_row("aiohttp", aiohttp.__version__)
    except ImportError:
        table.add_row("aiohttp", "[red]Not installed[/red]")

    console.print(table)


@app.command()
def config():
    """Show current configuration."""
    from ..core.config import get_config

    try:
        config = get_config()

        table = Table(title="Armadillo Configuration")
        table.add_column("Setting", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Deployment Mode", config.deployment_mode.value)
        table.add_row("Test Timeout", f"{config.test_timeout}s")
        table.add_row("Result Formats", ", ".join(config.result_formats))

        if config.temp_dir:
            table.add_row("Temp Directory", str(config.temp_dir))

        if config.bin_dir:
            table.add_row("Binary Directory", str(config.bin_dir))

        if config.work_dir:
            table.add_row("Work Directory", str(config.work_dir))

        table.add_row("Keep Instances on Failure", str(config.keep_instances_on_failure))
        table.add_row("Verbose Level", str(config.verbose))

        # Cluster settings
        if config.deployment_mode == DeploymentMode.CLUSTER:
            table.add_row("Agents", str(config.cluster.agents))
            table.add_row("DB Servers", str(config.cluster.dbservers))
            table.add_row("Coordinators", str(config.cluster.coordinators))
            table.add_row("Replication Factor", str(config.cluster.replication_factor))

        # Monitoring settings
        table.add_row("Crash Analysis", str(config.monitoring.enable_crash_analysis))
        table.add_row("GDB Debugging", str(config.monitoring.enable_gdb_debugging))
        table.add_row("Memory Profiling", str(config.monitoring.enable_memory_profiling))
        table.add_row("Network Monitoring", str(config.monitoring.enable_network_monitoring))

        console.print(table)

    except Exception as e:
        console.print(f"[red]Error getting configuration: {e}[/red]")
        raise typer.Exit(1)


def cli_main():
    """Entry point for the CLI."""
    try:
        app()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        console.print(f"[red]Unexpected error: {e}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    cli_main()
