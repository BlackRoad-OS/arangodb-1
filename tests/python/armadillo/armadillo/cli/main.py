"""Main CLI entry point for Armadillo framework."""

import sys
from pathlib import Path
from typing import Optional
import typer
from pydantic import BaseModel, Field, ConfigDict
from rich.console import Console
from rich.table import Table
from ..core.config import load_config
from ..core.log import configure_logging, get_logger
from ..core.types import DeploymentMode
from .commands.test import test_app
from .commands.analyze import analyze_app


class GlobalCliOptions(BaseModel):
    """Global CLI options that can be used across all commands."""

    verbose: int = Field(0, description="Increase verbosity level")
    config_file: Optional[Path] = Field(None, description="Configuration file path")
    build_dir: Optional[Path] = Field(
        None, description="ArangoDB build directory (auto-detected if not specified)"
    )
    log_level: str = Field(
        "INFO", description="Framework logging level (DEBUG, INFO, WARNING, ERROR)"
    )

    model_config = ConfigDict(
        # Allow typer to use this model for CLI argument parsing
        use_enum_values=True,
    )


app = typer.Typer(
    name="armadillo",
    help="Modern ArangoDB Testing Framework",
    no_args_is_help=True,
    rich_markup_mode="markdown",
)
app.add_typer(test_app, name="test", help="Run tests")
app.add_typer(analyze_app, name="analyze", help="Analyze test results")
console = Console()
logger = get_logger(__name__)


@app.callback()
def main(
    ctx: typer.Context,
    verbose: int = typer.Option(
        0, "--verbose", "-v", count=True, help="Increase verbosity level"
    ),
    config_file: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Configuration file path"
    ),
    build_dir: Optional[Path] = typer.Option(
        None,
        "--build-dir",
        "-b",
        help="ArangoDB build directory (auto-detected if not specified)",
    ),
):
    """Armadillo: Modern ArangoDB Testing Framework."""
    # Create CLI options model from the parsed arguments
    cli_options = GlobalCliOptions(
        verbose=verbose,
        config_file=config_file,
        build_dir=build_dir,
        log_level="DEBUG" if verbose >= 2 else "INFO" if verbose == 1 else "WARNING",
    )

    # Store CLI options in typer context for access by subcommands
    ctx.ensure_object(dict)
    ctx.obj["cli_options"] = cli_options

    configure_logging(
        level=cli_options.log_level, enable_console=True, enable_json=False
    )
    try:
        config = load_config(
            config_file=cli_options.config_file,
            verbose=cli_options.verbose,
            log_level=cli_options.log_level,
        )
        if cli_options.build_dir:
            config.bin_dir = cli_options.build_dir.resolve()
            console.print(
                f"[green]Using ArangoDB build directory: {config.bin_dir}[/green]"
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
        current_config = get_config()
        table = Table(title="Armadillo Configuration")
        table.add_column("Setting", style="cyan")
        table.add_column("Value", style="green")
        table.add_row("Deployment Mode", current_config.deployment_mode.value)
        table.add_row("Test Timeout", f"{current_config.test_timeout}s")
        table.add_row("Result Formats", ", ".join(current_config.result_formats))
        if current_config.temp_dir:
            table.add_row("Temp Directory", str(current_config.temp_dir))
        if current_config.bin_dir:
            table.add_row("Binary Directory", str(current_config.bin_dir))
        if current_config.work_dir:
            table.add_row("Work Directory", str(current_config.work_dir))
        table.add_row(
            "Keep Instances on Failure", str(current_config.keep_instances_on_failure)
        )
        table.add_row("Verbose Level", str(current_config.verbose))
        if current_config.deployment_mode == DeploymentMode.CLUSTER:
            table.add_row("Agents", str(current_config.cluster.agents))
            table.add_row("DB Servers", str(current_config.cluster.dbservers))
            table.add_row("Coordinators", str(current_config.cluster.coordinators))
            table.add_row(
                "Replication Factor", str(current_config.cluster.replication_factor)
            )
        table.add_row(
            "Crash Analysis", str(current_config.monitoring.enable_crash_analysis)
        )
        table.add_row(
            "GDB Debugging", str(current_config.monitoring.enable_gdb_debugging)
        )
        table.add_row(
            "Memory Profiling", str(current_config.monitoring.enable_memory_profiling)
        )
        table.add_row(
            "Network Monitoring",
            str(current_config.monitoring.enable_network_monitoring),
        )
        console.print(table)
    except (ValueError, OSError) as e:
        console.print(f"[red]Error getting configuration: {e}[/red]")
        raise typer.Exit(1)


def cli_main():
    """Entry point for the CLI."""
    try:
        app()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
        sys.exit(130)
    except (RuntimeError, OSError, ValueError, ImportError) as e:
        logger.error("Unexpected error: %s", e)
        console.print(f"[red]Unexpected error: {e}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    cli_main()
