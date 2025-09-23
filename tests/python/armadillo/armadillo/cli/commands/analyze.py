"""Result analysis CLI commands - Phase 1 scaffold."""

from pathlib import Path
from typing import List, Dict, Any
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from ...core.log import get_logger
from ...utils.codec import from_json_string
from ...utils.filesystem import read_text

console = Console()
logger = get_logger(__name__)
analyze_app = typer.Typer(help="Analyze test results")


@analyze_app.command()
def summary(
    result_files: List[str] = typer.Argument(help="JSON result files to analyze"),
    output_format: str = typer.Option(
        "rich", "--format", help="Output format: rich, plain, json"
    ),
):
    """Analyze test results and show summary."""
    if not result_files:
        console.print("[red]No result files provided[/red]")
        raise typer.Exit(1)
    try:
        path_objects = [Path(p) for p in result_files]
        aggregated_results = _load_results(path_objects)
        if output_format == "rich":
            _display_rich_summary(aggregated_results)
        elif output_format == "plain":
            _display_plain_summary(aggregated_results)
        elif output_format == "json":
            _display_json_summary(aggregated_results)
        else:
            console.print(f"[red]Unknown format: {output_format}[/red]")
            raise typer.Exit(1)
    except Exception as e:
        logger.error("Analysis failed: %s", e)
        console.print(f"[red]Analysis failed: {e}[/red]")
        raise typer.Exit(1)


@analyze_app.command()
def list_analyzers():
    """List available result analyzers."""
    analyzers = [
        ("pretty", "Human-readable summary with failure details", "✅ Phase 1"),
        ("table", "Column-oriented statistics table", "✅ Phase 1"),
        ("long-running", "Identify slowest tests", "⏳ Phase 2"),
        ("short-lifetime", "Detect inefficient setup/teardown ratios", "⏳ Phase 2"),
        ("resources", "Process and memory usage analysis", "⏳ Phase 2"),
        ("leaks", "SUT checker violation summary", "⏳ Phase 3"),
        ("crash-summary", "Crash and sanitizer report analysis", "⏳ Phase 4"),
        ("perf-regression", "Performance regression detection", "⏳ Phase 5"),
    ]
    table = Table(title="Available Result Analyzers")
    table.add_column("Analyzer", style="cyan")
    table.add_column("Description", style="green")
    table.add_column("Status", style="yellow")
    for name, description, status in analyzers:
        table.add_row(name, description, status)
    console.print(table)


def _load_results(result_files: List[Path]) -> Dict[str, Any]:
    """Load and aggregate result files."""
    aggregated = {
        "total_files": len(result_files),
        "total_tests": 0,
        "total_duration": 0.0,
        "summary": {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "error": 0,
            "timeout": 0,
            "crashed": 0,
        },
        "files": [],
        "failed_tests": [],
    }
    for result_file in result_files:
        if not result_file.exists():
            console.print(f"[red]Result file not found: {result_file}[/red]")
            raise typer.Exit(1)
        try:
            content = read_text(result_file)
            result_data = from_json_string(content)
            file_info = {
                "file": str(result_file),
                "duration": result_data.get("duration_s", 0.0),
                "test_count": len(result_data.get("tests", {})),
                "summary": result_data.get("meta", {}).get("summary", {}),
            }
            aggregated["files"].append(file_info)
            aggregated["total_duration"] += file_info["duration"]
            aggregated["total_tests"] += file_info["test_count"]
            file_summary = file_info["summary"]
            for key in aggregated["summary"]:
                aggregated["summary"][key] += file_summary.get(key, 0)
            tests = result_data.get("tests", {})
            for test_name, test_data in tests.items():
                if test_data.get("status") in ["failed", "error", "crashed", "timeout"]:
                    aggregated["failed_tests"].append(
                        {
                            "name": test_name,
                            "status": test_data.get("status"),
                            "duration": test_data.get("duration_s", 0.0),
                            "message": test_data.get("error_message")
                            or test_data.get("failure_message"),
                            "file": str(result_file),
                        }
                    )
        except Exception as e:
            console.print(f"[red]Failed to load {result_file}: {e}[/red]")
            raise
    return aggregated


def _display_rich_summary(results: Dict[str, Any]) -> None:
    """Display rich formatted summary."""
    summary = results["summary"]
    stats_table = Table(title="Test Summary")
    stats_table.add_column("Metric", style="cyan")
    stats_table.add_column("Value", style="green")
    stats_table.add_row("Total Files", str(results["total_files"]))
    stats_table.add_row("Total Tests", str(results["total_tests"]))
    stats_table.add_row("Total Duration", f"{results['total_duration']:.2f}s")
    stats_table.add_row("", "")
    stats_table.add_row("Passed", f"[green]{summary['passed']}[/green]")
    stats_table.add_row("Failed", f"[red]{summary['failed']}[/red]")
    stats_table.add_row("Errors", f"[red]{summary['error']}[/red]")
    stats_table.add_row("Skipped", f"[yellow]{summary['skipped']}[/yellow]")
    stats_table.add_row("Timeouts", f"[magenta]{summary['timeout']}[/magenta]")
    stats_table.add_row("Crashed", f"[red bold]{summary['crashed']}[/red bold]")
    console.print(stats_table)
    total = summary["total"]
    if total > 0:
        success_rate = summary["passed"] / total * 100
        color = (
            "green" if success_rate >= 90 else "yellow" if success_rate >= 70 else "red"
        )
        console.print(
            Panel(
                f"[{color}]Success Rate: {success_rate:.1f}% ({summary['passed']}/{total})[/{color}]",
                title="Overall Result",
            )
        )
    if results["failed_tests"]:
        failed_table = Table(title="Failed Tests", show_lines=True)
        failed_table.add_column("Test", style="cyan", max_width=40)
        failed_table.add_column("Status", style="red")
        failed_table.add_column("Duration", style="yellow")
        failed_table.add_column("Message", style="dim", max_width=60)
        for test in results["failed_tests"][:10]:
            message = (
                test.get("message", "")[:100] if test.get("message") else "No message"
            )
            failed_table.add_row(
                test["name"], test["status"], f"{test['duration']:.2f}s", message
            )
        if len(results["failed_tests"]) > 10:
            failed_table.add_row(
                f"... and {len(results['failed_tests']) - 10} more", "", "", ""
            )
        console.print(failed_table)


def _display_plain_summary(results: Dict[str, Any]) -> None:
    """Display plain text summary."""
    summary = results["summary"]
    print(f"Test Results Summary:")
    print(f"Files: {results['total_files']}")
    print(f"Tests: {results['total_tests']}")
    print(f"Duration: {results['total_duration']:.2f}s")
    print(f"Passed: {summary['passed']}")
    print(f"Failed: {summary['failed']}")
    print(f"Errors: {summary['error']}")
    print(f"Skipped: {summary['skipped']}")
    print(f"Timeouts: {summary['timeout']}")
    print(f"Crashed: {summary['crashed']}")
    total = summary["total"]
    if total > 0:
        success_rate = summary["passed"] / total * 100
        print(f"Success Rate: {success_rate:.1f}%")


def _display_json_summary(results: Dict[str, Any]) -> None:
    """Display JSON summary."""
    import json

    print(json.dumps(results, indent=2, default=str))
