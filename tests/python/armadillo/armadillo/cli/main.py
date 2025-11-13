"""Main CLI entry point for Armadillo framework."""

import sys
from pathlib import Path
from typing import Optional
import typer
from pydantic import BaseModel, Field, ConfigDict
from rich.console import Console
from rich.table import Table
from ..core.log import configure_logging, get_logger
from ..core.types import DeploymentMode
from .commands.test import test_app
from .commands.analyze import analyze_app


class GlobalCliOptions(BaseModel):
    """Global CLI options that can be used across all commands."""

    verbose: int = Field(0, description="Increase verbosity level")
    config_file: Optional[Path] = Field(None, description="Configuration file path")
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
    log_level: Optional[str] = typer.Option(
        None,
        "--log-level",
        help="Framework logging level (DEBUG, INFO, WARNING, ERROR) - explicit level",
    ),
    config_file: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Configuration file path"
    ),
) -> None:
    """Armadillo: Modern ArangoDB Testing Framework."""
    # Validate verbose and log_level are not both specified
    if verbose > 0 and log_level is not None:
        console.print("[red]Error: Cannot specify both --verbose and --log-level[/red]")
        raise typer.Exit(1)

    # Resolve log level from verbose if not explicitly specified
    if log_level is None:
        resolved_log_level = (
            "DEBUG" if verbose >= 2 else "INFO" if verbose == 1 else "WARNING"
        )
    else:
        resolved_log_level = log_level

    # Create CLI options model from the parsed arguments
    cli_options = GlobalCliOptions(
        verbose=verbose,
        config_file=config_file,
        log_level=resolved_log_level,
    )

    # Store CLI options in typer context for access by subcommands
    ctx.ensure_object(dict)
    ctx.obj["cli_options"] = cli_options

    configure_logging(
        level=cli_options.log_level, enable_console=True, enable_json=False
    )


@app.command()
def version() -> None:
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
def config() -> None:
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
        table.add_row("Log Level", current_config.log_level)
        if current_config.deployment_mode == DeploymentMode.CLUSTER:
            table.add_row("Agents", str(current_config.cluster.agents))
            table.add_row("DB Servers", str(current_config.cluster.dbservers))
            table.add_row("Coordinators", str(current_config.cluster.coordinators))
            table.add_row(
                "Replication Factor", str(current_config.cluster.replication_factor)
            )
        table.add_row(
            "Health Check Timeout", f"{current_config.timeouts.health_check_default}s"
        )
        table.add_row(
            "Server Startup Timeout", f"{current_config.timeouts.server_startup}s"
        )
        table.add_row(
            "Deployment Timeout (Single)",
            f"{current_config.timeouts.deployment_single}s",
        )
        table.add_row(
            "Deployment Timeout (Cluster)",
            f"{current_config.timeouts.deployment_cluster}s",
        )
        table.add_row(
            "Manager Max Workers",
            str(current_config.infrastructure.manager_max_workers),
        )
        table.add_row(
            "Orchestrator Max Workers",
            str(current_config.infrastructure.orchestrator_max_workers),
        )
        table.add_row(
            "Default Base Port", str(current_config.infrastructure.default_base_port)
        )
        console.print(table)
    except (ValueError, OSError) as e:
        console.print(f"[red]Error getting configuration: {e}[/red]")
        raise typer.Exit(1)


def cli_main() -> None:
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
